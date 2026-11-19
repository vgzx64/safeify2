//! Sink tables and literal handling.
//!
//! The tables mirror `research/detect/lint_safe.py` so that the differential
//! harness compares like with like; the *inputs* are resolved paths, not text.

use syntax::ast::{self, LiteralKind};

use crate::prov::{Kind, Prov};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum SinkKind {
    FsWrite,
    FsRead,
    EnvWrite,
    EnvRead,
    ExecProgram,
    ExecArg,
}

#[derive(Clone, Copy, Debug)]
pub struct Sink {
    pub kind: SinkKind,
    /// Argument indices that carry the path/name.
    pub args: &'static [usize],
}

/// Resolve a qualified path to a sink. Paths look like `fs::write`,
/// `fs::File::create`, `process::Command::new`, `io::Write::write_all`.
pub fn sink_spec(path: &str) -> Option<Sink> {
    match path {
        // Both arguments of a two-path operation are checked: the source can be
        // caller-controlled too (`copy(from, OUT_DIR)`).
        "fs::rename" | "fs::copy" | "fs::hard_link" | "fs::symlink" => {
            Some(Sink { kind: SinkKind::FsWrite, args: &[0, 1] })
        }
        "fs::write" | "fs::create_dir" | "fs::create_dir_all" | "fs::remove_file"
        | "fs::remove_dir" | "fs::remove_dir_all" | "fs::set_permissions"
        | "fs::File::create" | "fs::File::create_new" => {
            Some(Sink { kind: SinkKind::FsWrite, args: &[0] })
        }
        // OpenOptions::open is a write only when the builder asked for one;
        // rules.rs inspects the receiver chain for write/create/append flags.
        "fs::OpenOptions::open" => Some(Sink { kind: SinkKind::FsWrite, args: &[0] }),
        "fs::read" | "fs::read_to_string" | "fs::read_dir" | "fs::metadata"
        | "fs::symlink_metadata" | "fs::canonicalize" | "fs::read_link" | "fs::File::open"
        | "path::Path::exists" | "path::Path::metadata" | "path::Path::is_file"
        | "path::Path::is_dir" => {
            Some(Sink { kind: SinkKind::FsRead, args: &[0] })
        }
        "env::set_var" | "env::remove_var" => {
            Some(Sink { kind: SinkKind::EnvWrite, args: &[0] })
        }
        "env::var" | "env::var_os" => Some(Sink { kind: SinkKind::EnvRead, args: &[0] }),
        "process::Command::new" => Some(Sink { kind: SinkKind::ExecProgram, args: &[0] }),
        "process::Command::arg"
        | "process::Command::args"
        | "process::Command::env"
        | "process::Command::envs"
        | "process::Command::current_dir" => {
            Some(Sink { kind: SinkKind::ExecArg, args: &[0] })
        }
        _ => None,
    }
}

pub fn is_shell(name: &str) -> bool {
    matches!(
        name,
        "sh" | "bash" | "zsh" | "dash" | "ksh" | "cmd" | "cmd.exe" | "powershell" | "pwsh"
    )
}

pub fn dangerous_env(name: &str) -> bool {
    matches!(
        name,
        "PATH"
            | "LD_PRELOAD"
            | "LD_LIBRARY_PATH"
            | "LD_AUDIT"
            | "DYLD_INSERT_LIBRARIES"
            | "DYLD_LIBRARY_PATH"
            | "RUSTC"
            | "RUSTC_WRAPPER"
            | "RUSTC_WORKSPACE_WRAPPER"
            | "RUSTFLAGS"
            | "CARGO"
            | "CARGO_HOME"
            | "RUSTUP_TOOLCHAIN"
            | "RUSTUP_HOME"
            | "HOME"
            | "TMPDIR"
            | "IFS"
            | "BASH_ENV"
            | "ENV"
            | "SSL_CERT_FILE"
            | "SSL_CERT_DIR"
            | "http_proxy"
            | "https_proxy"
            | "ALL_PROXY"
            | "GIT_SSH"
            | "GIT_SSH_COMMAND"
            | "NODE_OPTIONS"
            | "PYTHONPATH"
            | "PERL5LIB"
    )
}

/// Cargo-provided variables: not attacker input, even though they come from
/// the environment.
pub fn is_trusted_env(name: &str) -> bool {
    const TRUSTED: [&str; 10] = [
        "OUT_DIR",
        "CARGO_MANIFEST_DIR",
        "CARGO_MANIFEST_PATH",
        "CARGO_TARGET_DIR",
        "TARGET",
        "HOST",
        "PROFILE",
        "OPT_LEVEL",
        "DEBUG",
        "NUM_JOBS",
    ];
    const PREFIXES: [&str; 4] =
        ["CARGO_PKG_", "CARGO_CFG_", "CARGO_BIN_EXE_", "CARGO_FEATURE_"];
    TRUSTED.contains(&name) || PREFIXES.iter().any(|p| name.starts_with(p))
}

pub fn is_env_read(path: &str) -> bool {
    matches!(path, "env::var" | "env::var_os")
}

/// Functions whose result is attacker-influenced (a taint source).
pub fn taint_source(path: &str) -> Option<&'static str> {
    Some(match path {
        "env::var" | "env::var_os" => "env",
        "env::args" | "env::args_os" => "argv",
        "env::current_dir" | "env::current_exe" => "cwd",
        "io::stdin" => "stdin",
        "fs::read_to_string" | "fs::read_dir" | "fs::read_link" => "filesystem",
        "net::TcpStream::connect"
        | "net::TcpListener::bind"
        | "net::UdpSocket::bind"
        | "net::TcpStream::from_stream" => "network",
        _ => return None,
    })
}

/// Path-composition methods. Used only when the receiver's type cannot be
/// resolved: the result still derives from the receiver and the arguments.
pub fn is_composition(name: &str) -> bool {
    matches!(
        name,
        "join" | "join_with" | "with_file_name" | "with_extension" | "push" | "format"
    )
}

/// Constructors that wrap a value without changing where it came from.
pub fn is_constructor(path: &str) -> bool {
    matches!(
        path,
        "path::PathBuf::from"
            | "path::PathBuf::from_os_str"
            | "path::Path::from"
            | "path::Path::new"
            | "ffi::OsString::from"
            | "ffi::OsStr::new"
            | "string::String::from"
            | "string::String::from_utf8"
            | "string::String::from_utf8_lossy"
            | "string::String::new"
            | "boxed::Box::new"
            | "sync::Arc::new"
            | "rc::Rc::new"
            | "borrow::Cow::Borrowed"
            | "borrow::Cow::Owned"
    )
}

/// Functions that *validate* or canonicalise a path; their result is trusted.
pub fn is_trusted_producer(path: &str) -> bool {
    matches!(
        path,
        "fs::canonicalize" | "path::Path::canonicalize" | "path::Path::file_name"
            | "path::Path::parent" | "path::Path::components" | "path::Path::to_path_buf"
    )
}

/// Methods that merely move a value along (`x.unwrap().to_string()`); their
/// provenance is the receiver's.
pub fn is_truthy_adapter(name: &str) -> bool {
    matches!(
        name,
        "unwrap"
            | "expect"
            | "unwrap_or"
            | "unwrap_or_else"
            | "unwrap_or_default"
            | "clone"
            | "to_owned"
            | "to_string"
            | "to_str"
            | "to_string_lossy"
            | "into"
            | "as_ref"
            | "as_str"
            | "as_path"
            | "as_os_str"
            | "borrow"
            | "deref"
            | "trim"
            | "into_owned"
            | "to_vec"
            | "to_vec_lossy"
            | "ok"
    )
}

/// `base.join(arg)` in the text engine's terms: an absolute argument discards
/// the base; otherwise the two provenances join.
pub fn join_prov(base: &Prov, arg: &Prov) -> Prov {
    if let Some(value) = &arg.value {
        if value.starts_with('/') || value.starts_with('\\') {
            return Prov::literal(value.clone());
        }
    }
    if base.kind == Kind::Trusted && arg.kind == Kind::Literal {
        return Prov::with_detail(Kind::Trusted, base.detail.clone());
    }
    if base.is_tainted() || arg.is_tainted() {
        let detail = if base.is_tainted() {
            base.detail.clone()
        } else {
            arg.detail.clone()
        };
        return Prov::with_detail(Kind::Tainted, detail);
    }
    Prov::unknown()
}

/// Danger-table lookup for an already-resolved literal path.
/// Returns `(reason_key, level)`.
pub fn danger_path(value: &str, write: bool) -> Option<(&'static str, &'static str)> {
    let is = |prefix: &str| value.starts_with(prefix);
    if is("/proc/sys/") || is("/sys/") {
        // Configuration paths are only dangerous when written.
        return write.then_some(("kernel_config", "warn"));
    }
    if is("/proc/self/mem") || is("/proc/self/pagemap") {
        return Some(("proc_mem", "deny"));
    }
    if value.starts_with("/proc/kcore") {
        return Some(("kernel_mem", "deny"));
    }
    if value.starts_with("/proc/sysrq-trigger") {
        return Some(("sysrq", "deny"));
    }
    if is("/dev/mem") || is("/dev/kmem") || is("/dev/port") {
        return Some(("device_mem", "deny"));
    }
    if is("/etc/ld.so.preload") {
        return Some(("preload", "deny"));
    }
    if value.starts_with("\\\\.\\") || value.starts_with("\\\\?\\") {
        return Some(("windows_device", "deny"));
    }
    None
}

/// An absolute literal path whose normalisation escapes its own directory
/// prefix (`/a/../b`).
pub fn has_escaping_dotdot(value: &str) -> bool {
    if !(value.starts_with('/') || value.starts_with('\\')) {
        return false;
    }
    let mut depth = 0usize;
    for part in value.split(['/', '\\']) {
        match part {
            "" | "." => {}
            ".." => {
                if depth == 0 {
                    return true;
                }
                depth -= 1;
            }
            _ => depth += 1,
        }
    }
    false
}

pub fn literal_string(lit: &ast::Literal) -> Option<String> {
    if !matches!(lit.kind(), LiteralKind::String(_)) {
        return None;
    }
    strip_string(lit.token().text())
}

fn strip_string(text: &str) -> Option<String> {
    // Raw strings: r"..." / r#"..."# (byte/c strings are not path literals).
    if let Some(rest) = text.strip_prefix('r') {
        let hashes = rest.len() - rest.trim_start_matches('#').len();
        let rest = rest[hashes..].strip_prefix('"')?;
        let suffix = "#".repeat(hashes);
        let rest = rest.strip_suffix(&suffix)?;
        return rest.strip_suffix('"').map(str::to_string);
    }
    let body = text.strip_prefix('"')?.strip_suffix('"')?;
    let mut out = String::new();
    syntax::unescape::unescape_str(body, |range, ch| match ch {
        Ok(c) => out.push(c),
        Err(_) => out.push_str(&body[range.start..range.end]),
    });
    Some(out)
}

//! Sink tables use resolved rust-analyzer paths rather than source-text matching.

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
    let path = strip_lang_prefix(path);
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

/// Drop a leading `std::`/`core::`/`alloc::`/`proc_macro::` so the sink tables
/// can name language-crate items without caring which of the three owns them.
pub fn normalized(path: &str) -> &str {
    strip_lang_prefix(path)
}

fn strip_lang_prefix(path: &str) -> &str {
    for prefix in ["std::", "core::", "alloc::", "proc_macro::"] {
        if let Some(rest) = path.strip_prefix(prefix) {
            return rest;
        }
    }
    path
}

/// A shell program name, with or without a path or an `.exe` suffix. The
/// argument of `Command::new("/bin/sh")` is as dangerous as `"sh"`, so the
/// basename decides.
pub fn is_shell(name: &str) -> bool {
    let base = name.rsplit(['/', '\\']).next().unwrap_or(name);
    matches!(
        base.to_ascii_lowercase().as_str(),
        "sh" | "bash" | "zsh" | "dash" | "ksh" | "ash" | "fish" | "csh" | "tcsh"
            | "cmd" | "cmd.exe"
            | "powershell" | "powershell.exe"
            | "pwsh" | "pwsh.exe"
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
    matches!(strip_lang_prefix(path), "env::var" | "env::var_os")
}

/// Functions whose result is attacker-influenced (a taint source).
pub fn taint_source(path: &str) -> Option<&'static str> {
    Some(match strip_lang_prefix(path) {
        "env::var" | "env::var_os" => "env",
        "env::args" | "env::args_os" => "argv",
        "env::current_dir" | "env::current_exe" => "cwd",
        // `std::io::stdin` is defined in `io::stdio` and re-exported as
        // `io::stdin`; the resolved path carries the definition module.
        "io::stdin" | "io::stdio::stdin" => "stdin",
        "fs::read_to_string" | "fs::read_dir" | "fs::read_link" => "filesystem",
        "net::TcpStream::connect"
        | "net::TcpListener::bind"
        | "net::UdpSocket::bind"
        | "net::TcpStream::from_stream" => "network",
        _ => return None,
    })
}

/// `Option`/`Result` combinators; the value flows from the receiver through
/// the closure, which `prov.rs` evaluates with its parameter bound.
pub fn is_closure_adapter(name: &str) -> bool {
    matches!(
        name,
        "map"
            | "and_then"
            | "or_else"
            | "or"
            | "unwrap_or"
            | "unwrap_or_else"
            | "ok_or"
            | "ok_or_else"
            | "map_err"
            | "filter"
            | "filter_map"
            | "inspect"
            | "inspect_err"
            | "then"
            | "then_some"
    )
}

/// Path-composition methods. Used only when the receiver's type cannot be
/// resolved: the result still derives from the receiver and the arguments.
pub fn is_composition(name: &str) -> bool {
    matches!(
        name,
        "join" | "join_with" | "with_file_name" | "with_extension" | "push" | "format"
    )
}

/// Constructor-shaped associated-function names. Used only when the callee
/// path itself does not resolve (blanket `From` impls, prelude helpers).
pub fn is_constructor_name(name: &str) -> bool {
    matches!(
        name,
        "from" | "new" | "from_os_str" | "from_utf8" | "from_utf8_lossy" | "from_utf8_unchecked"
    )
}

/// Formatting entry points produced by `format!`/`println!` expansion; their
/// value derives from every argument.
pub fn is_formatting_producer(path: &str) -> bool {
    matches!(
        strip_lang_prefix(path),
        "fmt::format" | "fmt::write" | "fmt::Arguments::new_v1" | "fmt::Arguments::new_const"
    )
}

/// Constructors that wrap a value without changing where it came from.
pub fn is_constructor(path: &str) -> bool {
    matches!(
        strip_lang_prefix(path),
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
            | "convert::From::from"
            | "convert::TryFrom::try_from"
            | "option::Option::Some"
            | "result::Result::Ok"
            | "result::Result::Err"
            // `format!` expands to `must_use({ fmt::format(format_args!(..)) })`;
            // the wrapper returns its argument unchanged.
            | "hint::must_use"
    )
}

/// Functions that genuinely reduce a path to a safe component; their result is
/// trusted. `canonicalize` and `parent` are not here: they derive a new path
/// without confining it, so `prov.rs` keeps the receiver's class instead.
pub fn is_trusted_producer(path: &str) -> bool {
    matches!(
        strip_lang_prefix(path),
        "path::Path::file_name" | "path::Path::components" | "path::Path::to_path_buf"
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
            | "to_path_buf"
            | "to_path"
            | "as_deref"
            | "as_mut"
            | "to_ascii_lowercase"
            | "to_ascii_uppercase"
            | "trim_start"
            | "trim_end"
            | "ok"
    )
}

/// `base.join(arg)` and the other path-composition methods.
///
/// An absolute argument discards the base (`Path::join` semantics). Otherwise
/// the result is as caller-controlled as the *more* caller-controlled piece:
/// composing does not launder a `Tainted` value, but it does not promote a
/// `Param` to `Tainted` either — a caller-supplied component under a trusted
/// base is still the informational `param` class. Two literals concatenate
/// into one literal path, so the danger table can see
/// `Path::new("/etc").join("ld.so.preload")`.
pub fn join_prov(base: &Prov, arg: &Prov) -> Prov {
    if let Some(value) = &arg.value {
        if is_absolute(value) {
            return Prov::literal(value.clone());
        }
    }
    let kind = crate::prov::composition_kind(base.kind, arg.kind);
    // The detail must describe the side that decided the class: naming a
    // trusted `OUT_DIR` base for a `param` result is how a message ends up
    // saying "comes from `OUT_DIR`" about a caller-supplied path.
    let detail = if kind == base.kind && !base.detail.is_empty() {
        base.detail.clone()
    } else if kind == arg.kind && !arg.detail.is_empty() {
        arg.detail.clone()
    } else {
        String::new()
    };
    match (kind, &base.value, &arg.value) {
        (Kind::Literal, Some(base_value), Some(arg_value)) => {
            let separator = if base_value.ends_with('/') || base_value.ends_with('\\') {
                ""
            } else {
                "/"
            };
            Prov::literal(format!("{base_value}{separator}{arg_value}"))
        }
        _ => Prov::with_detail(kind, detail),
    }
}

/// Danger-table lookup for an already-resolved literal path.
/// Returns `(reason_key, level)`.
pub fn danger_path(value: &str, write: bool) -> Option<(&'static str, &'static str)> {
    let is = |prefix: &str| value.starts_with(prefix);
    if is("/proc/sys/") || is("/sys/") {
        // Configuration paths are only dangerous when written.
        return write.then_some(("kernel_config", "warn"));
    }
    if proc_pid_file(value) {
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

/// `/proc/<pid>/mem`, `/proc/<pid>/pagemap`, and the per-thread
/// `/proc/<pid>/task/<tid>/mem`. `<pid>` is `self`, `thread-self` or a number.
fn proc_pid_file(value: &str) -> bool {
    let Some(rest) = value.strip_prefix("/proc/") else {
        return false;
    };
    let mut parts = rest.split('/');
    let Some(pid) = parts.next() else {
        return false;
    };
    let is_pid = pid == "self"
        || pid == "thread-self"
        || (!pid.is_empty() && pid.bytes().all(|b| b.is_ascii_digit()));
    if !is_pid {
        return false;
    }
    match parts.next() {
        Some("mem") | Some("pagemap") => parts.next().is_none(),
        Some("task") => {
            let Some(tid) = parts.next() else {
                return false;
            };
            !tid.is_empty()
                && tid.bytes().all(|b| b.is_ascii_digit())
                && matches!(parts.next(), Some("mem"))
                && parts.next().is_none()
        }
        _ => false,
    }
}

/// An absolute literal path on either analysed platform: a POSIX/UNC root or a
/// Windows drive prefix (`C:\`, `C:/`).
pub fn is_absolute(value: &str) -> bool {
    if value.starts_with('/') || value.starts_with('\\') {
        return true;
    }
    let bytes = value.as_bytes();
    bytes.len() >= 3
        && bytes[0].is_ascii_alphabetic()
        && bytes[1] == b':'
        && (bytes[2] == b'\\' || bytes[2] == b'/')
}

/// An absolute literal path whose normalisation escapes its own directory
/// prefix (`/a/../b`).
pub fn has_escaping_dotdot(value: &str) -> bool {
    if !is_absolute(value) {
        return false;
    }
    // An absolute literal that walks up out of the directory it names: the
    // normalised path is somewhere else than the written prefix suggests.
    // `/tmp/../etc/shadow` normalises to `/etc/shadow`, which is not `/tmp`.
    for part in value.split(['/', '\\']) {
        if part == ".." {
            return true;
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

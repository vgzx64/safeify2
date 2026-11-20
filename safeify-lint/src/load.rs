//! Loading one Cargo package into a rust-analyzer database.
//!
//! Deliberately `no_deps`: the corpus crates are vendored without their
//! dependency sources, and every rule in this analysis keys off `std`/`core`
//! paths (which live in the sysroot) or on paths defined inside the crate
//! itself. Resolving external crates would need the network per crate and
//! would not change any verdict.

use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use ide_db::RootDatabase;
use load_cargo::{load_workspace, LoadCargoConfig, ProcMacroServerChoice};
use paths::AbsPathBuf;
use project_model::{CargoConfig, ProjectManifest, ProjectWorkspace, RustLibSource};
use vfs::Vfs;

pub struct Loaded {
    pub db: RootDatabase,
    pub vfs: Vfs,
    pub root: PathBuf,
}

/// Locate a sysroot that carries rust-src (`std`/`core`/`alloc` sources).
///
/// rust-analyzer hands this path to cargo as `RUSTUP_TOOLCHAIN`, so it must be
/// a sysroot root (with `bin/`), not the `rustlib/src/rust/library` directory
/// inside it — passing the latter makes cargo reject the toolchain.
///
/// Preference order: explicit environment, the shim sysroot this repository
/// already maintains for the LSP evidence path
/// (`safeify-ai/setup_rust_src.sh`), then the active toolchain.
pub fn sysroot_dir() -> Result<PathBuf> {
    const RUST_SRC_SUFFIX: &str = "lib/rustlib/src/rust/library";
    let mut candidates: Vec<PathBuf> = Vec::new();

    // A variable may name either the sysroot root or its rust-src directory.
    for var in ["SAFEIFY_SYSROOT", "SAFEIFY_RUST_SRC", "RUST_SRC_PATH"] {
        let Ok(raw) = std::env::var(var) else {
            continue;
        };
        let path = PathBuf::from(raw);
        if let Some(rel) = path
            .to_string_lossy()
            .strip_suffix(RUST_SRC_SUFFIX)
            .map(PathBuf::from)
        {
            candidates.push(rel);
        }
        candidates.push(path);
    }
    candidates.push(
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../.tools/ra-home/.local/share/ra-detect/sysroot"),
    );
    if let Ok(out) = std::process::Command::new("rustc")
        .args(["--print", "sysroot"])
        .output()
    {
        if out.status.success() {
            let sysroot = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if !sysroot.is_empty() {
                candidates.push(PathBuf::from(sysroot));
            }
        }
    }
    for cand in &candidates {
        if cand.join("bin").is_dir() && cand.join(RUST_SRC_SUFFIX).join("std").is_dir() {
            return Ok(cand.clone());
        }
    }
    bail!(
        "no sysroot with rust-src found; set SAFEIFY_SYSROOT to a sysroot root that has bin/ and {RUST_SRC_SUFFIX}/std (tried: {})",
        candidates
            .iter()
            .map(|p| p.display().to_string())
            .collect::<Vec<_>>()
            .join(", ")
    )
}

/// `feature = "<name>"` cfg atoms for every feature in the package manifest,
/// plus any caller-supplied atoms (`flag` or `key=value`).
fn cfg_overrides(root: &Path, extra: &[String]) -> project_model::CfgOverrides {
    let output = std::process::Command::new("cargo")
        .args(["metadata", "--no-deps", "--format-version", "1", "--manifest-path"])
        .arg(root.join("Cargo.toml"))
        .env("CARGO_NET_OFFLINE", "true")
        .output();
    let Ok(output) = output else {
        return project_model::CfgOverrides::default();
    };
    let Ok(meta) = serde_json::from_slice::<serde_json::Value>(&output.stdout) else {
        return project_model::CfgOverrides::default();
    };
    let mut atoms = Vec::new();
    for package in meta["packages"].as_array().into_iter().flatten() {
        for name in package["features"]
            .as_object()
            .into_iter()
            .flatten()
            .map(|(name, _)| name)
        {
            atoms.push(cfg::CfgAtom::KeyValue {
                key: intern::Symbol::intern("feature"),
                value: intern::Symbol::intern(name),
            });
        }
    }
    for spec in extra {
        match spec.split_once('=') {
            Some((key, value)) => atoms.push(cfg::CfgAtom::KeyValue {
                key: intern::Symbol::intern(key.trim()),
                value: intern::Symbol::intern(value.trim()),
            }),
            None => atoms.push(cfg::CfgAtom::Flag(intern::Symbol::intern(spec.trim()))),
        }
    }
    project_model::CfgOverrides {
        global: cfg::CfgDiff::new(atoms, Vec::new()),
        ..project_model::CfgOverrides::default()
    }
}

/// Load a package, optionally enabling extra `cfg` atoms (for example
/// `windows`, `target_family=windows`) so code compiled for another target is
/// analysed too. Feature-gated modules are always enabled.
pub fn load_crate_with_cfg(dir: &Path, extra_cfg: &[String]) -> Result<Loaded> {
    let root = dir
        .canonicalize()
        .with_context(|| format!("cannot resolve crate directory {}", dir.display()))?;
    let manifest = ProjectManifest::discover_single(&AbsPathBuf::assert_utf8(root.clone()))
        .with_context(|| format!("no Cargo.toml under {}", root.display()))?;

    let cargo_config = CargoConfig {
        no_deps: true,
        all_targets: true,
        set_test: true,
        // Enable every feature the package declares: a counterexample in a
        // feature-gated module is shipped to whoever enables the feature, and
        // with `--no-deps` cargo cannot compute the active set itself.
        cfg_overrides: cfg_overrides(&root, extra_cfg),
        sysroot: Some(RustLibSource::Path(AbsPathBuf::assert_utf8(sysroot_dir()?))),
        ..CargoConfig::default()
    };
    let load_config = LoadCargoConfig {
        load_out_dirs_from_check: false,
        with_proc_macro_server: ProcMacroServerChoice::None,
        prefill_caches: true,
        num_worker_threads: 4,
        proc_macro_processes: 0,
    };

    let progress = |_msg: String| {};
    let workspace = ProjectWorkspace::load(manifest, &cargo_config, &progress)?;
    let (db, vfs, _proc_macro) = load_workspace(workspace, &cargo_config.extra_env, &load_config)?;
    Ok(Loaded { db, vfs, root })
}

/// Load one standalone `.rs` file as its own crate.
///
/// The frozen NIRM-3 split is a directory of detached snippets
/// (`vendors/SafeNet/testdata/<api>/<n>.rs`), not Cargo targets, so this is the
/// loading mode the inventory parity harness uses. rust-analyzer resolves the
/// sysroot the same way the LSP evidence path does, which is what lets
/// `std::ptr::read` resolve in a file that has no `use` statement.
pub fn load_file(path: &Path) -> Result<Loaded> {
    let root = path
        .canonicalize()
        .with_context(|| format!("cannot resolve {}", path.display()))?;
    let manifest = ProjectManifest::from_manifest_file(AbsPathBuf::assert_utf8(root.clone()))?;
    let cargo_config = CargoConfig {
        no_deps: true,
        sysroot: Some(RustLibSource::Path(AbsPathBuf::assert_utf8(sysroot_dir()?))),
        ..CargoConfig::default()
    };
    let load_config = LoadCargoConfig {
        load_out_dirs_from_check: false,
        with_proc_macro_server: ProcMacroServerChoice::None,
        prefill_caches: true,
        num_worker_threads: 2,
        proc_macro_processes: 0,
    };
    let progress = |_msg: String| {};
    let workspace = ProjectWorkspace::load(manifest, &cargo_config, &progress)?;
    let (db, vfs, _proc_macro) =
        load_workspace(workspace, &cargo_config.extra_env, &load_config)?;
    Ok(Loaded { db, vfs, root })
}

/// Every `.rs` file under the package, skipping build output and VCS metadata.
pub fn collect_rs_files(root: &Path) -> Vec<PathBuf> {
    fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
        let Ok(entries) = std::fs::read_dir(dir) else {
            return;
        };
        let mut entries: Vec<_> = entries.flatten().collect();
        entries.sort_by_key(|e| e.file_name());
        for entry in entries {
            let path = entry.path();
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if path.is_dir() {
                if matches!(name.as_ref(), "target" | ".git" | "node_modules") {
                    continue;
                }
                walk(&path, out);
            } else if path.extension().is_some_and(|ext| ext == "rs") {
                out.push(path);
            }
        }
    }
    let mut out = Vec::new();
    walk(root, &mut out);
    out
}

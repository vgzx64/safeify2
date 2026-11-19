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
/// (`research/detect/setup_rust_src.sh`), then the active toolchain.
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
            .join("../../../.tools/ra-home/.local/share/ra-detect/sysroot"),
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

pub fn load_crate(dir: &Path) -> Result<Loaded> {
    let root = dir
        .canonicalize()
        .with_context(|| format!("cannot resolve crate directory {}", dir.display()))?;
    let manifest = ProjectManifest::discover_single(&AbsPathBuf::assert_utf8(root.clone()))
        .with_context(|| format!("no Cargo.toml under {}", root.display()))?;

    let cargo_config = CargoConfig {
        no_deps: true,
        all_targets: true,
        set_test: true,
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

//! safeify-lint — semantic analysis of the Counterexamples-in-Safe-Rust
//! patterns (filesystem, command execution, build-time effects, environment),
//! computed over rust-analyzer's resolved model.
//!
//! Usage: `safeify-lint --crate <DIR> [--out findings.json]`

mod load;
mod paths;
mod prov;
mod rules;
mod sink;

use std::path::PathBuf;

use anyhow::{bail, Context, Result};
use hir::Semantics;
use rules::{Ctx, Scanner};
use syntax::ast::{self, HasVisibility};
use syntax::AstNode;
use vfs::VfsPath;

fn main() -> Result<()> {
    let mut crate_dir: Option<PathBuf> = None;
    let mut out_file: Option<PathBuf> = None;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--crate" | "-c" => crate_dir = args.next().map(PathBuf::from),
            "--out" | "-o" => out_file = args.next().map(PathBuf::from),
            "--help" | "-h" => {
                println!("usage: safeify-lint --crate <DIR> [--out <FILE>]");
                return Ok(());
            }
            other => bail!("unknown argument: {other}"),
        }
    }
    let Some(dir) = crate_dir else {
        bail!("--crate <DIR> is required (a Cargo package directory)")
    };

    let cwd = std::env::current_dir()?;
    let loaded = load::load_crate(&dir)?;
    let sema = Semantics::new(&loaded.db);
    let eval = prov::Eval { sema: &sema, db: &loaded.db };
    let mut findings: Vec<rules::Finding> = Vec::new();
    let mut files_scanned = 0usize;

    hir::attach_db(&loaded.db, || {
        for path in load::collect_rs_files(&loaded.root) {
            let vpath = VfsPath::new_real_path(path.to_string_lossy().into_owned());
            let Some((file_id, excluded)) = loaded.vfs.file_id(&vpath) else {
                continue;
            };
            if excluded == vfs::FileExcluded::Yes {
                continue;
            }
            let Ok(source) = std::fs::read_to_string(&path) else {
                continue;
            };
            let source_file = sema.parse_guess_edition(file_id);
            let display = path.strip_prefix(&cwd).unwrap_or(&path).display().to_string();
            let is_build = path
                .file_name()
                .is_some_and(|name| name == "build.rs");
            for fn_ast in item_functions(&source_file) {
                let ctx = Ctx {
                    file: display.clone(),
                    source: &source,
                    is_pub: fn_ast.visibility().is_some(),
                    is_build,
                };
                let scanner = Scanner { eval: &eval, ctx: &ctx };
                scanner.scan_fn(&fn_ast, &mut findings);
            }
            files_scanned += 1;
        }
    });

    findings.sort_by(|a, b| {
        (a.path.as_str(), a.line, a.col, a.rule.as_str())
            .cmp(&(b.path.as_str(), b.line, b.col, b.rule.as_str()))
    });
    findings.dedup_by(|a, b| {
        a.path == b.path && a.line == b.line && a.rule == b.rule && a.message == b.message
    });

    let json = serde_json::to_string_pretty(&findings)?;
    match out_file {
        Some(file) => std::fs::write(&file, json)
            .with_context(|| format!("cannot write {}", file.display()))?,
        None => println!("{json}"),
    }
    eprintln!(
        "safeify-lint: {} files, {} findings",
        files_scanned,
        findings.len()
    );
    Ok(())
}

/// Item-level functions: module items and associated functions, not nested
/// `fn` inside bodies (those are scanned as part of their owner).
fn item_functions(source_file: &ast::SourceFile) -> Vec<ast::Fn> {
    source_file
        .syntax()
        .descendants()
        .filter_map(ast::Fn::cast)
        .filter(|f| {
            f.syntax().parent().is_some_and(|parent| {
                parent.kind() == syntax::SyntaxKind::SOURCE_FILE
                    || ast::ItemList::can_cast(parent.kind())
                    || ast::AssocItemList::can_cast(parent.kind())
            })
        })
        .collect()
}

//! safeify-lint — semantic fact collection for the Counterexamples-in-Safe-Rust
//! lints, on top of a rust-analyzer database.
//!
//! Milestone 0/1: prove that a corpus crate loads into the RA database with
//! full name resolution, and report coverage numbers. Rules land next; see
//! notes/research/engine.md for the migration plan.

mod load;
mod paths;

use std::path::PathBuf;
use std::time::Instant;

use anyhow::{bail, Result};
use hir::{CallableKind, Semantics};
use syntax::{ast, AstNode};
use vfs::VfsPath;

#[derive(Default)]
struct Counts {
    files: usize,
    files_in_graph: usize,
    fns: usize,
    fns_resolved: usize,
    calls: usize,
    calls_resolved: usize,
    method_calls: usize,
    method_calls_resolved: usize,
}

fn main() -> Result<()> {
    let mut crate_dir: Option<PathBuf> = None;
    let mut dump_limit: usize = 0;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--crate" | "-c" => crate_dir = args.next().map(PathBuf::from),
            "--dump-calls" => {
                dump_limit = args.next().and_then(|n| n.parse().ok()).unwrap_or(20)
            }
            "--help" | "-h" => {
                println!("usage: safeify-lint --crate <DIR>");
                return Ok(());
            }
            other => bail!("unknown argument: {other}"),
        }
    }
    let Some(dir) = crate_dir else {
        bail!("--crate <DIR> is required (a Cargo package directory)")
    };

    let started = Instant::now();
    let loaded = load::load_crate(&dir)?;
    let load_ms = started.elapsed().as_millis() as u64;
    let sema = Semantics::new(&loaded.db);
    let mut counts = Counts::default();
    let mut dumped: Vec<serde_json::Value> = Vec::new();

    let record = |dumped: &mut Vec<serde_json::Value>, path: &std::path::Path, source_file: &ast::SourceFile, offset: syntax::TextSize, call: String, item: String| {
        if dumped.len() >= dump_limit {
            return;
        }
        let text = source_file.syntax().text().to_string();
        let off = u32::from(offset) as usize;
        let line = text[..off.min(text.len())].matches('\n').count() + 1;
        dumped.push(serde_json::json!({
            "file": path.display().to_string(),
            "line": line,
            "call": call,
            "item": item,
        }));
    };

    // hir-ty's next-solver keeps a thread-local database pointer; every entry
    // point that resolves or types an expression must run inside attach_db.
    hir::attach_db(&loaded.db, || {
        for path in load::collect_rs_files(&loaded.root) {
            counts.files += 1;
            let vpath = VfsPath::new_real_path(path.to_string_lossy().into_owned());
            let Some((file_id, excluded)) = loaded.vfs.file_id(&vpath) else {
                continue;
            };
            if excluded == vfs::FileExcluded::Yes {
                continue;
            }
            counts.files_in_graph += 1;
            let source_file = sema.parse_guess_edition(file_id);
            for f in source_file.syntax().descendants().filter_map(ast::Fn::cast) {
                counts.fns += 1;
                if sema.to_fn_def(&f).is_some() {
                    counts.fns_resolved += 1;
                }
            }
            for call in source_file
                .syntax()
                .descendants()
                .filter_map(ast::CallExpr::cast)
            {
                counts.calls += 1;
                if let Some(callee) = call.expr() {
                    if let Some(callable) = sema.resolve_expr_as_callable(&callee) {
                        counts.calls_resolved += 1;
                        if let CallableKind::Function(f) = callable.kind() {
                            let item = paths::qualified_path(&loaded.db, f);
                            record(
                                &mut dumped,
                                &path,
                                &source_file,
                                call.syntax().text_range().start(),
                                call.syntax().text().to_string(),
                                item,
                            );
                        }
                    }
                }
            }
            for call in source_file
                .syntax()
                .descendants()
                .filter_map(ast::MethodCallExpr::cast)
            {
                counts.method_calls += 1;
                if let Some(f) = sema.resolve_method_call(&call) {
                    counts.method_calls_resolved += 1;
                    let item = paths::qualified_path(&loaded.db, f);
                    record(
                        &mut dumped,
                        &path,
                        &source_file,
                        call.syntax().text_range().start(),
                        call.syntax().text().to_string(),
                        item,
                    );
                }
            }
        }
    });

    let out = serde_json::json!({
        "crate": dir.display().to_string(),
        "files": counts.files,
        "files_in_graph": counts.files_in_graph,
        "fns": counts.fns,
        "fns_resolved": counts.fns_resolved,
        "calls": counts.calls,
        "calls_resolved": counts.calls_resolved,
        "method_calls": counts.method_calls,
        "method_calls_resolved": counts.method_calls_resolved,
        "load_ms": load_ms,
        "total_ms": started.elapsed().as_millis() as u64,
        "dump": dumped,
    });
    println!("{}", serde_json::to_string_pretty(&out)?);
    Ok(())
}

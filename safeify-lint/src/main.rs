//! safeify-lint — semantic analysis of the Counterexamples-in-Safe-Rust
//! patterns (filesystem, command execution, build-time effects, environment),
//! computed over rust-analyzer's resolved model.
//!
//! Usage: `safeify-lint --crate <DIR> [--out findings.json]`

mod fields;
mod inventory;
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

fn main() {
    // Findings exit `1` (the `--min-level` gate); anything else is an engine
    // error and exits `2`, so CI can tell "the code is dirty" from "the tool
    // broke".
    if let Err(error) = run() {
        eprintln!("safeify-lint: {error:#}");
        std::process::exit(2);
    }
}

fn run() -> Result<()> {
    let mut crate_dir: Option<PathBuf> = None;
    let mut out_file: Option<PathBuf> = None;
    let mut stats_file: Option<PathBuf> = None;
    let mut min_level: Option<String> = None;
    let mut inventory_file: Option<PathBuf> = None;
    let mut extra_cfg: Vec<String> = Vec::new();
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--crate" | "-c" => crate_dir = args.next().map(PathBuf::from),
            "--inventory" => inventory_file = args.next().map(PathBuf::from),
            "--out" | "-o" => out_file = args.next().map(PathBuf::from),
            "--min-level" => min_level = args.next(),
            "--stats" => stats_file = args.next().map(PathBuf::from),
            "--extra-cfg" => {
                if let Some(spec) = args.next() {
                    extra_cfg.extend(spec.split(',').filter(|s| !s.trim().is_empty()).map(String::from));
                }
            }
            "--help" | "-h" => {
                println!(
                    "usage: safeify-lint (--crate <DIR> | --inventory <FILE>) [--out <FILE>]\n\
\n\
Analyzes one Cargo package with rust-analyzer and prints findings as JSON.\n\
With --inventory, prints the unsafe-region inventory of one standalone file\n\
instead (the frozen NIRM-3 split is a directory of detached snippets).\n\
\n\
options:\n\
  --crate <DIR>        package directory\n\
  --inventory <FILE>   standalone .rs file: unsafe regions, the calls inside\n\
                       them, raw derefs and the enclosing fn's guards\n\
  --out <FILE>         write JSON here instead of stdout\n\
  --extra-cfg <SPEC>   enable extra cfg atoms, comma separated\n\
                       (for example: windows,target_family=windows)\n\
  --stats <FILE>       write classification counters here (JSON)\n\
  --min-level <LEVEL>  exit 1 if a finding at info|warn|deny exists\n\
\n\
Suppress a rule with #[allow(safeify::<rule>)] on the item or crate, or with\n\
a '// safeify: allow(<rule>)' comment."
                );
                return Ok(());
            }
            other => bail!("unknown argument: {other}"),
        }
    }
    if let Some(file) = inventory_file {
        return inventory_mode(&file, out_file.as_deref());
    }
    let Some(dir) = crate_dir else {
        bail!("--crate <DIR> is required (a Cargo package directory)")
    };

    let cwd = std::env::current_dir()?;
    let loaded = load::load_crate_with_cfg(&dir, &extra_cfg)?;
    let sema = Semantics::new(&loaded.db);
    // Phase 1: parse every file that belongs to a crate target, once.
    struct ParsedFile {
        path: PathBuf,
        source: String,
        ast: ast::SourceFile,
        file_id: base_db::FileId,
    }
    let mut files: Vec<ParsedFile> = Vec::new();
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
            let ast = sema.parse_guess_edition(file_id);
            files.push(ParsedFile { path, source, ast, file_id });
        }
    });

    // Phase 2: crate-wide field summaries.
    let field_index = hir::attach_db(&loaded.db, || {
        fields::build(&sema, &loaded.db, files.iter().map(|f| &f.ast))
    });
    // `SAFEIFY_INTERPROC=0` turns the call-site interpretation off, which is how
    // the coverage numbers in engine.md §7 are measured (same binary, one knob).
    let interproc = std::env::var("SAFEIFY_INTERPROC").map_or(true, |v| v != "0");
    let eval = prov::Eval::new(&sema, &loaded.db, Some(&field_index), interproc);

    // Phase 3: rules.
    let mut findings: Vec<rules::Finding> = Vec::new();
    hir::attach_db(&loaded.db, || {
        for file in &files {
            let display = file
                .path
                .strip_prefix(&cwd)
                .unwrap_or(&file.path)
                .display()
                .to_string();
            let is_build = file
                .path
                .file_name()
                .is_some_and(|name| name == "build.rs");
            for fn_ast in item_functions(&file.ast) {
                // One suppression scope per function in the body: an
                // `#[allow]` on a nested `fn` must apply to that function,
                // while severity still follows the item function's visibility.
                let scopes = fn_ast
                    .syntax()
                    .descendants()
                    .filter_map(ast::Fn::cast)
                    .map(|function| {
                        let mut allowed =
                            allowed_lints(&sema, &loaded.db, file.file_id, &function);
                        allowed.extend(rules::comment_allows(&function));
                        rules::FnScope { range: function.syntax().text_range(), allowed }
                    })
                    .collect();
                let ctx = Ctx {
                    file: display.clone(),
                    source: &file.source,
                    is_pub: fn_ast.visibility().is_some(),
                    is_build,
                    scopes,
                };
                let scanner = Scanner { eval: &eval, ctx: &ctx };
                scanner.scan_fn(&fn_ast, &mut findings);
            }
        }
    });

    if let Some(file) = &stats_file {
        let stats = eval.stats.snapshot();
        if file.as_os_str() == "-" {
            // One line, so a corpus driver can attribute it to its crate.
            eprintln!("STATS {}", serde_json::to_string(&stats)?);
        } else {
            std::fs::write(file, serde_json::to_string_pretty(&stats)?)
                .with_context(|| format!("cannot write {}", file.display()))?;
        }
    }

    if let Some(threshold) = min_level {
        let wanted = level_rank(&threshold)
            .ok_or_else(|| anyhow::anyhow!("unknown --min-level `{threshold}` (info, warn, deny)"))?;
        if findings
            .iter()
            .any(|finding| level_rank(&finding.level).is_some_and(|rank| rank >= wanted))
        {
            // Print the findings first for a pipe (`--out -`/stdout) and only
            // then fail the process: exit codes are the CI contract, the JSON is
            // the report.
            let json = serde_json::to_string_pretty(&findings)?;
            match out_file {
                Some(file) => std::fs::write(&file, json)
                    .with_context(|| format!("cannot write {}", file.display()))?,
                None => println!("{json}"),
            }
            eprintln!("safeify-lint: findings at or above `{threshold}`");
            std::process::exit(1);
        }
    }

    let json = serde_json::to_string_pretty(&findings)?;
    match out_file {
        Some(file) => std::fs::write(&file, json)
            .with_context(|| format!("cannot write {}", file.display()))?,
        None => println!("{json}"),
    }
    eprintln!(
        "safeify-lint: {} files, {} field summaries, {} findings",
        files.len(),
        field_index.len(),
        findings.len()
    );
    Ok(())
}

/// `--inventory <FILE>`: the semantic unsafe-region inventory of one standalone
/// file, printed as JSON. Same loading mode as the LSP evidence path, so a
/// snippet with no `use` statement still resolves `std::ptr::read`.
fn inventory_mode(file: &std::path::Path, out: Option<&std::path::Path>) -> Result<()> {
    let loaded = load::load_file(file)?;
    let vpath = VfsPath::new_real_path(file.canonicalize()?.to_string_lossy().into_owned());
    let file_id = loaded
        .vfs
        .file_id(&vpath)
        .map(|(id, excluded)| (id, excluded))
        .filter(|(_, excluded)| *excluded == vfs::FileExcluded::No)
        .map(|(id, _)| id)
        .with_context(|| format!("{} is not in the loaded project", file.display()))?;
    let source =
        std::fs::read_to_string(file).with_context(|| format!("cannot read {}", file.display()))?;
    let inventory = hir::attach_db(&loaded.db, || {
        let sema = Semantics::new(&loaded.db);
        let ast = sema.parse_guess_edition(file_id);
        inventory::collect(&sema, &loaded.db, file_id, file, &source, &ast)
    });
    let json = serde_json::to_string_pretty(&inventory)?;
    match out {
        Some(path) => std::fs::write(path, json)
            .with_context(|| format!("cannot write {}", path.display()))?,
        None => println!("{json}"),
    }
    Ok(())
}

/// Severity ordering for `--min-level`: info < warn < deny.
fn level_rank(level: &str) -> Option<u8> {
    match level {
        "info" => Some(1),
        "warn" => Some(2),
        "deny" => Some(3),
        _ => None,
    }
}

/// Lint attributes that allow a rule for this function, resolved by
/// rust-analyzer (`#[allow]`/`#[expect]`, including crate/module level and
/// `cfg_attr`), not by scanning attribute text.
fn allowed_lints(
    sema: &Semantics<'_, ide_db::RootDatabase>,
    db: &ide_db::RootDatabase,
    file_id: base_db::FileId,
    fn_ast: &ast::Fn,
) -> Vec<String> {
    let Some(krate) = sema
        .file_to_module_defs(file_id)
        .next()
        .map(|module| module.krate(db))
    else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for node in fn_ast.syntax().ancestors() {
        let Some(item) = ast::AnyHasAttrs::cast(node) else {
            continue;
        };
        for (attr, name) in sema.lint_attrs(file_id, krate, item) {
            if matches!(attr, hir::LintAttr::Allow | hir::LintAttr::Expect) {
                out.push(name.to_string());
            }
        }
    }
    out
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

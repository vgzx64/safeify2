//! safeify-lint — semantic analysis of the Counterexamples-in-Safe-Rust
//! patterns (filesystem, command execution, build-time effects, environment),
//! computed over rust-analyzer's resolved model.
//!
//! Usage: `safeify-lint --crate <DIR> [--out findings.json]`

mod fields;
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
    let mut debug_macro: Option<PathBuf> = None;
    let mut stats_file: Option<PathBuf> = None;
    let mut extra_cfg: Vec<String> = Vec::new();
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--crate" | "-c" => crate_dir = args.next().map(PathBuf::from),
            "--out" | "-o" => out_file = args.next().map(PathBuf::from),
            "--debug-macro" => debug_macro = args.next().map(PathBuf::from),
            "--stats" => stats_file = args.next().map(PathBuf::from),
            "--extra-cfg" => {
                if let Some(spec) = args.next() {
                    extra_cfg.extend(spec.split(',').filter(|s| !s.trim().is_empty()).map(String::from));
                }
            }
            "--help" | "-h" => {
                println!(
                    "usage: safeify-lint --crate <DIR> [--out <FILE>] [--extra-cfg <SPEC>]\n\
\n\
Analyzes one Cargo package with rust-analyzer and prints findings as JSON.\n\
\n\
options:\n\
  --crate <DIR>        package directory (required)\n\
  --out <FILE>         write findings here instead of stdout\n\
  --extra-cfg <SPEC>   enable extra cfg atoms, comma separated\n\
                       (for example: windows,target_family=windows)\n\
  --debug-macro <FILE> print macro expansion status for one file\n\
  --stats <FILE>       write classification counters here (JSON)\n\
\n\
Suppress a rule with #[allow(safeify::<rule>)] on the item or crate, or with\n\
a '// safeify: allow(<rule>)' comment."
                );
                return Ok(());
            }
            other => bail!("unknown argument: {other}"),
        }
    }
    let Some(dir) = crate_dir else {
        bail!("--crate <DIR> is required (a Cargo package directory)")
    };

    let cwd = std::env::current_dir()?;
    let loaded = load::load_crate_with_cfg(&dir, &extra_cfg)?;
    let sema = Semantics::new(&loaded.db);
    if let Some(file) = &debug_macro {
        let vpath = VfsPath::new_real_path(
            file.canonicalize()?.to_string_lossy().into_owned(),
        );
        let (file_id, _) = loaded.vfs.file_id(&vpath).expect("file in vfs");
        hir::attach_db(&loaded.db, || {
            let source = sema.parse_guess_edition(file_id);
            for call in source
                .syntax()
                .descendants()
                .filter_map(ast::MacroCall::cast)
            {
                let text = call.syntax().text().to_string();
                let def = sema.to_def(&call);
                let expanded = sema.expand_macro_call(&call);
                eprintln!(
                    "macro {:?} to_def={} expand={:?}",
                    text.chars().take(48).collect::<String>(),
                    def.is_some(),
                    expanded
                        .as_ref()
                        .map(|e| e.value.text().to_string().chars().take(140).collect::<String>())
                );
                if let Some(exp) = &expanded {
                    for nested in exp.value.descendants().filter_map(ast::MacroCall::cast) {
                        let nested_text = nested.syntax().text().to_string();
                        let nested_exp = sema.expand_macro_call(&nested);
                        eprintln!(
                            "  nested {:?} expand={:?}",
                            nested_text.chars().take(40).collect::<String>(),
                            nested_exp.as_ref().map(|e| e
                                .value
                                .text()
                                .to_string()
                                .chars()
                                .take(180)
                                .collect::<String>())
                        );
                    }
                }
            }
        });
        return Ok(());
    }

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
                let mut allowed = allowed_lints(&sema, &loaded.db, file.file_id, &fn_ast);
                allowed.extend(rules::comment_allows(&fn_ast));
                let ctx = Ctx {
                    file: display.clone(),
                    source: &file.source,
                    is_pub: fn_ast.visibility().is_some(),
                    is_build,
                    allowed,
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

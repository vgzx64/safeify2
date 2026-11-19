//! Rule evaluation over resolved call sites.
//!
//! A rule is a decision about a *resolved* callee (module path + function) and
//! the provenance of its arguments. Nothing here inspects source text except
//! to turn a literal node into its value, and findings point at the argument
//! that carries the risk (the same convention as the text engine, so the
//! differential harness compares line for line).

use serde::Serialize;
use syntax::ast::{self, AstNode, HasArgList};
use syntax::TextSize;

use crate::prov::{Eval, Kind, Prov};
use crate::sink::{self, SinkKind};

#[derive(Clone, Debug, Serialize)]
pub struct Finding {
    pub path: String,
    pub line: usize,
    pub col: usize,
    pub rule: String,
    pub level: String,
    pub message: String,
}

/// Rules that are demoted to `info` outside public API and build scripts.
const DEMOTABLE: [&str; 3] = ["fs_tainted_path", "exec_basename", "exec_tainted_cmd"];

pub struct Ctx<'a> {
    pub file: String,
    pub source: &'a str,
    pub is_pub: bool,
    pub is_build: bool,
    /// Rules suppressed for this function by `#[allow(safeify::x)]` /
    /// `#[expect(safeify::x)]` (resolved by rust-analyzer, so crate-level,
    /// module-level and `cfg_attr` forms all work) or by a
    /// `// safeify: allow(x)` comment.
    pub allowed: Vec<String>,
}

impl<'a> Ctx<'a> {
    fn line_col(&self, offset: u32) -> (usize, usize) {
        let off = (offset as usize).min(self.source.len());
        let prefix = &self.source[..off];
        let line = prefix.matches('\n').count() + 1;
        let col = prefix.rsplit('\n').next().map_or(1, |l| l.chars().count() + 1);
        (line, col)
    }

    fn emit(
        &self,
        out: &mut Vec<Finding>,
        offset: TextSize,
        rule: &str,
        mut level: &'static str,
        message: String,
    ) {
        if self.allowed.iter().any(|name| allows(name, rule)) {
            return;
        }
        if level == "warn" && DEMOTABLE.contains(&rule) && !(self.is_pub || self.is_build) {
            level = "info";
        }
        let (line, col) = self.line_col(offset.into());
        out.push(Finding {
            path: self.file.clone(),
            line,
            col,
            rule: rule.to_string(),
            level: level.to_string(),
            message,
        });
    }
}

pub struct Scanner<'a, 'b> {
    pub eval: &'a Eval<'b>,
    pub ctx: &'a Ctx<'a>,
}

impl<'a, 'b> Scanner<'a, 'b> {
    pub fn scan_fn(&self, fn_ast: &ast::Fn, out: &mut Vec<Finding>) {
        let Some(body) = fn_ast.body() else {
            return;
        };
        let start_of = |node: &syntax::SyntaxNode| node.text_range().start();
        let mut writes: Vec<(u32, String)> = Vec::new();
        let mut calls: Vec<ast::CallExpr> = Vec::new();
        let mut methods: Vec<ast::MethodCallExpr> = Vec::new();
        for node in body.syntax().descendants() {
            if let Some(call) = ast::CallExpr::cast(node.clone()) {
                calls.push(call);
            } else if let Some(method) = ast::MethodCallExpr::cast(node.clone()) {
                methods.push(method);
            }
        }

        // Pre-pass: literal write sites, for the same-function dropper rule.
        for call in &calls {
            let Some(path) = self.resolve_call(call) else {
                continue;
            };
            let Some(spec) = sink::sink_spec(&path) else {
                continue;
            };
            if spec.kind != SinkKind::FsWrite {
                continue;
            }
            let Some(lit) = first_arg_literal(call) else {
                continue;
            };
            if lit.starts_with('/') || lit.starts_with('\\') {
                writes.push((u32::from(start_of(call.syntax())), lit));
            }
        }

        for call in calls {
            let Some(path) = self.resolve_call(&call) else {
                continue;
            };
            let Some(spec) = sink::sink_spec(&path) else {
                continue;
            };
            let args: Vec<ast::Expr> = call
                .arg_list()
                .map(|list| list.args().collect())
                .unwrap_or_default();
            self.sink(&path, spec.kind, spec.args, &args, Some(&call), &writes, None, out);
        }

        for mac in body.syntax().descendants().filter_map(ast::MacroCall::cast) {
            self.scan_macro(&mac, 0, out);
        }

        for method in methods {
            let Some(path) = self.resolve_method(&method) else {
                continue;
            };
            let Some(spec) = sink::sink_spec(&path) else {
                continue;
            };
            let args: Vec<ast::Expr> = method
                .arg_list()
                .map(|list| list.args().collect())
                .unwrap_or_default();
            let kind = if sink::normalized(&path) == "fs::OpenOptions::open"
                && !openoptions_writes(&method)
            {
                SinkKind::FsRead
            } else {
                spec.kind
            };
            self.sink(&path, kind, spec.args, &args, Some(&method), &writes, None, out);
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn sink(
        &self,
        _path: &str,
        kind: SinkKind,
        arg_indices: &[usize],
        args: &[ast::Expr],
        node: Option<&impl AstNode>,
        writes: &[(u32, String)],
        origin: Option<TextSize>,
        out: &mut Vec<Finding>,
    ) {
        if std::env::var_os("SAFEIFY_DEBUG").is_some() {
            let first = args
                .first()
                .map(|a| a.syntax().text().to_string())
                .unwrap_or_default();
            eprintln!(
                "SINK {_path} kind={kind:?} file={} first={:?}",
                self.ctx.file,
                first.chars().take(60).collect::<String>()
            );
        }
        match kind {
            SinkKind::FsWrite | SinkKind::FsRead => {
                let write = kind == SinkKind::FsWrite;
                for &index in arg_indices {
                    let Some(arg) = args.get(index) else {
                        continue;
                    };
                    let prov = self.eval.expr(arg);
                    let at = origin.unwrap_or_else(|| arg.syntax().text_range().start());
                    self.fs_sink(arg, &prov, at, write, out);
                }
            }
            SinkKind::EnvWrite | SinkKind::EnvRead => {
                let Some(arg) = args.first() else {
                    return;
                };
                let prov = self.eval.expr(arg);
                let Some(name) = &prov.value else {
                    return;
                };
                if !sink::dangerous_env(name) {
                    return;
                }
                let at = origin.unwrap_or_else(|| arg.syntax().text_range().start());
                if kind == SinkKind::EnvWrite {
                    self.ctx.emit(
                        out,
                        at,
                        "env_set_dangerous",
                        "warn",
                        format!("`{name}` is written by this crate; spawned processes inherit it"),
                    );
                } else {
                    self.ctx.emit(
                        out,
                        at,
                        "env_read_dangerous",
                        "info",
                        format!("`{name}` read from the environment: a taint source"),
                    );
                }
            }
            SinkKind::ExecProgram => {
                let Some(arg) = args.first() else {
                    return;
                };
                let prov = self.eval.expr(arg);
                let at = origin.unwrap_or_else(|| arg.syntax().text_range().start());
                self.exec_program(&prov, at, writes, out);
            }
            SinkKind::ExecArg => {
                let Some(arg) = args.first() else {
                    return;
                };
                let prov = self.eval.expr(arg);
                let Some(node) = node else {
                    return;
                };
                let at = origin.unwrap_or_else(|| arg.syntax().text_range().start());
                self.exec_arg(node.syntax(), &prov, at, out);
            }
        }
    }

    fn fs_sink(
        &self,
        arg: &ast::Expr,
        prov: &Prov,
        at: TextSize,
        write: bool,
        out: &mut Vec<Finding>,
    ) {
        if write && self.ctx.is_build && !under_out_dir(prov) {
            let what = prov
                .value
                .as_deref()
                .map(|v| format!("`{v}`"))
                .unwrap_or_else(|| "a caller-supplied path".to_string());
            self.ctx.emit(
                out,
                at,
                "build_outside_out_dir",
                "warn",
                format!("build script writes {what}; the write lands outside OUT_DIR"),
            );
        }
        if let Some(value) = &prov.value {
            if let Some((reason, level)) = sink::danger_path(value, write) {
                self.ctx.emit(
                    out,
                    at,
                    "fs_special_path",
                    level,
                    format!("`{value}` targets {reason}"),
                );
            }
            if sink::has_escaping_dotdot(value) {
                self.ctx.emit(
                    out,
                    at,
                    "fs_traversal_literal",
                    "warn",
                    format!("`{value}` normalises outside its own prefix"),
                );
            }
            return;
        }
        if write && prov.is_tainted() && !self.guarded(arg) {
            let level = if prov.kind == Kind::Tainted { "warn" } else { "info" };
            let detail = if prov.detail.is_empty() {
                "a caller-supplied path".to_string()
            } else {
                format!("`{}`", prov.detail)
            };
            self.ctx.emit(
                out,
                at,
                "fs_tainted_path",
                level,
                format!("path written by this call comes from {detail}"),
            );
        }
    }

    /// Is the sink argument protected by a guard that runs before it?
    ///
    /// Two shapes count, both resolved rather than text-matched:
    /// * `path.file_name()` on the value itself (only the last component is used);
    /// * a dominating `if` whose condition checks the canonicalised value with
    ///   `starts_with`, or inspects `components()` for `ParentDir`/`RootDir`.
    fn guarded(&self, arg: &ast::Expr) -> bool {
        // Any resolved `file_name()` on the value, whoever owns it
        // (`std::fs::DirEntry`, `walkdir::DirEntry`, `Path`): only the last
        // path component is used, so the write stays inside the directory.
        if self.expr_has_named_call(arg, "file_name") {
            return true;
        }
        let arg_range = arg.syntax().text_range();
        for if_expr in arg.syntax().ancestors().filter_map(ast::IfExpr::cast) {
            let Some(then_branch) = if_expr.then_branch() else {
                continue;
            };
            if !then_branch.syntax().text_range().contains_range(arg_range) {
                continue;
            }
            let Some(condition) = if_expr.condition() else {
                continue;
            };
            if self.condition_guards(&condition) {
                return true;
            }
        }
        false
    }

    fn condition_guards(&self, condition: &ast::Expr) -> bool {
        let mut canonicalised_starts_with = false;
        let mut components = false;
        let mut parent_dir = false;
        for node in condition.syntax().descendants() {
            if let Some(call) = ast::MethodCallExpr::cast(node.clone()) {
                let Some(function) = self.eval.sema.resolve_method_call(&call) else {
                    continue;
                };
                let path = crate::paths::qualified_path(self.eval.db, function);
                match sink::normalized(&path) {
                    "path::Path::starts_with" => {
                        if let Some(receiver) = call.receiver() {
                            if self.value_derives_from(
                                &receiver,
                                &["fs::canonicalize", "path::Path::canonicalize"],
                                0,
                            ) {
                                canonicalised_starts_with = true;
                            }
                        }
                    }
                    "path::Path::components" => components = true,
                    _ => {}
                }
            }
            if let Some(path_expr) = ast::PathExpr::cast(node.clone()) {
                if let Some(path) = path_expr.path() {
                    if let Some(name) = path.segment().and_then(|s| s.name_ref()) {
                        if matches!(name.text().to_string().as_str(), "ParentDir" | "RootDir") {
                            parent_dir = true;
                        }
                    }
                }
            }
        }
        canonicalised_starts_with || (components && parent_dir)
    }

    /// Does this value come from one of `paths`, directly or through a local
    /// binding (`let canonical = fs::canonicalize(p)?`)?
    fn value_derives_from(&self, expr: &ast::Expr, paths: &[&str], depth: usize) -> bool {
        if depth > 3 {
            return false;
        }
        if self.expr_has_call(expr, paths) {
            return true;
        }
        if let ast::Expr::PathExpr(path_expr) = expr {
            if let Some(path) = path_expr.path() {
                if let Some(hir::PathResolution::Local(local)) =
                    self.eval.sema.resolve_path(&path)
                {
                    let source = local.primary_source(self.eval.db);
                    let node = source.source.value.syntax().clone();
                    if let Some(ident_pat) = ast::IdentPat::cast(node) {
                        if let Some(init) = ident_pat
                            .syntax()
                            .ancestors()
                            .find_map(ast::LetStmt::cast)
                            .and_then(|l| l.initializer())
                        {
                            return self.value_derives_from(&init, paths, depth + 1);
                        }
                    }
                }
            }
        }
        false
    }

    fn expr_has_named_call(&self, expr: &ast::Expr, name: &str) -> bool {
        expr.syntax()
            .descendants()
            .filter_map(ast::MethodCallExpr::cast)
            .any(|call| {
                self.eval
                    .sema
                    .resolve_method_call(&call)
                    .map(|function| crate::paths::qualified_path(self.eval.db, function))
                    .is_some_and(|path| path.rsplit("::").next() == Some(name))
            })
    }

    fn expr_has_call(&self, expr: &ast::Expr, paths: &[&str]) -> bool {
        expr.syntax()
            .descendants()
            .filter_map(ast::CallExpr::cast)
            .any(|call| {
                self.resolve_call(&call)
                    .is_some_and(|resolved| paths.contains(&sink::normalized(&resolved)))
            })
    }

    fn exec_program(
        &self,
        prov: &Prov,
        at: TextSize,
        writes: &[(u32, String)],
        out: &mut Vec<Finding>,
    ) {
        let Some(value) = &prov.value else {
            if prov.is_tainted() {
                let detail = if prov.detail.is_empty() {
                    "caller-controlled".to_string()
                } else {
                    format!("`{}`", prov.detail)
                };
                self.ctx.emit(
                    out,
                    at,
                    "exec_tainted_cmd",
                    "warn",
                    format!("program name comes from {detail}; PATH/CWD decides what runs"),
                );
            }
            return;
        };
        if !value.contains('/') && !value.contains('\\') && !value.is_empty() {
            self.ctx.emit(
                out,
                at,
                "exec_basename",
                "warn",
                format!("`{value}` is resolved through PATH (and the CWD on Windows)"),
            );
        }
        if value.starts_with('/') || value.starts_with('\\') {
            let at_u32: u32 = at.into();
            if writes.iter().any(|(w, p)| *w < at_u32 && p == value) {
                self.ctx.emit(
                    out,
                    at,
                    "exec_written_path",
                    "warn",
                    format!("`{value}` was written by this function and is now executed"),
                );
            }
        }
    }

    fn exec_arg(&self, node: &syntax::SyntaxNode, prov: &Prov, at: TextSize, out: &mut Vec<Finding>) {
        if !prov.is_tainted() {
            return;
        }
        let Some(program) = self.command_program(node) else {
            return;
        };
        if !sink::is_shell(&program) {
            return;
        }
        let detail = if prov.detail.is_empty() {
            "caller-controlled".to_string()
        } else {
            format!("`{}`", prov.detail)
        };
        self.ctx.emit(
            out,
            at,
            "exec_shell_tainted",
            "warn",
            format!("`{program}` receives {detail}; the shell interprets it"),
        );
    }

    /// Walk `receiver` chains back to the `Command::new(<literal>)` that
    /// started them.
    fn command_program(&self, node: &syntax::SyntaxNode) -> Option<String> {
        let mut current = ast::Expr::cast(node.clone())?;
        if let ast::Expr::MethodCallExpr(m) = &current {
            current = m.receiver()?;
        }
        loop {
            match current {
                ast::Expr::MethodCallExpr(m) => current = m.receiver()?,
                ast::Expr::CallExpr(c) => {
                    if self.resolve_call(&c)
                        .as_deref()
                        .map(sink::normalized)
                        == Some("process::Command::new")
                    {
                        return first_arg_literal(&c);
                    }
                    return None;
                }
                _ => return None,
            }
        }
    }

    /// Calls written inside a macro invocation (`try!(File::create(p))`,
    /// `assert!(..)`, `matches!(..)`) are tokens in the source tree, but
    /// rust-analyzer expands them into a real syntax tree. Scan the expansion
    /// and report at the macro call site, which is where the reader looks.
    fn scan_macro(&self, call: &ast::MacroCall, depth: usize, out: &mut Vec<Finding>) {
        if depth > 3 {
            return;
        }
        let Some(expanded) = self.eval.sema.expand_macro_call(call) else {
            return;
        };
        let at = call.syntax().text_range().start();
        let writes: Vec<(u32, String)> = Vec::new();
        for node in expanded.value.descendants() {
            if let Some(inner) = ast::CallExpr::cast(node.clone()) {
                let Some(path) = self.resolve_call(&inner) else {
                    continue;
                };
                let Some(spec) = sink::sink_spec(&path) else {
                    continue;
                };
                let args: Vec<ast::Expr> = inner
                    .arg_list()
                    .map(|list| list.args().collect())
                    .unwrap_or_default();
                self.sink(&path, spec.kind, spec.args, &args, Some(&inner), &writes, Some(at), out);
            } else if let Some(inner) = ast::MethodCallExpr::cast(node.clone()) {
                let Some(path) = self.resolve_method(&inner) else {
                    continue;
                };
                let Some(spec) = sink::sink_spec(&path) else {
                    continue;
                };
                let args: Vec<ast::Expr> = inner
                    .arg_list()
                    .map(|list| list.args().collect())
                    .unwrap_or_default();
                self.sink(&path, spec.kind, spec.args, &args, Some(&inner), &writes, Some(at), out);
            } else if let Some(nested) = ast::MacroCall::cast(node.clone()) {
                self.scan_macro(&nested, depth + 1, out);
            }
        }
    }

    fn resolve_call(&self, call: &ast::CallExpr) -> Option<String> {
        let callee = call.expr()?;
        let callable = self.eval.sema.resolve_expr_as_callable(&callee)?;
        let hir::CallableKind::Function(function) = callable.kind() else {
            return None;
        };
        Some(crate::paths::qualified_path(self.eval.db, function))
    }

    fn resolve_method(&self, call: &ast::MethodCallExpr) -> Option<String> {
        let function = self.eval.sema.resolve_method_call(call)?;
        // Method resolution occasionally answers with a free function of the
        // same name (`std::fs::write` for a `.write(..)` call). A free function
        // cannot be a method: do not turn it into a sink.
        if !function.has_self_param(self.eval.db) {
            return None;
        }
        Some(crate::paths::qualified_path(self.eval.db, function))
    }
}

/// `OpenOptions::new().write(true).create(true).open(p)` is a write; a plain
/// `.read(true).open(p)` is not.
fn openoptions_writes(call: &ast::MethodCallExpr) -> bool {
    let mut current = call.receiver();
    let mut write = false;
    while let Some(ast::Expr::MethodCallExpr(m)) = current {
        if let Some(name) = m.name_ref() {
            let name = name.text().to_string();
            if matches!(name.as_str(), "write" | "append" | "create" | "create_new")
                && m.arg_list()
                    .and_then(|a| a.args().next())
                    .is_some_and(|arg| arg.syntax().text().to_string() == "true")
            {
                write = true;
            }
        }
        current = m.receiver();
    }
    write
}

/// Does a lint name from an attribute or comment cover `rule`? Accept both the
/// tool-qualified and bare spelling, matching how clippy tool lints work.
fn allows(name: &str, rule: &str) -> bool {
    name == rule || name == format!("safeify::{rule}") || name == "all" || name == "safeify"
}

/// `// safeify: allow(a, b)` directives. Comments are tokens, so this is a
/// directive scan rather than a rule decision.
pub fn comment_allows(fn_ast: &ast::Fn) -> Vec<String> {
    let mut out = Vec::new();
    let Some(body) = fn_ast.body() else {
        return out;
    };
    for token in body.syntax().descendants_with_tokens().filter_map(|it| it.into_token()) {
        if token.kind() != syntax::SyntaxKind::COMMENT {
            continue;
        }
        let text = token.text().to_string();
        let Some(rest) = text.split("safeify: allow(").nth(1) else {
            continue;
        };
        let inner = rest.split(')').next().unwrap_or(rest);
        for name in inner.split(',') {
            let name = name.trim();
            if !name.is_empty() {
                out.push(name.to_string());
            }
        }
    }
    out
}

/// Whether a build-script write target is legitimately inside the build
/// directory: a Cargo-provided variable, or a literal that names OUT_DIR/target.
fn under_out_dir(prov: &Prov) -> bool {
    if prov.kind == Kind::Trusted
        && matches!(
            prov.detail.as_str(),
            "OUT_DIR" | "CARGO_TARGET_DIR" | "CARGO_MANIFEST_DIR" | "CARGO_MANIFEST_PATH"
        )
    {
        return true;
    }
    prov.value
        .as_deref()
        .is_some_and(|v| v.contains("OUT_DIR") || v.contains("target"))
}

fn first_arg_literal(call: &ast::CallExpr) -> Option<String> {
    let first = call.arg_list()?.args().next()?;
    match &first {
        ast::Expr::Literal(lit) => sink::literal_string(lit),
        _ => None,
    }
}

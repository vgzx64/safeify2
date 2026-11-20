//! Whole-file inventory of `unsafe` regions: the semantic replacement for the
//! masked-text scanner (`research/detect/inventory.py`) that the frozen NIRM-3
//! evaluation feeds into `detect.py`.
//!
//! Every field is a resolution result rather than a text guess:
//! * a region is an `unsafe { .. }` block or the body of an `unsafe fn`, found
//!   as syntax (including `unsafe extern "C" fn` and nested blocks);
//! * a call is a `CallExpr` with a path callee or a `MethodCallExpr`, with
//!   argument spans from the AST and the resolved item when rust-analyzer can
//!   resolve it — the frozen files are detached snippets, so many callees are
//!   deliberately unresolved and the written path is kept as the callee text;
//! * a deref is a `PrefixExpr` with `UnaryOp::Deref`, and its operand type is
//!   classified raw pointer / not a raw pointer / unknown (`null`), because a
//!   corpus snippet often carries types (like `Node`) that nothing defines;
//! * an fn context is the parsed signature plus guards recognised from
//!   *resolved* call names (`is_null`, `len`, `with_capacity`, `checked_add`,
//!   ...) and macro invocations (`assert!`, `matches!`).
//!
//! Calls and derefs written inside a macro invocation (`assert_eq!(ptr::read(p))`)
//! are not expressions in the source tree, so the macro expansion is scanned too
//! and every hit is mapped back to its original source range. That keeps the
//! sites a token scan would find without scanning tokens.

use std::collections::BTreeSet;
use std::path::Path;

use hir::{CallableKind, Semantics};
use ide_db::RootDatabase;
use serde::Serialize;
use syntax::ast::{self, AstNode, HasArgList, HasName, HasVisibility};
use syntax::SyntaxNode;

use crate::paths;

#[derive(Debug, Serialize)]
pub struct FileInventory {
    pub file: String,
    pub regions: Vec<Region>,
    pub functions: Vec<FnContext>,
}

#[derive(Debug, Serialize)]
pub struct Region {
    pub kind: &'static str,
    pub name: Option<String>,
    pub start: u32,
    pub end: u32,
    pub body_start: u32,
    pub body_end: u32,
    pub calls: Vec<Call>,
    pub derefs: Vec<Deref>,
}

#[derive(Debug, Serialize)]
pub struct Call {
    pub callee: String,
    pub is_method: bool,
    /// Same convention as the text scanner: the dot for a method call, the
    /// start of the path for a path call, one past the closing `)` at the end.
    pub span: (u32, u32),
    pub args: Vec<String>,
    pub arg_spans: Vec<(u32, u32)>,
    /// Resolved `module::Type::fn` when rust-analyzer can resolve it.
    pub resolved: Option<String>,
    /// Offset of the callee name, used to decide which region owns the call.
    /// (The span starts at the dot for method calls; the name starts after it.)
    #[serde(skip)]
    pub member_start: u32,
}

#[derive(Debug, Serialize)]
pub struct Deref {
    pub offset: u32,
    pub snippet: String,
    /// `null` when the operand's type did not resolve, which is common in the
    /// frozen snippet corpus; `false` when it resolved to a non-raw-pointer.
    pub raw_ptr: Option<bool>,
}

/// A region before its call/deref lists are attached.
#[derive(Clone)]
struct RegionDesc {
    kind: &'static str,
    name: Option<String>,
    start: u32,
    end: u32,
    body_start: u32,
    body_end: u32,
}

#[derive(Debug, Serialize)]
pub struct FnContext {
    pub span: (u32, u32),
    pub name: Option<String>,
    pub is_unsafe: bool,
    pub is_pub: bool,
    pub signature: String,
    pub guards: Vec<String>,
}

pub fn collect(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    file_id: base_db::FileId,
    file: &Path,
    source: &str,
    ast: &ast::SourceFile,
) -> FileInventory {
    let mut calls = all_calls(sema, db, file_id, source, ast.syntax());
    let mut derefs = all_derefs(sema, db, file_id, ast.syntax());

    let mut descs = source_regions(ast);
    let mut expansion_descs: Vec<RegionDesc> = Vec::new();
    for mac in ast.syntax().descendants().filter_map(ast::MacroCall::cast) {
        expansion_inventory(
            sema,
            db,
            file_id,
            source,
            &mac,
            0,
            &mut calls,
            &mut derefs,
            &mut expansion_descs,
        );
    }
    // Source order, with the macro-expansion sites merged in; the same call can
    // surface twice when a macro duplicates its argument.
    calls.sort_by_key(|c| (c.span.0, c.span.1));
    calls.dedup_by(|a, b| a.span == b.span && a.is_method == b.is_method && a.callee == b.callee);
    derefs.sort_by_key(|d| d.offset);
    derefs.dedup_by(|a, b| a.offset == b.offset);

    descs.extend(expansion_descs);
    descs.sort_by_key(|d| (d.start, d.kind));
    descs.dedup_by(|a, b| a.start == b.start && a.kind == b.kind);

    let mut regions: Vec<Region> = descs
        .into_iter()
        .map(|desc| Region {
            kind: desc.kind,
            name: desc.name,
            start: desc.start,
            end: desc.end,
            body_start: desc.body_start,
            body_end: desc.body_end,
            calls: calls
                .iter()
                .filter(|c| c.member_start >= desc.body_start && c.member_start < desc.body_end)
                .map(clone_call)
                .collect(),
            derefs: derefs
                .iter()
                .filter(|d| d.offset >= desc.body_start && d.offset < desc.body_end)
                .map(|d| Deref {
                    offset: d.offset,
                    snippet: d.snippet.clone(),
                    raw_ptr: d.raw_ptr,
                })
                .collect(),
        })
        .collect();
    regions.sort_by_key(|r| r.start);

    let mut functions: Vec<FnContext> = ast
        .syntax()
        .descendants()
        .filter_map(ast::Fn::cast)
        .map(|f| fn_context(sema, db, source, &f))
        .collect();
    // Guard evidence from every call, including the ones written inside a macro
    // invocation: `assert!(p.is_null())` is a null check even though the
    // `is_null` call only exists in `assert!`'s expansion.
    for function in &mut functions {
        let mut guards: BTreeSet<String> = function.guards.drain(..).collect();
        for call in &calls {
            if call.member_start < function.span.0 || call.member_start >= function.span.1 {
                continue;
            }
            let name = call.callee.rsplit("::").next().unwrap_or(&call.callee);
            if let Some(guard) = classify_guard(name, false) {
                guards.insert(guard.to_string());
            }
        }
        function.guards = guards.into_iter().collect();
    }

    FileInventory {
        file: file.display().to_string(),
        regions,
        functions,
    }
}

/// `unsafe { .. }` blocks and `unsafe fn` bodies that exist in the source tree.
fn source_regions(ast: &ast::SourceFile) -> Vec<RegionDesc> {
    let mut out = Vec::new();
    for node in ast.syntax().descendants() {
        let (kind, name, unsafe_token, body) = if let Some(block) = ast::BlockExpr::cast(node.clone())
        {
            let Some(token) = block.unsafe_token() else {
                continue;
            };
            ("block", None, token, block.stmt_list().map(|l| l.syntax().clone()))
        } else if let Some(function) = ast::Fn::cast(node) {
            let Some(token) = function.unsafe_token() else {
                continue;
            };
            let name = function.name().map(|n| n.text().to_string());
            let body = function
                .body()
                .and_then(|b| b.stmt_list().map(|l| l.syntax().clone()));
            ("fn", name, token, body)
        } else {
            continue;
        };
        // `fn` declarations without a body and blocks without a statement list
        // cannot contain sinks; the text scanner skips them too.
        let Some(body) = body else {
            continue;
        };
        let (body_start, body_end) = body_bounds(&body);
        let block_end = body
            .parent()
            .map(|p| u32::from(p.text_range().end()))
            .unwrap_or_else(|| u32::from(body.text_range().end()));
        out.push(RegionDesc {
            kind,
            name,
            start: unsafe_token.text_range().start().into(),
            end: block_end,
            body_start,
            body_end,
        });
    }
    out
}

/// Inside-braces bounds of a block: the byte after `{` and the byte of `}`.
///
/// The statement list carries the braces in this rust-analyzer version; the
/// token check keeps the offsets right if that ever changes.
fn body_bounds(stmt_list: &SyntaxNode) -> (u32, u32) {
    let start = match stmt_list.first_token() {
        Some(token) if token.kind() == syntax::SyntaxKind::L_CURLY => {
            token.text_range().end().into()
        }
        _ => stmt_list.text_range().start().into(),
    };
    let end = match stmt_list.last_token() {
        Some(token) if token.kind() == syntax::SyntaxKind::R_CURLY => {
            token.text_range().start().into()
        }
        _ => stmt_list.text_range().end().into(),
    };
    (start, end)
}

fn clone_call(c: &Call) -> Call {
    Call {
        callee: c.callee.clone(),
        is_method: c.is_method,
        span: c.span,
        args: c.args.clone(),
        arg_spans: c.arg_spans.clone(),
        resolved: c.resolved.clone(),
        member_start: c.member_start,
    }
}

/// Source range of a node, also for nodes inside a macro expansion: the tokens
/// a macro got from its caller map back to the caller's file, tokens from the
/// macro definition do not (`original_range_opt` filters those).
fn source_range(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    file_id: base_db::FileId,
    node: &SyntaxNode,
) -> Option<(u32, u32)> {
    let range = sema.original_range_opt(node)?;
    if range.file_id.file_id(db) != file_id {
        return None;
    }
    Some((range.range.start().into(), range.range.end().into()))
}

fn all_calls(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    file_id: base_db::FileId,
    source: &str,
    root: &SyntaxNode,
) -> Vec<Call> {
    let mut out: Vec<Call> = Vec::new();
    for node in root.descendants() {
        if let Some(call) = ast::CallExpr::cast(node.clone()) {
            if let Some(call) = call_out(sema, db, file_id, &call) {
                out.push(call);
            }
        } else if let Some(method) = ast::MethodCallExpr::cast(node) {
            if let Some(call) = method_out(sema, db, file_id, source, &method) {
                out.push(call);
            }
        }
    }
    out
}

fn call_out(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    file_id: base_db::FileId,
    call: &ast::CallExpr,
) -> Option<Call> {
    let callee = call.expr()?;
    // Only path callees correspond to what the text scanner called a "path
    // call"; every unsafe API in the spec DB is one.
    let ast::Expr::PathExpr(path_expr) = &callee else {
        return None;
    };
    let callee_text = path_text(&path_expr.path()?);
    let arg_list = call.arg_list()?;
    arg_list.r_paren_token()?;
    let (start, _) = source_range(sema, db, file_id, callee.syntax())?;
    let (_, end) = source_range(sema, db, file_id, arg_list.syntax())?;
    let resolved = sema.resolve_expr_as_callable(&callee).and_then(|callable| {
        let CallableKind::Function(function) = callable.kind() else {
            return None;
        };
        Some(paths::qualified_path(db, function))
    });
    Some(Call {
        callee: callee_text,
        is_method: false,
        span: (start, end),
        args: arg_texts(&arg_list),
        arg_spans: arg_spans(sema, db, file_id, &arg_list),
        resolved,
        member_start: start,
    })
}

fn method_out(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    file_id: base_db::FileId,
    source: &str,
    method: &ast::MethodCallExpr,
) -> Option<Call> {
    let name = method.name_ref()?;
    let arg_list = method.arg_list()?;
    arg_list.r_paren_token()?;
    let (name_start, _) = source_range(sema, db, file_id, name.syntax())?;
    let start = dot_offset(source, name_start)?;
    let (_, end) = source_range(sema, db, file_id, arg_list.syntax())?;
    let resolved = sema
        .resolve_method_call(method)
        .map(|function| paths::qualified_path(db, function));
    Some(Call {
        callee: name.text().to_string(),
        is_method: true,
        span: (start, end),
        args: arg_texts(&arg_list),
        arg_spans: arg_spans(sema, db, file_id, &arg_list),
        resolved,
        member_start: start + 1,
    })
}

/// Path as written, without generic arguments (`Box::<T>::from_raw` ->
/// `Box::from_raw`) — the form the spec DB is keyed by.
fn path_text(path: &ast::Path) -> String {
    let segments: Vec<String> = path
        .segments()
        .filter_map(|segment| segment.name_ref().map(|n| n.text().to_string()))
        .collect();
    segments.join("::")
}

fn arg_texts(arg_list: &ast::ArgList) -> Vec<String> {
    arg_list
        .args()
        .map(|arg| arg.syntax().text().to_string())
        .collect()
}

fn arg_spans(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    file_id: base_db::FileId,
    arg_list: &ast::ArgList,
) -> Vec<(u32, u32)> {
    arg_list
        .args()
        .filter_map(|arg| source_range(sema, db, file_id, arg.syntax()))
        .collect()
}

fn all_derefs(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    file_id: base_db::FileId,
    root: &SyntaxNode,
) -> Vec<Deref> {
    root.descendants()
        .filter_map(ast::PrefixExpr::cast)
        .filter_map(|prefix| deref_out(sema, db, file_id, &prefix))
        .collect()
}

fn deref_out(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    file_id: base_db::FileId,
    prefix: &ast::PrefixExpr,
) -> Option<Deref> {
    if prefix.op_kind() != Some(ast::UnaryOp::Deref) {
        return None;
    }
    let (op, operand) = (prefix.op_token()?, prefix.expr()?);
    let range = sema.original_range_opt(prefix.syntax())?;
    if range.file_id.file_id(db) != file_id {
        return None;
    }
    let offset = range.range.start().into();
    // Raw pointer, provably not a raw pointer, or unresolved. The text scanner
    // reported every `*place` in a deref-looking position; the tri-state lets
    // the caller keep the unresolved ones (which is what the frozen snippets
    // mostly are) instead of silently losing them.
    let raw_ptr = match sema.type_of_expr(&operand) {
        Some(info) => {
            if info.original.is_raw_ptr() {
                Some(true)
            } else if info.adjusted.as_ref().is_some_and(|t| t.is_raw_ptr()) {
                Some(true)
            } else if info.original.is_unknown() {
                None
            } else {
                Some(false)
            }
        }
        None => None,
    };
    // Keep the `*` and the operand as written (`*self.head`, not `* p`).
    let _ = op;
    Some(Deref {
        offset,
        snippet: source_text(sema, db, prefix.syntax()),
        raw_ptr,
    })
}

/// Text of a node as it appears in its original file (for a macro expansion,
/// the caller's text). Falls back to the expansion's own text.
fn source_text(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    node: &SyntaxNode,
) -> String {
    sema.original_range_opt(node)
        .map(|range| range.text(db).to_string())
        .unwrap_or_else(|| node.text().to_string())
}

/// Offset of the `.` that precedes a method name at `name_start`.
fn dot_offset(source: &str, name_start: u32) -> Option<u32> {
    let bytes = source.as_bytes();
    let mut i = name_start as usize;
    while i > 0 && bytes[i - 1].is_ascii_whitespace() {
        i -= 1;
    }
    (i > 0 && bytes[i - 1] == b'.').then(|| (i - 1) as u32)
}

fn fn_context(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    source: &str,
    function: &ast::Fn,
) -> FnContext {
    let name = function.name().map(|n| n.text().to_string());
    let signature_start: u32 = function
        .fn_token()
        .map(|t| t.text_range().start().into())
        .unwrap_or_else(|| function.syntax().text_range().start().into());
    let (signature_end, end) = match function.body() {
        Some(body) => (
            u32::from(body.syntax().text_range().start()),
            u32::from(body.syntax().text_range().end()),
        ),
        None => {
            let end = u32::from(function.syntax().text_range().end());
            (end, end)
        }
    };
    let signature = source
        .get(signature_start as usize..signature_end as usize)
        .unwrap_or_default()
        .trim()
        .to_string();
    let guards = function
        .body()
        .map(|body| guards_in(sema, db, &body))
        .unwrap_or_default();
    FnContext {
        span: (signature_start, end),
        name,
        is_unsafe: function.unsafe_token().is_some(),
        is_pub: function.visibility().is_some(),
        signature,
        guards,
    }
}

/// Calls and derefs that exist only in a macro expansion, reported at the
/// source ranges their tokens came from. Depth-capped like the rule scanner.
fn expansion_inventory(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    file_id: base_db::FileId,
    source: &str,
    mac: &ast::MacroCall,
    depth: usize,
    calls: &mut Vec<Call>,
    derefs: &mut Vec<Deref>,
    regions: &mut Vec<RegionDesc>,
) {
    if depth > 3 {
        return;
    }
    let Some(expanded) = sema.expand_macro_call(mac) else {
        // The macro itself did not resolve (an external crate is not loaded, so
        // `log::warn!` is opaque). Its arguments are still written in this file:
        // parse the parenthesised token list as expressions, which is how those
        // call sites — and the derefs in them — are not lost.
        return parsed_macro_args(source, mac, calls, derefs, regions);
    };
    for node in expanded.value.descendants() {
        if let Some(call) = ast::CallExpr::cast(node.clone()) {
            if let Some(call) = call_out(sema, db, file_id, &call) {
                calls.push(call);
            }
        } else if let Some(method) = ast::MethodCallExpr::cast(node.clone()) {
            if let Some(call) = method_out(sema, db, file_id, source, &method) {
                calls.push(call);
            }
        } else if let Some(prefix) = ast::PrefixExpr::cast(node.clone()) {
            if let Some(deref) = deref_out(sema, db, file_id, &prefix) {
                derefs.push(deref);
            }
        } else if let Some(block) = ast::BlockExpr::cast(node.clone()) {
            if block.unsafe_token().is_some() {
                if let Some(desc) = expansion_block_region(sema, db, file_id, &block) {
                    regions.push(desc);
                }
            }
        } else if let Some(nested) = ast::MacroCall::cast(node) {
            expansion_inventory(
                sema,
                db,
                file_id,
                source,
                &nested,
                depth + 1,
                calls,
                derefs,
                regions,
            );
        }
    }
}

/// Inventory the arguments of a macro whose expansion is unavailable.
///
/// `ast::Expr::parse` runs the real parser on `( <tokens> )`; every node offset
/// is then shifted by the token list's start. Types are unknown here (there is
/// no `HirFileId`), so derefs come back with `raw_ptr: null`. Bracketed and
/// braced macro bodies are skipped: `vec![..]` holds items the parser cannot
/// treat as one expression, and brace lists are statement/definition bodies.
fn parsed_macro_args(
    source: &str,
    mac: &ast::MacroCall,
    calls: &mut Vec<Call>,
    derefs: &mut Vec<Deref>,
    regions: &mut Vec<RegionDesc>,
) {
    let Some(tree) = mac.token_tree() else {
        return;
    };
    // Parenthesised argument lists only.
    if tree.l_paren_token().is_none() || tree.r_paren_token().is_none() {
        return;
    }
    let range = tree.syntax().text_range();
    let Some(inner) = source.get(range.start().into()..range.end().into()) else {
        return;
    };
    let inner = &inner[1..inner.len() - 1];
    // `$` means a macro-definition body, not a call site.
    if inner.trim().is_empty() || inner.contains('$') {
        return;
    }
    let parsed = ast::Expr::parse(&format!("({inner})"), syntax::Edition::CURRENT);
    // `Expr::parse` only asserts that the root is an expression or an ERROR
    // node; casting is the check that decides whether to walk it.
    let root = parsed.syntax_node();
    let Some(expr) = ast::Expr::cast(root) else {
        return;
    };
    let base: u32 = range.start().into();
    let offset = |range: syntax::TextRange| u32::from(range.start()) + base;
    let end = |range: syntax::TextRange| u32::from(range.end()) + base;
    for node in expr.syntax().descendants() {
        if let Some(call) = ast::CallExpr::cast(node.clone()) {
            // Only path callees are spec-DB candidates (same universe as the
            // text scanner's "path call").
            let Some(ast::Expr::PathExpr(path_expr)) = call.expr() else {
                continue;
            };
            let (Some(path), Some(arg_list), Some(r_paren)) =
                (path_expr.path(), call.arg_list(), call.arg_list().and_then(|l| l.r_paren_token()))
            else {
                continue;
            };
            calls.push(Call {
                callee: path_text(&path),
                is_method: false,
                span: (offset(path.syntax().text_range()), end(r_paren.text_range())),
                args: arg_texts(&arg_list),
                arg_spans: spanned_args(&arg_list, &offset, &end),
                resolved: None,
                member_start: offset(path.syntax().text_range()),
            });
        } else if let Some(method) = ast::MethodCallExpr::cast(node.clone()) {
            let (Some(name), Some(arg_list), Some(r_paren)) = (
                method.name_ref(),
                method.arg_list(),
                method.arg_list().and_then(|l| l.r_paren_token()),
            ) else {
                continue;
            };
            calls.push(Call {
                callee: name.text().to_string(),
                is_method: true,
                span: (offset(name.syntax().text_range()), end(r_paren.text_range())),
                args: arg_texts(&arg_list),
                arg_spans: spanned_args(&arg_list, &offset, &end),
                resolved: None,
                member_start: offset(name.syntax().text_range()),
            });
        } else if let Some(prefix) = ast::PrefixExpr::cast(node.clone()) {
            if prefix.op_kind() != Some(ast::UnaryOp::Deref) {
                continue;
            }
            derefs.push(Deref {
                offset: offset(prefix.syntax().text_range()),
                snippet: prefix.syntax().text().to_string(),
                raw_ptr: None,
            });
        } else if let Some(block) = ast::BlockExpr::cast(node.clone()) {
            let (Some(unsafe_token), Some(stmt_list)) = (block.unsafe_token(), block.stmt_list())
            else {
                continue;
            };
            let body = stmt_list.syntax().text_range();
            regions.push(RegionDesc {
                kind: "block",
                name: None,
                start: offset(unsafe_token.text_range()),
                end: end(block.syntax().text_range()),
                body_start: offset(body) + 1,
                body_end: end(body) - 1,
            });
        }
    }
}

fn spanned_args(
    arg_list: &ast::ArgList,
    offset: &impl Fn(syntax::TextRange) -> u32,
    end: &impl Fn(syntax::TextRange) -> u32,
) -> Vec<(u32, u32)> {
    arg_list
        .args()
        .map(|arg| (offset(arg.syntax().text_range()), end(arg.syntax().text_range())))
        .collect()
}

/// An `unsafe { .. }` block written inside a macro invocation, mapped back to
/// the source range of its caller's tokens.
fn expansion_block_region(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    file_id: base_db::FileId,
    block: &ast::BlockExpr,
) -> Option<RegionDesc> {
    let range = sema.original_range_opt(block.syntax())?;
    if range.file_id.file_id(db) != file_id {
        return None;
    }
    let text = range.text(db);
    let lead = text.len() - text.trim_start().len();
    let start = u32::from(range.range.start()) + u32::try_from(lead).ok()?;
    let stmt_list = block.stmt_list()?;
    let body = sema.original_range_opt(stmt_list.syntax())?;
    if body.file_id.file_id(db) != file_id {
        return None;
    }
    Some(RegionDesc {
        kind: "block",
        name: None,
        start,
        end: range.range.end().into(),
        body_start: u32::from(body.range.start()) + 1,
        body_end: u32::from(body.range.end()).saturating_sub(1),
    })
}

/// Guard evidence in one function body: resolved call names plus macro names.
fn guards_in(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    body: &ast::BlockExpr,
) -> Vec<String> {
    let mut out = BTreeSet::new();
    for node in body.syntax().descendants() {
        let (name, is_macro) = if let Some(mac) = ast::MacroCall::cast(node.clone()) {
            let name = mac
                .path()
                .and_then(|p| p.segment())
                .and_then(|s| s.name_ref())
                .map(|n| n.text().to_string());
            (name, true)
        } else if let Some(call) = ast::CallExpr::cast(node.clone()) {
            let name = call.expr().map(|callee| callee_name(sema, db, &callee));
            (name, false)
        } else if let Some(method) = ast::MethodCallExpr::cast(node) {
            let name = method.name_ref().map(|n| n.text().to_string());
            (name, false)
        } else {
            continue;
        };
        let Some(name) = name else {
            continue;
        };
        if let Some(guard) = classify_guard(&name, is_macro) {
            out.insert(guard.to_string());
        }
    }
    out.into_iter().collect()
}

/// The short name of a call target: the resolved item when there is one, the
/// last written path segment otherwise (a detached snippet's callee).
fn callee_name(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    callee: &ast::Expr,
) -> String {
    if let Some(function) = sema
        .resolve_expr_as_callable(callee)
        .and_then(|callable| match callable.kind() {
            CallableKind::Function(function) => Some(function),
            _ => None,
        })
    {
        return function.name(db).as_str().to_string();
    }
    match callee {
        ast::Expr::PathExpr(path_expr) => path_expr
            .path()
            .map(|p| path_text(&p))
            .and_then(|text| text.rsplit("::").next().map(|s| s.to_string()))
            .unwrap_or_default(),
        _ => String::new(),
    }
}

fn classify_guard(name: &str, is_macro: bool) -> Option<&'static str> {
    if is_macro && name == "matches" {
        return Some("matches_macro");
    }
    match name {
        "is_null" => Some("null_check"),
        "assert" | "assert_eq" | "assert_ne" | "debug_assert" | "debug_assert_eq"
        | "debug_assert_ne" => Some("assert"),
        "with_capacity" => Some("with_capacity"),
        "len" | "capacity" => Some("len_cap"),
        "saturating_add" | "saturating_sub" | "checked_add" | "checked_sub" | "checked_mul"
        | "wrapping_add" | "wrapping_sub" => Some("overflow_math"),
        _ => None,
    }
}

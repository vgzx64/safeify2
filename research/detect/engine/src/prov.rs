//! Provenance over resolved expressions.
//!
//! Same lattice as the text engine (`literal < param < tainted < trusted <
//! unknown`, join = max, unknown never fires) so audit labels stay comparable,
//! but every step is a resolution result: a local is a `hir::Local` with a
//! source pattern, a callee is a `hir::Function`, a method is the trait or
//! inherent method it actually dispatches to.

use std::collections::HashSet;

use hir::{CallableKind, Local, PathResolution, Semantics};
use ide_db::RootDatabase;
use syntax::ast::{self, AstNode, HasArgList};

use crate::paths;
use crate::sink;

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub enum Kind {
    Literal,
    Param,
    Tainted,
    Trusted,
    Unknown,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Prov {
    pub kind: Kind,
    pub detail: String,
    /// Literal value, when the expression is a string literal.
    pub value: Option<String>,
}

impl Prov {
    pub fn new(kind: Kind) -> Self {
        Self { kind, detail: String::new(), value: None }
    }

    pub fn with_detail(kind: Kind, detail: impl Into<String>) -> Self {
        Self { kind, detail: detail.into(), value: None }
    }

    pub fn literal(value: String) -> Self {
        Self { kind: Kind::Literal, detail: String::new(), value: Some(value) }
    }

    pub fn unknown() -> Self {
        Self::new(Kind::Unknown)
    }

    pub fn is_tainted(&self) -> bool {
        matches!(self.kind, Kind::Param | Kind::Tainted)
    }

    /// Join two provenances: the more conservative-information one wins, with
    /// `unknown` absorbing everything (a value we cannot see never fires).
    pub fn join(a: Self, b: Self) -> Self {
        if a.kind >= b.kind {
            a
        } else {
            b
        }
    }
}

const MAX_DEPTH: usize = 12;

pub struct Eval<'a> {
    pub sema: &'a Semantics<'a, RootDatabase>,
    pub db: &'a RootDatabase,
}

impl<'a> Eval<'a> {
    pub fn expr(&self, expr: &ast::Expr) -> Prov {
        let mut seen = HashSet::new();
        self.expr_inner(expr, 0, &mut seen)
    }

    fn expr_inner(&self, expr: &ast::Expr, depth: usize, seen: &mut HashSet<Local<'a>>) -> Prov {
        if depth > MAX_DEPTH {
            return Prov::unknown();
        }
        match expr {
            ast::Expr::Literal(lit) => match sink::literal_string(lit) {
                Some(value) => Prov::literal(value),
                None => Prov::new(Kind::Literal),
            },
            ast::Expr::ParenExpr(e) => {
                e.expr().map_or(Prov::unknown(), |e| self.expr_inner(&e, depth + 1, seen))
            }
            ast::Expr::RefExpr(e) => {
                e.expr().map_or(Prov::unknown(), |e| self.expr_inner(&e, depth + 1, seen))
            }
            ast::Expr::CastExpr(e) => {
                e.expr().map_or(Prov::unknown(), |e| self.expr_inner(&e, depth + 1, seen))
            }
            ast::Expr::TryExpr(e) => {
                e.expr().map_or(Prov::unknown(), |e| self.expr_inner(&e, depth + 1, seen))
            }
            ast::Expr::AwaitExpr(e) => {
                e.expr().map_or(Prov::unknown(), |e| self.expr_inner(&e, depth + 1, seen))
            }
            ast::Expr::BlockExpr(e) => e
                .tail_expr()
                .map_or(Prov::unknown(), |e| self.expr_inner(&e, depth + 1, seen)),
            ast::Expr::IfExpr(e) => {
                let then = e
                    .then_branch()
                    .map_or(Prov::unknown(), |b| self.expr_inner(&b.into(), depth + 1, seen));
                match e.else_branch() {
                    Some(ast::ElseBranch::Block(b)) => {
                        Prov::join(then, self.expr_inner(&b.into(), depth + 1, seen))
                    }
                    Some(ast::ElseBranch::IfExpr(inner)) => {
                        Prov::join(then, self.expr_inner(&inner.into(), depth + 1, seen))
                    }
                    None => then,
                }
            }
            ast::Expr::BinExpr(e) => self.bin_expr(e, depth, seen),
            ast::Expr::PathExpr(e) => self.path_expr(e, seen),
            ast::Expr::CallExpr(e) => self.call_expr(e, depth, seen),
            ast::Expr::MethodCallExpr(e) => self.method_call(e, depth, seen),
            ast::Expr::FieldExpr(e) => e
                .expr()
                .map_or(Prov::unknown(), |b| self.field_like(&b, depth + 1, seen)),
            ast::Expr::IndexExpr(e) => e
                .base()
                .map_or(Prov::unknown(), |b| self.field_like(&b, depth + 1, seen)),
            // Macros need expansion (format!, concat!) before they are visible.
            _ => Prov::unknown(),
        }
    }

    fn bin_expr(&self, e: &ast::BinExpr, depth: usize, seen: &mut HashSet<Local<'a>>) -> Prov {
        let Some(op) = e.op_kind() else {
            return Prov::unknown();
        };
        let is_concat = matches!(
            op,
            ast::BinaryOp::ArithOp(ast::ArithOp::Add)
                | ast::BinaryOp::LogicOp(ast::LogicOp::Or)
                | ast::BinaryOp::LogicOp(ast::LogicOp::And)
        );
        if !is_concat {
            return Prov::unknown();
        }
        let (Some(lhs), Some(rhs)) = (e.lhs(), e.rhs()) else {
            return Prov::unknown();
        };
        let a = self.expr_inner(&lhs, depth + 1, seen);
        let b = self.expr_inner(&rhs, depth + 1, seen);
        Prov::join(a, b)
    }

    /// A field or element of a value: the text engine treated `self.x`,
    /// `p.x` and `v[i]` as `param`, because a struct field or collection
    /// element is caller-controlled whenever its owner is. The interprocedural
    /// field summary refines this later.
    fn field_like(&self, base: &ast::Expr, depth: usize, seen: &mut HashSet<Local<'a>>) -> Prov {
        match self.expr_inner(base, depth + 1, seen).kind {
            Kind::Param => Prov::new(Kind::Param),
            Kind::Tainted => Prov::with_detail(Kind::Tainted, "field"),
            _ => Prov::unknown(),
        }
    }

    fn path_expr(&self, e: &ast::PathExpr, seen: &mut HashSet<Local<'a>>) -> Prov {
        let Some(path) = e.path() else {
            return Prov::unknown();
        };
        match self.sema.resolve_path(&path) {
            Some(PathResolution::Local(local)) => {
                if !seen.insert(local) {
                    return Prov::new(Kind::Param);
                }
                self.local_prov(local, seen)
            }
            Some(PathResolution::Def(hir::ModuleDef::Const(_))) => Prov::new(Kind::Literal),
            _ => Prov::unknown(),
        }
    }

    /// A binding's provenance: its initializer for a `let`, `param` for a
    /// function parameter, `unknown` for other pattern bindings (match arms,
    /// `for`, `if let`) until the interprocedural pass understands them.
    fn local_prov(&self, local: Local<'a>, seen: &mut HashSet<Local<'a>>) -> Prov {
        let source = local.primary_source(self.db);
        let node = source.source.value.syntax().clone();
        let Some(ident_pat) = ast::IdentPat::cast(node.clone()) else {
            // `self`
            return Prov::new(Kind::Param);
        };
        if ident_pat
            .syntax()
            .ancestors()
            .any(|a| ast::Param::cast(a).is_some())
        {
            return Prov::new(Kind::Param);
        }
        let let_stmt = ident_pat.syntax().ancestors().find_map(ast::LetStmt::cast);
        match let_stmt.and_then(|l| l.initializer()) {
            Some(init) => {
                let prov = self.expr_inner(&init, 1, seen);
                if std::env::var_os("SAFEIFY_DEBUG").is_some() {
                    eprintln!(
                        "  LOCAL {:?} init={:?} -> {:?}",
                        ident_pat.syntax().text().to_string(),
                        init.syntax().text().to_string().chars().take(70).collect::<String>(),
                        prov.kind
                    );
                }
                prov
            }
            None => Prov::unknown(),
        }
    }

    fn call_expr(&self, call: &ast::CallExpr, depth: usize, seen: &mut HashSet<Local<'a>>) -> Prov {
        let Some(callee) = call.expr() else {
            return Prov::unknown();
        };
        let Some(callable) = self.sema.resolve_expr_as_callable(&callee) else {
            return Prov::unknown();
        };
        match callable.kind() {
            CallableKind::Function(function) => {
                let path = paths::qualified_path(self.db, function);
                self.fn_call_prov(&path, call, depth, seen)
            }
            // `Some(x)`, `Ok(x)`, tuple-struct wrappers: the value is the
            // first argument.
            CallableKind::TupleStruct(_) | CallableKind::TupleEnumVariant(_) => {
                first_arg_prov(self, call, depth, seen)
            }
            _ => Prov::unknown(),
        }
    }

    fn fn_call_prov(
        &self,
        path: &str,
        call: &ast::CallExpr,
        _depth: usize,
        _seen: &mut HashSet<Local<'a>>,
    ) -> Prov {
        if sink::is_constructor(path) {
            return first_arg_prov(self, call, _depth, _seen);
        }
        if sink::is_env_read(path) {
            // The *name* decides: Cargo supplies these, attackers do not.
            if let Some(name) = first_arg_string(call) {
                if sink::is_trusted_env(&name) {
                    return Prov::with_detail(Kind::Trusted, name);
                }
                return Prov::with_detail(Kind::Tainted, name);
            }
            return Prov::unknown();
        }
        if let Some(name) = sink::taint_source(path) {
            return Prov::with_detail(Kind::Tainted, name);
        }
        if sink::is_trusted_producer(path) {
            return Prov::with_detail(Kind::Trusted, path.to_string());
        }
        Prov::unknown()
    }

    fn method_call(
        &self,
        call: &ast::MethodCallExpr,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
    ) -> Prov {
        let receiver = call
            .receiver()
            .map_or(Prov::unknown(), |r| self.expr_inner(&r, depth + 1, seen));
        let Some(function) = self.sema.resolve_method_call(call) else {
            // Method resolution can fail on receivers whose type lives in an
            // unresolved dependency (e.g. a lock guard around `&Path`). For
            // path-composition methods the value still derives from the
            // receiver and arguments, so keep that provenance instead of
            // dropping the taint.
            let name = call
                .name_ref()
                .map(|n| n.text().to_string())
                .unwrap_or_default();
            if sink::is_composition(&name) {
                let mut prov = receiver;
                for arg in call.arg_list().map(|a| a.args()).into_iter().flatten() {
                    let arg_prov = self.expr_inner(&arg, depth + 1, seen);
                    prov = sink::join_prov(&prov, &arg_prov);
                }
                return prov;
            }
            return receiver;
        };
        let path = paths::qualified_path(self.db, function);
        if std::env::var_os("SAFEIFY_DEBUG").is_some() {
            eprintln!("  METHOD {path} recv={:?}", receiver.kind);
        }
        let name = path.rsplit("::").next().unwrap_or(&path);

        if sink::is_truthy_adapter(name) {
            return receiver;
        }
        if sink::is_trusted_producer(name) {
            return Prov::with_detail(Kind::Trusted, name.to_string());
        }
        if let Some(detail) = sink::taint_source(name) {
            return Prov::with_detail(Kind::Tainted, detail);
        }
        if name == "join" {
            let arg = call
                .arg_list()
                .and_then(|a| a.args().next())
                .map_or(Prov::unknown(), |a| self.expr_inner(&a, depth + 1, seen));
            return sink::join_prov(&receiver, &arg);
        }
        Prov::unknown()
    }
}

fn first_arg_prov<'a>(
    eval: &Eval<'a>,
    call: &ast::CallExpr,
    depth: usize,
    seen: &mut HashSet<Local<'a>>,
) -> Prov {
    let Some(first) = call.arg_list().and_then(|a| a.args().next()) else {
        return Prov::unknown();
    };
    eval.expr_inner(&first, depth + 1, seen)
}

fn first_arg_string(call: &ast::CallExpr) -> Option<String> {
    let first = call.arg_list()?.args().next()?;
    match &first {
        ast::Expr::Literal(lit) => sink::literal_string(&lit),
        _ => None,
    }
}

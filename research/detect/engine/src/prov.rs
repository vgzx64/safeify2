//! Provenance over resolved expressions.
//!
//! Same lattice as the text engine (`literal < param < tainted < trusted <
//! unknown`, join = max, unknown never fires) so audit labels stay comparable,
//! but every step is a resolution result: a local is a `hir::Local` with a
//! source pattern, a callee is a `hir::Function`, a method is the trait or
//! inherent method it actually dispatches to.
//!
//! Two mechanisms make this deeper than name-based text matching:
//! * pattern bindings (`if let`, `match`, `for`) inherit the scrutinee's
//!   provenance, and
//! * closure arguments are evaluated with their parameter bound to the
//!   receiver's provenance, so `.map(|s| PathBuf::from(s).join(..))` keeps the
//!   trust of what it started from.

use std::collections::HashSet;

use hir::{CallableKind, Local, PathResolution, Semantics};
use ide_db::RootDatabase;
use hir::HirFileId;
use syntax::ast::{self, AstNode, HasArgList};
use syntax::TextRange;

use crate::fields::{self, FieldIndex};
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

/// Bindings whose value is being substituted (closure parameters).
#[derive(Default)]
struct Subst {
    entries: Vec<((HirFileId, TextRange), Prov)>,
}

impl Subst {
    fn push(&mut self, key: (HirFileId, TextRange), prov: Prov) {
        self.entries.push((key, prov));
    }

    fn truncate(&mut self, len: usize) {
        self.entries.truncate(len);
    }

    fn get(&self, key: (HirFileId, TextRange)) -> Option<Prov> {
        self.entries
            .iter()
            .rev()
            .find(|(k, _)| *k == key)
            .map(|(_, prov)| prov.clone())
    }
}

pub struct Eval<'a> {
    pub sema: &'a Semantics<'a, RootDatabase>,
    pub db: &'a RootDatabase,
    pub fields: Option<&'a FieldIndex>,
}

impl<'a> Eval<'a> {
    pub fn expr(&self, expr: &ast::Expr) -> Prov {
        let mut seen = HashSet::new();
        let mut subst = Subst::default();
        self.expr_inner(expr, 0, &mut seen, &mut subst)
    }

    fn expr_inner(
        &self,
        expr: &ast::Expr,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        if depth > MAX_DEPTH {
            return Prov::unknown();
        }
        match expr {
            ast::Expr::Literal(lit) => match sink::literal_string(lit) {
                Some(value) => Prov::literal(value),
                None => Prov::new(Kind::Literal),
            },
            ast::Expr::ParenExpr(e) => e
                .expr()
                .map_or(Prov::unknown(), |e| self.expr_inner(&e, depth + 1, seen, subst)),
            ast::Expr::RefExpr(e) => e
                .expr()
                .map_or(Prov::unknown(), |e| self.expr_inner(&e, depth + 1, seen, subst)),
            ast::Expr::CastExpr(e) => e
                .expr()
                .map_or(Prov::unknown(), |e| self.expr_inner(&e, depth + 1, seen, subst)),
            ast::Expr::TryExpr(e) => e
                .expr()
                .map_or(Prov::unknown(), |e| self.expr_inner(&e, depth + 1, seen, subst)),
            ast::Expr::AwaitExpr(e) => e
                .expr()
                .map_or(Prov::unknown(), |e| self.expr_inner(&e, depth + 1, seen, subst)),
            ast::Expr::BlockExpr(e) => e.tail_expr().map_or(Prov::unknown(), |e| {
                self.expr_inner(&e, depth + 1, seen, subst)
            }),
            ast::Expr::IfExpr(e) => {
                let then = e.then_branch().map_or(Prov::unknown(), |b| {
                    self.expr_inner(&b.into(), depth + 1, seen, subst)
                });
                match e.else_branch() {
                    Some(ast::ElseBranch::Block(b)) => Prov::join(
                        then,
                        self.expr_inner(&b.into(), depth + 1, seen, subst),
                    ),
                    Some(ast::ElseBranch::IfExpr(inner)) => Prov::join(
                        then,
                        self.expr_inner(&inner.into(), depth + 1, seen, subst),
                    ),
                    None => then,
                }
            }
            ast::Expr::BinExpr(e) => self.bin_expr(e, depth, seen, subst),
            ast::Expr::PathExpr(e) => self.path_expr(e, seen, subst),
            ast::Expr::CallExpr(e) => self.call_expr(e, depth, seen, subst),
            ast::Expr::MethodCallExpr(e) => self.method_call(e, depth, seen, subst),
            ast::Expr::MacroExpr(e) => e.macro_call().map_or(Prov::unknown(), |c| {
                self.macro_prov(&c, depth + 1, seen, subst)
            }),
            ast::Expr::ArrayExpr(e) => self.join_all(
                e.exprs().map(Some),
                depth,
                seen,
                subst,
            ),
            ast::Expr::TupleExpr(e) => self.join_all(
                e.fields().map(Some),
                depth,
                seen,
                subst,
            ),
            ast::Expr::RecordExpr(e) => self.join_all(
                e.record_expr_field_list()
                    .into_iter()
                    .flat_map(|l| l.fields())
                    .map(|f| f.expr()),
                depth,
                seen,
                subst,
            ),
            ast::Expr::FieldExpr(e) => self.field_expr(e, depth, seen, subst),
            ast::Expr::IndexExpr(e) => e.base().map_or(Prov::unknown(), |b| {
                self.element_like(&b, depth + 1, seen, subst)
            }),
            // Macros we cannot expand, and struct-literal-adjacent forms we do
            // not model, stay unknown rather than guessing.
            _ => Prov::unknown(),
        }
    }

    fn join_all(
        &self,
        exprs: impl Iterator<Item = Option<ast::Expr>>,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        let mut prov: Option<Prov> = None;
        for expr in exprs.flatten() {
            let item = self.expr_inner(&expr, depth + 1, seen, subst);
            prov = Some(match prov {
                Some(prev) => Prov::join(prev, item),
                None => item,
            });
        }
        prov.unwrap_or_else(Prov::unknown)
    }

    fn bin_expr(
        &self,
        e: &ast::BinExpr,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
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
        let a = self.expr_inner(&lhs, depth + 1, seen, subst);
        let b = self.expr_inner(&rhs, depth + 1, seen, subst);
        Prov::join(a, b)
    }

    fn path_expr(
        &self,
        e: &ast::PathExpr,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        let Some(path) = e.path() else {
            return Prov::unknown();
        };
        match self.sema.resolve_path(&path) {
            Some(PathResolution::Local(local)) => {
                if !seen.insert(local) {
                    return Prov::new(Kind::Param);
                }
                self.local_prov(local, seen, subst)
            }
            Some(PathResolution::Def(hir::ModuleDef::Const(_))) => Prov::new(Kind::Literal),
            _ => Prov::unknown(),
        }
    }

    /// A binding's provenance, in priority order: a substituted value (closure
    /// parameter), a `let` initializer, an `if let`/`match` scrutinee, a `for`
    /// iterable, a function parameter, or nothing.
    fn local_prov(
        &self,
        local: Local<'a>,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        let source = local.primary_source(self.db);
        let node = source.source.value.syntax().clone();
        if let Some(prov) = subst.get((source.source.file_id, node.text_range())) {
            return prov;
        }
        let Some(ident_pat) = ast::IdentPat::cast(node.clone()) else {
            return Prov::new(Kind::Param); // `self`
        };
        if ident_pat.syntax().ancestors().any(|a| ast::Param::cast(a).is_some()) {
            return Prov::new(Kind::Param);
        }
        if let Some(init) = ident_pat
            .syntax()
            .ancestors()
            .find_map(ast::LetStmt::cast)
            .and_then(|l| l.initializer())
        {
            return self.expr_inner(&init, 1, seen, subst);
        }
        if let Some(let_expr) = ident_pat.syntax().ancestors().find_map(ast::LetExpr::cast) {
            return let_expr
                .expr()
                .map_or(Prov::unknown(), |e| self.expr_inner(&e, 1, seen, subst));
        }
        if ident_pat.syntax().ancestors().any(|a| ast::MatchArm::can_cast(a.kind())) {
            if let Some(match_expr) = ident_pat.syntax().ancestors().find_map(ast::MatchExpr::cast)
            {
                return match_expr
                    .expr()
                    .map_or(Prov::unknown(), |e| self.expr_inner(&e, 1, seen, subst));
            }
        }
        if let Some(for_expr) = ident_pat.syntax().ancestors().find_map(ast::ForExpr::cast) {
            return for_expr
                .iterable()
                .map_or(Prov::unknown(), |e| self.expr_inner(&e, 1, seen, subst));
        }
        Prov::unknown()
    }

    /// A struct field: use the crate-wide field summary when there is one,
    /// otherwise a field of a caller-controlled value is caller-controlled.
    fn field_expr(
        &self,
        e: &ast::FieldExpr,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        let Some(base) = e.expr() else {
            return Prov::unknown();
        };
        let base_prov = self.expr_inner(&base, depth + 1, seen, subst);
        if std::env::var_os("SAFEIFY_DEBUG").is_some() {
            eprintln!(
                "  FIELD-READ {:?} base={:?} adt={:?}",
                e.name_ref().map(|n| n.text().to_string()),
                base.syntax().text().to_string().chars().take(20).collect::<String>(),
                fields::adt_name(self.sema, self.db, &base)
            );
        }
        if let (Some(name), Some(index)) = (e.name_ref(), self.fields) {
            if let Some(adt) = fields::adt_name(self.sema, self.db, &base) {
                if let Some(summary) = fields::summary(
                    index,
                    &base_prov,
                    (adt.as_str(), name.text().to_string().as_str()),
                ) {
                    return summary;
                }
            }
        }
        self.inherit_from_base(&base_prov)
    }

    fn element_like(
        &self,
        base: &ast::Expr,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        let base_prov = self.expr_inner(base, depth + 1, seen, subst);
        self.inherit_from_base(&base_prov)
    }

    fn inherit_from_base(&self, base: &Prov) -> Prov {
        match base.kind {
            Kind::Param => Prov::new(Kind::Param),
            Kind::Tainted => Prov::with_detail(Kind::Tainted, base.detail.clone()),
            _ => Prov::unknown(),
        }
    }

    fn call_expr(
        &self,
        call: &ast::CallExpr,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        let Some(callee) = call.expr() else {
            return Prov::unknown();
        };
        let Some(callable) = self.sema.resolve_expr_as_callable(&callee) else {
            return self.unresolved_callee(&callee, call, depth, seen, subst);
        };
        match callable.kind() {
            CallableKind::Function(function) => {
                let path = paths::qualified_path(self.db, function);
                self.fn_call_prov(&path, call, depth, seen, subst)
            }
            // `Some(x)`, `Ok(x)`, tuple-struct wrappers: the value is the
            // first argument.
            CallableKind::TupleStruct(_) | CallableKind::TupleEnumVariant(_) => {
                first_arg_prov(self, call, depth, seen, subst)
            }
            _ => Prov::unknown(),
        }
    }

    /// Call resolution needs the argument types to be inferred; for paths this
    /// can fail where name resolution still succeeds (`PathBuf::from` through a
    /// blanket `From` impl). Fall back to the resolved path when possible.
    fn unresolved_callee(
        &self,
        callee: &ast::Expr,
        call: &ast::CallExpr,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        let ast::Expr::PathExpr(path_expr) = callee else {
            return Prov::unknown();
        };
        let Some(path) = path_expr.path() else {
            return Prov::unknown();
        };
        let Some(resolution) = self.sema.resolve_path(&path) else {
            // Prelude variant constructors (`Some`, `Ok`, ...) and associated
            // functions reached through blanket impls (`PathBuf::from`) do not
            // always resolve as paths; treat the known constructor shapes as
            // value-preserving wrappers.
            let last = last_segment(&path);
            if let Some(name) = &last {
                if matches!(name.as_str(), "Some" | "Ok" | "Err") {
                    return first_arg_prov(self, call, depth, seen, subst);
                }
                if sink::is_constructor_name(name) && path.qualifier().is_some() {
                    return first_arg_prov(self, call, depth, seen, subst);
                }
            }
            return Prov::unknown();
        };
        match resolution {
            PathResolution::Def(hir::ModuleDef::Function(function)) => {
                let path = paths::qualified_path(self.db, function);
                if std::env::var_os("SAFEIFY_DEBUG").is_some() {
                    eprintln!("  CALLPATH-FALLBACK {path}");
                }
                self.fn_call_prov(&path, call, depth, seen, subst)
            }
            PathResolution::Def(hir::ModuleDef::EnumVariant(_))
            | PathResolution::Def(hir::ModuleDef::Adt(hir::Adt::Struct(_))) => {
                first_arg_prov(self, call, depth, seen, subst)
            }
            _ => Prov::unknown(),
        }
    }

    fn fn_call_prov(
        &self,
        path: &str,
        call: &ast::CallExpr,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
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
        if sink::is_constructor(path) || sink::is_formatting_producer(path) {
            return self.join_all(
                call.arg_list().map(|a| a.args().map(Some)).into_iter().flatten(),
                depth,
                seen,
                subst,
            );
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
        subst: &mut Subst,
    ) -> Prov {
        let receiver = call
            .receiver()
            .map_or(Prov::unknown(), |r| self.expr_inner(&r, depth + 1, seen, subst));
        let args: Vec<ast::Expr> = call
            .arg_list()
            .map(|a| a.args().collect())
            .unwrap_or_default();
        let name = call
            .name_ref()
            .map(|n| n.text().to_string())
            .unwrap_or_default();

        let resolved = self.sema.resolve_method_call(call);
        if std::env::var_os("SAFEIFY_DEBUG").is_some() {
            eprintln!(
                "  M {:?} recv={:?} resolved={}",
                call.name_ref().map(|n| n.text().to_string()),
                receiver.kind,
                resolved
                    .map(|f| crate::paths::qualified_path(self.db, f))
                    .unwrap_or_default()
            );
        }
        let Some(function) = self.sema.resolve_method_call(call) else {
            // Method resolution can fail on receivers whose type lives in an
            // unresolved dependency (e.g. a lock guard around `&Path`). For
            // path-composition methods the value still derives from the
            // receiver and arguments, so keep that provenance instead of
            // dropping the taint.
            if sink::is_composition(&name) {
                let mut prov = receiver;
                for arg in &args {
                    let arg_prov = self.expr_inner(arg, depth + 1, seen, subst);
                    prov = sink::join_prov(&prov, &arg_prov);
                }
                return prov;
            }
            return receiver;
        };
        let path = paths::qualified_path(self.db, function);
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
        if sink::is_closure_adapter(name) {
            return self.closure_adapter(name, &receiver, &args, depth, seen, subst);
        }
        if name == "join" {
            let arg = args
                .first()
                .map_or(Prov::unknown(), |a| self.expr_inner(a, depth + 1, seen, subst));
            return sink::join_prov(&receiver, &arg);
        }
        Prov::unknown()
    }

    /// `Option`/`Result` combinators: the result derives from the receiver
    /// through the closure, so evaluate the closure with its parameter bound to
    /// the receiver's provenance.
    fn closure_adapter(
        &self,
        name: &str,
        receiver: &Prov,
        args: &[ast::Expr],
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        // Predicates do not change the value.
        if matches!(name, "filter" | "filter_map" | "inspect" | "inspect_err") {
            return receiver.clone();
        }
        for arg in args {
            if let ast::Expr::ClosureExpr(closure) = arg {
                let bound = if matches!(name, "or_else" | "unwrap_or_else" | "ok_or_else") {
                    Prov::unknown()
                } else {
                    receiver.clone()
                };
                return self.closure_prov(closure, &bound, depth, seen, subst);
            }
        }
        // No closure argument (`or`, `unwrap_or`, `ok_or`): the value is either
        // the receiver or the plain argument.
        let fallback = args
            .first()
            .map_or(Prov::unknown(), |a| self.expr_inner(a, depth + 1, seen, subst));
        if receiver.kind == Kind::Unknown {
            fallback
        } else {
            receiver.clone()
        }
    }

    fn closure_prov(
        &self,
        closure: &ast::ClosureExpr,
        bound: &Prov,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        let mark = subst.entries.len();
        let mut pushed = 0usize;
        if let Some(params) = closure.param_list() {
            for (index, param) in params.params().enumerate() {
                let Some(pat) = param.pat() else { continue };
                let key = (
                    self.sema.hir_file_for(pat.syntax()),
                    pat.syntax().text_range(),
                );
                let value = if index == 0 { bound.clone() } else { Prov::unknown() };
                subst.push(key, value);
                pushed += 1;
            }
        }
        let prov = closure
            .body()
            .map_or(Prov::unknown(), |body| self.expr_inner(&body, depth + 1, seen, subst));
        let _ = pushed;
        subst.truncate(mark);
        prov
    }

    /// Macro expressions: let rust-analyzer expand the call and evaluate the
    /// expansion. Expression-macro expansion is not always available in
    /// `no_deps` mode; when it is not, the value is unknown rather than guessed.
    fn macro_prov(
        &self,
        call: &ast::MacroCall,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        if depth > MAX_DEPTH {
            return Prov::unknown();
        }
        let Some(expanded) = self.sema.expand_macro_call(call) else {
            return Prov::unknown();
        };
        let node = expanded.value;
        let Some(expr) = ast::Expr::cast(node.clone())
            .or_else(|| node.descendants().find_map(ast::Expr::cast))
        else {
            return Prov::unknown();
        };
        self.expr_inner(&expr, depth + 1, seen, subst)
    }
}

fn last_segment(path: &ast::Path) -> Option<String> {
    path.segment()
        .and_then(|s| s.name_ref())
        .map(|n| n.text().to_string())
}

fn first_arg_prov<'a>(
    eval: &Eval<'a>,
    call: &ast::CallExpr,
    depth: usize,
    seen: &mut HashSet<Local<'a>>,
    subst: &mut Subst,
) -> Prov {
    let Some(first) = call.arg_list().and_then(|a| a.args().next()) else {
        return Prov::unknown();
    };
    eval.expr_inner(&first, depth + 1, seen, subst)
}

fn first_arg_string(call: &ast::CallExpr) -> Option<String> {
    let first = call.arg_list()?.args().next()?;
    match &first {
        ast::Expr::Literal(lit) => sink::literal_string(lit),
        _ => None,
    }
}

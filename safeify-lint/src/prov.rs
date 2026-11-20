//! Provenance over resolved expressions.
//!
//! The lattice is `literal < param < tainted < trusted < unknown`; joining
//! uses the conservative maximum and `unknown` never fires. Every step is a
//! resolution result: locals are `hir::Local` values, callees are resolved
//! functions, and methods use their resolved trait or inherent dispatch.
//!
//! Three mechanisms make this deeper than name-based text matching:
//! * pattern bindings (`if let`, `match`, `for`) inherit the scrutinee's
//!   provenance, and
//! * closure arguments are evaluated with their parameter bound to the
//!   receiver's provenance, so `.map(|s| PathBuf::from(s).join(..))` keeps the
//!   trust of what it started from.
//! * a call into a crate-local function is evaluated at the call site: the
//!   caller's argument provenance is bound to the callee's parameters and the
//!   callee's return expressions are evaluated with that binding. That is a
//!   context-sensitive interprocedural summary — `fs::write(dest(root, name))`
//!   sees what `dest` does with `root` and `name` without any fixed-point
//!   summary table.

use std::cell::Cell;
use std::collections::HashSet;

use hir::{CallableKind, Function, Local, PathResolution, Semantics};
use ide_db::RootDatabase;
use hir::HirFileId;
use syntax::ast::{self, AstNode, AstToken, HasArgList};
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

const MAX_DEPTH: usize = 24;
/// How many crate-local calls deep the evaluator follows before it gives up
/// with `unknown`. Recursive helpers hit this cap instead of diverging.
const MAX_CALL_DEPTH: usize = 8;

/// How a sink argument was classified, for the coverage metric in
/// `notes/research/engine.md` §7 ("how many sink calls are still `unknown`").
#[derive(Default)]
pub struct ProvCounts {
    literal: Cell<u64>,
    param: Cell<u64>,
    tainted: Cell<u64>,
    trusted: Cell<u64>,
    unknown: Cell<u64>,
}

impl ProvCounts {
    pub fn add(&self, kind: Kind) {
        let cell = match kind {
            Kind::Literal => &self.literal,
            Kind::Param => &self.param,
            Kind::Tainted => &self.tainted,
            Kind::Trusted => &self.trusted,
            Kind::Unknown => &self.unknown,
        };
        cell.set(cell.get() + 1);
    }

    fn total(&self) -> u64 {
        self.literal.get() + self.param.get() + self.tainted.get() + self.trusted.get() + self.unknown.get()
    }

    fn snapshot(&self) -> CountsSnapshot {
        CountsSnapshot {
            literal: self.literal.get(),
            param: self.param.get(),
            tainted: self.tainted.get(),
            trusted: self.trusted.get(),
            unknown: self.unknown.get(),
            total: self.total(),
        }
    }
}

#[derive(serde::Serialize)]
pub struct CountsSnapshot {
    pub literal: u64,
    pub param: u64,
    pub tainted: u64,
    pub trusted: u64,
    pub unknown: u64,
    pub total: u64,
}

/// Counters, written by `--stats`. Interior mutability because evaluation is
/// `&self`: the counters are observation, not analysis state.
#[derive(Default)]
pub struct Stats {
    /// One count per filesystem sink call, classified by its path argument.
    pub fs_calls: ProvCounts,
    pub exec_program_calls: ProvCounts,
    pub exec_arg_calls: ProvCounts,
    /// Crate-local calls whose body was interpreted.
    pub local_calls: Cell<u64>,
    /// Calls not interpreted because the function was already being evaluated.
    pub recursion_cuts: Cell<u64>,
    /// Calls not interpreted because the call-depth cap was reached.
    pub depth_cuts: Cell<u64>,
}

#[derive(serde::Serialize)]
pub struct StatsSnapshot {
    pub fs_calls: CountsSnapshot,
    pub exec_program_calls: CountsSnapshot,
    pub exec_arg_calls: CountsSnapshot,
    pub local_calls: u64,
    pub recursion_cuts: u64,
    pub depth_cuts: u64,
}

impl Stats {
    pub fn snapshot(&self) -> StatsSnapshot {
        StatsSnapshot {
            fs_calls: self.fs_calls.snapshot(),
            exec_program_calls: self.exec_program_calls.snapshot(),
            exec_arg_calls: self.exec_arg_calls.snapshot(),
            local_calls: self.local_calls.get(),
            recursion_cuts: self.recursion_cuts.get(),
            depth_cuts: self.depth_cuts.get(),
        }
    }
}

fn bump(cell: &Cell<u64>) {
    cell.set(cell.get() + 1);
}

/// Bindings whose value is being substituted (closure parameters, and the
/// parameters of a crate-local function being interpreted at its call site).
#[derive(Default)]
struct Subst {
    entries: Vec<((HirFileId, TextRange), Prov)>,
    /// Crate-local functions currently being interpreted. A function already on
    /// the stack is not expanded again: recursion becomes `unknown`, which the
    /// lattice turns into silence rather than an invented verdict.
    stack: Vec<Function>,
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
    /// Follow calls into crate-local function bodies. Off while building the
    /// field index: that pass asks only "what is assigned here", and expanding
    /// every call of every record literal buys nothing there.
    pub interproc: bool,
    pub stats: Stats,
}

impl<'a> Eval<'a> {
    pub fn new(
        sema: &'a Semantics<'a, RootDatabase>,
        db: &'a RootDatabase,
        fields: Option<&'a FieldIndex>,
        interproc: bool,
    ) -> Self {
        Self { sema, db, fields, interproc, stats: Stats::default() }
    }
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
            // `format_args!` lowers to a dedicated node whose arguments are
            // real expressions and whose template captures resolve, so both
            // `format!("{}/{}", root, name)` and `format!("{name}")` yield the
            // pieces the result is built from.
            ast::Expr::FormatArgsExpr(e) => self.format_args_prov(e, depth + 1, seen, subst),
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
                if self.interproc && self.is_local(function) {
                    let args: Vec<Prov> = call
                        .arg_list()
                        .map(|list| list.args().collect::<Vec<_>>())
                        .unwrap_or_default()
                        .iter()
                        .map(|arg| self.expr_inner(arg, depth + 1, seen, subst))
                        .collect();
                    return self.local_call(function, &args, depth, seen, subst);
                }
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
                if self.interproc && self.is_local(function) {
                    let args: Vec<Prov> = call
                        .arg_list()
                        .map(|list| list.args().collect::<Vec<_>>())
                        .unwrap_or_default()
                        .iter()
                        .map(|arg| self.expr_inner(arg, depth + 1, seen, subst))
                        .collect();
                    return self.local_call(function, &args, depth, seen, subst);
                }
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

    /// A definition that belongs to the analyzed package rather than to std or
    /// a dependency. Dependency sources are not loaded (`no_deps`), so only
    /// these can be interpreted.
    fn is_local(&self, function: Function) -> bool {
        function.module(self.db).krate(self.db).origin(self.db).is_local()
    }

    /// Evaluate a call into a crate-local function: bind the evaluated
    /// arguments to the callee's parameters and evaluate what it returns.
    ///
    /// `args[0]` is the receiver for a method (the parameter list of a method
    /// starts with `self`), matching `Function::assoc_fn_params`.
    fn local_call(
        &self,
        function: Function,
        args: &[Prov],
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        if subst.stack.contains(&function) {
            bump(&self.stats.recursion_cuts);
            return Prov::unknown();
        }
        if subst.stack.len() >= MAX_CALL_DEPTH {
            bump(&self.stats.depth_cuts);
            return Prov::unknown();
        }
        let Some(fn_ast) = self.sema.source(function) else {
            return Prov::unknown();
        };
        let Some(body) = fn_ast.value.body() else {
            return Prov::unknown();
        };
        bump(&self.stats.local_calls);

        let mark = subst.entries.len();
        for param in function.assoc_fn_params(self.db) {
            let Some(local) = param.as_local(self.db) else {
                continue;
            };
            let source = local.primary_source(self.db);
            let key = (
                source.source.file_id,
                source.source.value.syntax().text_range(),
            );
            let prov = args.get(param.index()).cloned().unwrap_or_else(Prov::unknown);
            subst.push(key, prov);
        }
        subst.stack.push(function);
        let prov = self.body_prov(&body, depth + 1, seen, subst);
        subst.stack.pop();
        subst.truncate(mark);
        prov
    }

    /// The value a function body produces: its tail expression joined with
    /// every `return` expression that belongs to it (a `return` inside a
    /// nested closure or `fn` belongs to that closure).
    fn body_prov(
        &self,
        body: &ast::BlockExpr,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        if depth > MAX_DEPTH {
            return Prov::unknown();
        }
        let mut prov: Option<Prov> = None;
        let mut add = |next: Prov| {
            prov = Some(match prov.take() {
                Some(prev) => Prov::join(prev, next),
                None => next,
            });
        };
        if let Some(tail) = body.tail_expr() {
            add(self.expr_inner(&tail, depth + 1, seen, subst));
        }
        for ret in body.syntax().descendants().filter_map(ast::ReturnExpr::cast) {
            if !return_belongs_to(&ret, body) {
                continue;
            }
            if let Some(value) = ret.expr() {
                add(self.expr_inner(&value, depth + 1, seen, subst));
            }
        }
        prov.unwrap_or_else(Prov::unknown)
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
        // Value-preserving adapters (`clone`, `into`, `to_string`, `unwrap`,
        // `as_ref`, ...) come before interpretation: a derived `Clone` has no
        // body of its own (its source is the core trait method), and a local
        // `Display`/`From` impl would otherwise be cut to `unknown` where the
        // receiver's provenance is the useful answer.
        if sink::is_truthy_adapter(&name) {
            return receiver;
        }
        if self.interproc && self.is_local(function) {
            // A method of this crate: interpret its body with the receiver
            // bound to `self`. Deeper than the name tables, and correct for a
            // local helper that happens to share a name with a `Path` method.
            let mut provs = vec![receiver];
            for arg in &args {
                provs.push(self.expr_inner(arg, depth + 1, seen, subst));
            }
            return self.local_call(function, &provs, depth, seen, subst);
        }
        let path = paths::qualified_path(self.db, function);
        let name = path.rsplit("::").next().unwrap_or(&path);

        // The trusted/taint tables are keyed by qualified path (`path::Path::
        // file_name`, `net::TcpStream::connect`), so a method must be looked up
        // by the path it resolved to, not by its bare name.
        if sink::is_trusted_producer(&path) {
            return Prov::with_detail(Kind::Trusted, name.to_string());
        }
        if let Some(detail) = sink::taint_source(&path) {
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

    /// A formatted string: the join of its explicit arguments and of the
    /// implicit captures in its template (`{name}`), both resolved by
    /// rust-analyzer. The result is a new string, so it carries no literal
    /// value even when every piece is literal.
    fn format_args_prov(
        &self,
        e: &ast::FormatArgsExpr,
        depth: usize,
        seen: &mut HashSet<Local<'a>>,
        subst: &mut Subst,
    ) -> Prov {
        let mut prov: Option<Prov> = None;
        let mut add = |next: Prov| {
            prov = Some(match prov.take() {
                Some(prev) => Prov::join(prev, next),
                None => next,
            });
        };
        for arg in e.args() {
            if let Some(expr) = arg.expr() {
                add(self.expr_inner(&expr, depth + 1, seen, subst));
            }
        }
        if let Some(template) = e.template() {
            if let Some(string) = template_string(&template) {
                if let Some(parts) = self.sema.as_format_args_parts(&string) {
                    for (_range, resolution) in parts {
                        let Some(either::Either::Left(PathResolution::Local(local))) = resolution
                        else {
                            continue;
                        };
                        add(self.local_prov(local, seen, subst));
                    }
                }
            }
        }
        let mut prov = prov.unwrap_or_else(|| Prov::new(Kind::Literal));
        prov.value = None;
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

/// The string token of a `format_args!` template, when the template is a
/// string literal (the only form that can carry implicit captures).
fn template_string(template: &ast::Expr) -> Option<ast::String> {
    template
        .syntax()
        .descendants_with_tokens()
        .filter_map(|it| it.into_token())
        .find_map(ast::String::cast)
}

/// Does this `return` leave `body`, or a closure / nested `fn` inside it?
fn return_belongs_to(ret: &ast::ReturnExpr, body: &ast::BlockExpr) -> bool {
    for ancestor in ret.syntax().ancestors() {
        if ancestor == *body.syntax() {
            return true;
        }
        if ast::ClosureExpr::can_cast(ancestor.kind()) || ast::Fn::can_cast(ancestor.kind()) {
            return false;
        }
    }
    false
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

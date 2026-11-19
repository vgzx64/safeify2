//! Field provenance: what values get written into struct fields.
//!
//! A field inherited from a parameter is caller-controlled, but a field
//! initialised from `OUT_DIR` is not. Without this index the engine reports
//! `self.out_dir.join("install")` as tainted (openssl-src), which is the
//! false-positive class the summary exists to remove.
//!
//! Context-insensitive on purpose: all writes to `(struct, field)` in the crate
//! join into one summary. That matches the tool's "can this field ever carry a
//! caller value" question and keeps the analysis O(fields) rather than
//! O(fields x call sites).

use std::collections::HashMap;

use hir::Semantics;
use ide_db::RootDatabase;
use syntax::ast::{self, AstNode};

use crate::prov::{Eval, Kind, Prov};

#[derive(Default, Clone)]
pub struct FieldIndex {
    map: HashMap<(String, String), Prov>,
}

impl FieldIndex {
    pub fn get(&self, adt: &str, field: &str) -> Option<&Prov> {
        self.map.get(&(adt.to_string(), field.to_string()))
    }

    fn insert(&mut self, adt: String, field: String, prov: Prov) {
        match self.map.get_mut(&(adt.clone(), field.clone())) {
            // A field that is *ever* written from a caller-controlled value is
            // caller-controlled: taint must dominate trust here, unlike the
            // expression-level join where trusted wins to avoid false alarms.
            Some(existing) => *existing = taint_join(existing.clone(), prov),
            None => {
                self.map.insert((adt, field), prov);
            }
        }
    }

    pub fn len(&self) -> usize {
        self.map.len()
    }
}

/// Walk every parsed file and record the provenance of values assigned to
/// struct fields, both in record literals (`S { f: v }`) and assignments
/// (`self.f = v`).
pub fn build<'a>(
    sema: &'a Semantics<'a, RootDatabase>,
    db: &'a RootDatabase,
    files: impl Iterator<Item = &'a ast::SourceFile>,
) -> FieldIndex {
    let eval = Eval { sema, db, fields: None };
    let mut index = FieldIndex::default();

    for source_file in files {
        for node in source_file.syntax().descendants() {
            if let Some(record) = ast::RecordExpr::cast(node.clone()) {
                let Some(adt) = adt_name(sema, db, &ast::Expr::RecordExpr(record.clone()))
                else {
                    continue;
                };
                let Some(fields) = record.record_expr_field_list() else {
                    continue;
                };
                for field in fields.fields() {
                    let (Some(name), Some(value)) = (field.name_ref(), field.expr()) else {
                        continue;
                    };
                    index.insert(adt.clone(), name.text().to_string(), eval.expr(&value));
                }
                continue;
            }
            if let Some(assign) = ast::BinExpr::cast(node.clone()) {
                if !matches!(assign.op_kind(), Some(ast::BinaryOp::Assignment { op: None })) {
                    continue;
                }
                let (Some(lhs), Some(rhs)) = (assign.lhs(), assign.rhs()) else {
                    continue;
                };
                let ast::Expr::FieldExpr(field_expr) = lhs else {
                    continue;
                };
                let (Some(base), Some(name)) = (field_expr.expr(), field_expr.name_ref()) else {
                    continue;
                };
                let Some(adt) = adt_name(sema, db, &base) else {
                    continue;
                };
                index.insert(adt, name.text().to_string(), eval.expr(&rhs));
            }
        }
    }
    index
}

pub fn adt_name(
    sema: &Semantics<'_, RootDatabase>,
    db: &RootDatabase,
    expr: &ast::Expr,
) -> Option<String> {
    let info = sema.type_of_expr(expr)?;
    // `self` inside a method has type `&Build`; strip the reference before
    // asking for the ADT, and try the adjusted type as a fallback.
    let adt = info
        .original
        .strip_references()
        .as_adt()
        .or_else(|| {
            info.adjusted
                .as_ref()
                .and_then(|t| t.strip_references().as_adt())
        })?;
    Some(adt.name(db).as_str().to_string())
}

/// The most informative summary for a field, or `None` when the crate never
/// writes it (then the base value's provenance stands).
/// May-analysis join: a single tainted write makes every read tainted.
fn taint_join(a: Prov, b: Prov) -> Prov {
    let a_tainted = a.is_tainted();
    let b_tainted = b.is_tainted();
    match (a_tainted, b_tainted) {
        (true, false) => a,
        (false, true) => b,
        (true, true) => {
            if a.kind == Kind::Param && b.kind == Kind::Param {
                a
            } else if a.kind == Kind::Tainted {
                a
            } else {
                b
            }
        }
        (false, false) => {
            if a.kind == Kind::Trusted || b.kind == Kind::Trusted {
                Prov::with_detail(Kind::Trusted, String::new())
            } else if a.kind == Kind::Literal || b.kind == Kind::Literal {
                Prov::new(Kind::Literal)
            } else {
                Prov::unknown()
            }
        }
    }
}

pub fn summary(index: &FieldIndex, base: &Prov, adt_and_field: (&str, &str)) -> Option<Prov> {
    let field = index.get(adt_and_field.0, adt_and_field.1)?;
    match field.kind {
        // Any tainted write makes reads of the field tainted; a field that is
        // only ever written from literals or Cargo variables stays trusted.
        Kind::Tainted | Kind::Param => Some(Prov::with_detail(field.kind, field.detail.clone())),
        Kind::Trusted => Some(Prov::with_detail(Kind::Trusted, field.detail.clone())),
        Kind::Literal => Some(Prov::new(Kind::Literal)),
        Kind::Unknown => base.is_tainted().then(|| base.clone()),
    }
}

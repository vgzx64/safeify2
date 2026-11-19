//! Stable, human-readable names for resolved items.
//!
//! Rules key off these strings (`fs::write`, `process::Command::new`,
//! `io::Write::write_all`), so they must come from the resolved item, never
//! from source text. The crate name is omitted on purpose: `std`/`core`/`alloc`
//! both re-export the same items, and the module path is what the rules mean.

use hir::{AsAssocItem, AssocItemContainer, Function};
use ide_db::RootDatabase;

pub fn qualified_path(db: &RootDatabase, f: Function) -> String {
    let mut parts: Vec<String> = Vec::new();
    let mut modules = f.module(db).path_to_root(db);
    modules.reverse();
    for module in modules {
        if let Some(name) = module.name(db) {
            parts.push(name.as_str().to_string());
        }
    }
    if let Some(container) = container_name(db, f) {
        parts.push(container);
    }
    parts.push(f.name(db).as_str().to_string());
    parts.join("::")
}

fn container_name(db: &RootDatabase, f: Function) -> Option<String> {
    let item = f.as_assoc_item(db)?;
    match item.container(db) {
        AssocItemContainer::Trait(trait_) => Some(trait_.name(db).as_str().to_string()),
        AssocItemContainer::Impl(impl_) => {
            let ty = impl_.self_ty(db);
            let adt = ty.as_adt()?;
            Some(adt.name(db).as_str().to_string())
        }
    }
}

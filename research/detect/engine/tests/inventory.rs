//! Regression suite for `--inventory`, the semantic replacement of the masked
//! text scanner the frozen NIRM-3 evaluation used.
//!
//! The fixture is one detached file (the frozen split's convention), so this
//! runs the same loading mode as `detect/semantic_inventory.py`. Assertions are
//! on the designed behaviour the parity harness depends on: a raw-pointer deref
//! is kept, a reference deref is excluded, a guard found in a macro expansion
//! counts, and a call written in an unresolvable macro is still inventoried.

use std::path::PathBuf;
use std::process::Command;

fn inventory() -> (String, serde_json::Value) {
    let file = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("fixtures")
        .join("inventory_snippet.rs");
    let output = Command::new(env!("CARGO_BIN_EXE_safeify-lint"))
        .arg("--inventory")
        .arg(&file)
        .output()
        .expect("engine runs");
    assert!(
        output.status.success(),
        "engine failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    (
        std::fs::read_to_string(&file).unwrap(),
        serde_json::from_slice(&output.stdout).expect("inventory is JSON"),
    )
}

fn strings(values: impl Iterator<Item = serde_json::Value>) -> Vec<String> {
    values.map(|v| v.as_str().unwrap().to_string()).collect()
}

#[test]
fn unsafe_regions_calls_derefs_and_guards() {
    let (_source, inv) = inventory();
    let regions = inv["regions"].as_array().expect("regions");
    let kinds: Vec<String> = regions
        .iter()
        .map(|r| {
            let name = if r["name"].is_null() {
                String::new()
            } else {
                format!("/{}", r["name"].as_str().unwrap())
            };
            format!("{}{name}", r["kind"].as_str().unwrap())
        })
        .collect();
    // `unsafe fn load` and the nested `unsafe { *ptr }` block.
    assert_eq!(kinds, ["fn/load", "block"]);

    let function = &regions[0];
    let calls: Vec<String> = function["calls"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| c["callee"].as_str().unwrap().to_string())
        .collect();
    // `is_null` and `ptr::read` are not in the source tree as expressions:
    // the first lives in `assert!`'s expansion, the second in `warn!`'s token
    // list. Both have to be found anyway.
    assert_eq!(calls, ["is_null", "core::ptr::write", "ptr::read"]);

    let resolved: Vec<bool> = function["calls"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| !c["resolved"].is_null())
        .collect();
    // `ptr::read` has no `use` statement to resolve through.
    assert_eq!(resolved, [true, true, false]);

    let functions = inv["functions"].as_array().expect("functions");
    assert_eq!(functions.len(), 1);
    assert_eq!(functions[0]["name"], "load");
    let guards = strings(functions[0]["guards"].as_array().unwrap().iter().cloned());
    assert_eq!(guards, ["assert", "null_check"]);

    let derefs: Vec<(String, serde_json::Value)> = function["derefs"]
        .as_array()
        .unwrap()
        .iter()
        .map(|d| {
            (
                d["snippet"].as_str().unwrap().to_string(),
                d["raw_ptr"].clone(),
            )
        })
        .collect();
    // `*ptr` is a raw pointer; `*r` is a reference and must not become a
    // `ptr::deref` candidate (the text scanner could not tell them apart).
    assert_eq!(
        derefs,
        [
            ("*ptr".to_string(), serde_json::json!(true)),
            ("*r".to_string(), serde_json::json!(false))
        ]
    );

    let block = &regions[1];
    let block_derefs = strings(
        block["derefs"]
            .as_array()
            .unwrap()
            .iter()
            .map(|d| d["snippet"].clone()),
    );
    assert_eq!(block_derefs, ["*ptr"]);
    assert!(block["calls"].as_array().unwrap().is_empty());
}

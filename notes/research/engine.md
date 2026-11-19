# Semantic engine — replacing the regex front end

> **Status: milestone 2 (rules ported, differential harness running) ·
> 2026-11-19**
>
> Code: [`research/detect/engine/`](../../research/detect/engine/).
> Supersedes the text layer of
> [`lint_safe.py`](../../research/detect/lint_safe.py) and
> [`provenance.py`](../../research/detect/provenance.py); those stay as the
> parity oracle until every rule's site set matches.
>
> Naming: the project is **Safeify**. The engine binary is `safeify-lint` and
> the lint namespace is `safeify::<rule>` (`#[allow(safeify::fs_special_path)]`,
> `[lints.safeify]`). "NIRM 3" survives only in historical note paths and
> frozen evaluation artifacts, which are cited by filename and are not
> rewritten.

## 1. Why the regex front end has to go

The counterexample lints were built on masked source text plus regular
expressions. That was a scaffold to get 39 fixtures and a corpus census
quickly, and it worked for the easy half of the problem: literal paths,
literal program names, `env::set_var("PATH", …)`. Three measurements show
where it stops:

| Evidence | What it is really saying |
|---|---|
| 445 of 915 filesystem sink calls classify `unknown` (49%) | The lattice cannot see through a function return, a struct field, or a helper call, because text has no resolution. These calls can never fire, at any severity. |
| `exec_written_path` only catches same-function droppers | The rule needs a definition-use pair; the text engine can only find one by scanning the same body. |
| The audit's single FP (`grep-cli` 0.1.6) is a cross-function resolution failure | A helper (`resolve_binary()`) guarantees the path is absolute; text cannot know the helper's return value, so the call site looks tainted. |

These are not bugs to patch. They are the boundary of what source text can
express. Worse, the regex layer is where a silent regression is most likely:
a change in formatting, a new macro, or a `use` alias changes the answer
without changing the program's semantics, and no test would notice unless it
happened to cover that spelling.

The rest of NIRM 3 already commits to the opposite premise: verdicts are
computed over `unsafe` regions with `rust-analyzer` hover evidence, and the
frozen evaluation exists to show that evidence changes the outcome. Two front
ends with opposite epistemics is a defect in the project, not a division of
labour.

## 2. What the engine is

A Rust binary, `safeify-lint`, that links rust-analyzer **as a library**
(`ra_ap_ide` 0.0.358, the 2026-08-24 release line that also produced the
detector's pinned `rust-analyzer 0.3.3025-standalone`). It is not an LSP
client: no JSON-RPC, no hover round-trips, no text parsing. The pipeline is:

```
cargo metadata --no-deps        one shot per crate, ~50 ms, writes no Cargo.lock
  → ProjectWorkspace (crate graph: local package + sysroot)
  → RootDatabase (incremental, salsa)
  → Semantics                     name resolution + type inference, the same
                                  code paths the `rust-analyzer` binary uses
  → rules                         AST visitor over *resolved* nodes
  → findings.json                 same schema as lint_safe.py --json
```

Why the library and not the LSP server: interprocedural analysis needs the
whole crate in one place — every function body, every resolved call edge, the
type of every expression, all at once. Over LSP that is thousands of
positional round-trips per crate, and the answers still arrive as text. The
library exposes the resolved tree directly.

Why not reimplement anything: name resolution (aliases, `use` trees, trait
method dispatch, inherent vs. trait impls, generics) is exactly the work that
rust-analyzer already does, and exactly the work that regex gets wrong.

## 3. Rules over resolved nodes, not text

Each rule is a visitor over `ast` nodes, with every decision made on a
resolution result:

| Question the rule asks | Old answer | New answer |
|---|---|---|
| Is this call `std::fs::write`? | regex on the callee text | `sema.resolve_expr_as_callable(&callee)` → `Function`, then its module path |
| Is this argument a literal? | masked source text | `ast::Literal` node, no resolution needed |
| Is this argument a parameter? | regex over the enclosing `fn` signature | `sema.resolve_path(&path)` → `PathResolution::Local`, then the local's `Pat` owner |
| Is this argument tainted? | name in a hand-written source list | same list, but *reached through* resolved locals, fields and call summaries |
| Is there a guard before the call? | regex over the statement window, matched by callee name | resolved calls on the dominated path: `canonicalize`, `starts_with`, `components`, `ParentDir`, `file_name`, `matches!` |
| Is this `build.rs`? | file name | package target kind from the crate graph |
| Is the enclosing `fn` public? | regex | `ast::Fn` visibility + `sema.to_fn_def` |

The lattice is unchanged — `literal < param < tainted < trusted < unknown`,
`unknown` never fires, `trusted` covers Cargo-provided variables — because the
25-site audit in [counterexamples.md](counterexamples.md) was labelled against
it, and the labels must stay comparable. What changes is how a value's
position in the lattice is *computed*.

## 4. Interprocedural analysis (the point of the exercise)

"Reasonably deep" is defined as: no whole-program points-to, no alias
analysis, no heap model — but every function in the crate is analyzed, and
values are tracked *through* calls, returns and struct fields.

Three summaries per function, computed bottom-up over the call graph:

1. **sink summary** — for each parameter index `i`, does a sink receive `i`
   (directly or through locals/fields/other calls)? Used to propagate at call
   sites and to answer "is this helper dangerous at all".
2. **return summary** — for each parameter index `i` and for the function's
   own taint sources (env reads, file reads, stdin, network), what does the
   function *return*? This is what fixes the `resolve_binary()` FP class:
   a helper that returns a canonicalized/absolute path marks its result as
   `trusted`, not `tainted`.
3. **field summary** — for each struct field written from a parameter, the
   provenance written. Read sites of that field inherit it. This is the
   cross-method dropper: `self.path = download(url)` in one method,
   `Command::new(self.path)` in another.

The call graph is built in the same pass: when a call resolves to a
`hir::Function`, the engine records the edge and the provenance of each
argument at that site. Cycles (recursion, mutual recursion) are condensed
with Tarjan's algorithm and iterated to a fixed point; summaries are
context-insensitive, so all call sites of a function share one summary. That
is a deliberate cost: context sensitivity multiplies summaries by call sites
and buys little for path-shaped taint, where the interesting distinction is
"came from outside" vs. "came from a literal", not which caller.

What this does **not** do, and the report must say so: no sanitizer-aware
dataflow across branches (a guard only protects the dominated suffix), no
interior mutability or aliasing, no cross-crate summaries in the default
`no_deps` mode (external sinks beyond `std` stay `unknown`), and no macro
expansion for proc macros.

## 5. Migration, with the audit as the gate

The 25-site census, the 24/25 precision, and the per-rule strict counts in
[counterexamples.md](counterexamples.md) are the paper's evidence. Rewriting
the engine must not quietly change them. So the rule IDs stay identical, the
JSON schema stays identical, and every rule is ported behind a differential
check:

```
python3 detect/compare_engines.py <crate-dir>...
  for each rule: site set (rule, file, line) old vs new
  → identical      : rule is ported, text implementation deleted
  → additions      : inspect; either a bug in the new engine or a real
                     capability gain (then re-audit the new sites)
  → removals       : inspect; either a bug or the text engine's false
                     positive finally exposed (then re-audit)
```

Nothing is deleted until its rule reaches an explained diff. The Python
orchestration stays: corpus walking, the frozen NIRM 3 split, report
generation and the audit sheet builder are I/O and bookkeeping, not analysis,
and the 0.2000 accuracy on the 97-file split must keep reproducing from
untouched code.

## 6. Reproducibility

- Built from the vendored source at
  [`vendors/rust-analyzer`](../../vendors/rust-analyzer) (git `aa198229`,
  2026-11-19) via path dependencies, so the analysis engine is pinned to code
  checked into this repository. Release build: 9m21s cold, 0.8s incremental.
  A compatible prebuilt server is also installed at `/usr/bin/rust-analyzer`.
- Loading uses `CargoConfig { no_deps: true }`: `cargo metadata --no-deps`
  resolves in ~50 ms per crate, needs no network, and does not write a
  `Cargo.lock` into the vendored corpus.
- Standard library comes from the same `rust-src` shim sysroot the LSP path
  already uses ([`ra_client.py`](../../research/detect/ra_client.py),
  `~/.local/share/ra-detect/sysroot`), so `std::fs`/`std::process` paths
  resolve identically in both paths.
- Build wrapper [`cargo.sh`](../../research/detect/engine/cargo.sh) points
  `CARGO_HOME` at `.tools/cargo-home` (the global one is read-only here) and
  the target dir at `.tools/cargo-target`, outside the repository tree.

## 7. Measurements the engine must produce

Recorded here as they land, so the claim "semantic > text" is a number and
not an assertion:

| Metric | Text engine | Semantic engine |
|---|---|---|
| filesystem sink calls classified (not `unknown`) | 470/915 (51%) | — |
| same-function-only limitations hit by the corpus | dropper class unmeasurable | — |
| audit precision on the 25-site census | 24/25 = 0.96 | — |
| corpus findings / `warn` | 251 / 31 | — |
| wall time, 147 crates | ~2.5–4 min | — |

Corpus-wide differential (329 crate versions, 8,426 files), old text engine vs
`safeify-lint`, keyed on `(rule, file, line)`. Artifact:
[`lint_corpus_semantic_2026-11-19.json`](../../research/detect/out/lint_corpus_semantic_2026-11-19.json),
driver [`run_semantic_corpus.py`](../../research/detect/run_semantic_corpus.py).
Semantic engine: 232 findings in 82 files (old census: 251 in 91).

| Rule | old | new | common | old-only | new-only |
|---|---|---|---|---|---|
| `exec_basename` | 85 | 55 | 55 | 30 | 0 |
| `exec_tainted_cmd` | 14 | 15 | 11 | 3 | 4 |
| `fs_tainted_path` | 141 | 155 | 123 | 18 | 32 |
| `build_outside_out_dir` | 4 | 2 | 2 | 2 | 0 |
| `env_read_dangerous` | 5 | 5 | 5 | 0 | 0 |

Old-only causes, each checked against the source:

- **files that are not a Cargo target** (slice-deque `ci/*.rs`, 10 sites): the
  semantic engine walks the crate graph, so a script that no target includes is
  never compiled and never scanned. The text engine lints it anyway.
- **`#[cfg(windows)]` blocks** (arrayfire `build.rs`, 6 sites): only the active
  configuration resolves.
- **`Command` types from unresolved dependencies** (lettre `&self.command`,
  chrono `path`): `no_deps` cannot resolve a non-`std` `Command::new`, so the
  sink is invisible. This is the largest honest coverage gap and is what a
  `--deps` mode would recover.
- **macro arguments** (simd-json `format!(".baseline/{}.json", name)`): macro
  token trees are not walked yet; `format!`/`concat!` need expansion.

New-only causes: the mdbook binding-resolution gains (9) and the openssl field
false positives (2) described above; the remainder are the same classes on other
crates.

Differential status on 10 corpus crates (2026-11-19), old text engine vs
`safeify-lint`, keyed on `(rule, file, line)` — per-crate detail:

| Rule | old | new | common | old-only | new-only |
|---|---|---|---|---|---|
| `exec_basename` | 18 | 15 | 15 | 3 | 0 |
| `exec_tainted_cmd` | 1 | 1 | 1 | 0 | 0 |
| `build_outside_out_dir` | 2 | 1 | 1 | 1 | 0 |
| `fs_tainted_path` | 43 | 53 | 42 | 1 | 11 |

Every remaining difference has a named cause:

- **old-only, `#[cfg(windows)]`** (arrayfire `build.rs` 206/210/222/230):
  rust-analyzer only resolves the active configuration, so code compiled for a
  different target is invisible. The text engine lints it; it does not build
  here. Recorded as a coverage limit, not a bug.
- **new-only, binding resolution** (mdbook `init.rs`, 9 sites): the text engine
  gave up on `themedir.join("css")` because `themedir` was re-bound (its cycle
  detection is name-based); the semantic engine resolves the actual `let`. The
  extra findings are the same class as the 21 it already reported — an
  under-reporting bug in the old engine, now fixed.
- **new-only, missing field summary** (openssl-src `lib.rs`, 2 sites):
  `self.out_dir` is initialised from `env::var("OUT_DIR")` in the build script,
  so the write is legitimate; without a field summary the engine sees only
  "field of self = caller-controlled". This is the false-positive class the
  interprocedural field summary is designed to remove.
- **`RwLock` guard receivers**: `self.write().join(file)` where `write()`
  returns `RwLockWriteGuard<'_, &Path>` does not resolve in `no_deps` mode. The
  engine keeps provenance through path-composition methods (`join`,
  `with_file_name`, …) instead of dropping it; documented in `prov.rs`.

First measurements (2026-11-19), from the loader milestone:

| Crate | `fn` items resolved | calls resolved | method calls resolved | load |
|---|---|---|---|---|
| controlled fixture (`fs`/`env`/`Command`) | 4/4 | 4/4 | 1/4 (`.unwrap` chain) | 2.0 s |
| `grep-cli` 0.1.6 | 99/100 | 83/140 | 36/170 | 2.0 s |
| `abi_stable` 0.9.1 | 2014/2156 | 1112/2246 | 1384/3419 | 2.3 s |
| `arrayfire` 3.5.0 | 173/707 | 201/1200 | 41/603 | 2.0 s |
| `actix-codec` 0.2.0 | 27/27 | 0/41 | 0/37 | 2.0 s |

Reading these honestly: item resolution is ~93–100% except where `#[cfg]`
gates whole modules off (`arrayfire`), and call resolution tracks how much of
a crate's surface is external. In `no_deps` mode a call into `bytes`/`futures`
cannot resolve, so a crate that is mostly glue over dependencies
(`actix-codec`) looks blind — that is a property of the loading mode, not of
the rules, and it is exactly what the parity harness will expose per site.
The fixture proves the semantic path works: `fs::write`, `env::var`,
`process::Command::new`, `fs::File::open`, `process::Command::status` are all
identified from the resolved item, with no source-text matching.

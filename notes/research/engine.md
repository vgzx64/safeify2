# Semantic engine — replacing the regex front end

> **Status: milestone 3 (rules ported; macro bodies, suppressions, feature and
> cross-target coverage) · 2026-11-19**
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

## 5b. What the semantic engine does that text cannot

Seven mechanisms carry most of the depth, and each is a rust-analyzer query
rather than a text pattern:

| Mechanism | Query | Why it matters |
|---|---|---|
| Pattern bindings | `hir::Local::primary_source` → `IdentPat` → enclosing `let` / `if let` / `match` / `for` | `if let Some(p) = env::var(..).ok()` keeps the taint of the scrutinee; the text engine lost it unless the names matched its binding table. |
| Closure adapters | `resolve_method_call` → `Option::map`, then the closure body is evaluated with its parameter bound in a substitution | `env::var_os("OUT_DIR").map(|s| PathBuf::from(s).join("b"))` stays `trusted`; naive text classification either drops it or marks the whole chain tainted. |
| Field summaries | `type_of_expr` → `as_adt` → crate-wide `(struct, field)` index built from record literals and assignments | `self.out_dir` initialised from `OUT_DIR` is trusted, while a field written from a parameter is not. Joins are taint-dominant (a single caller-controlled write wins), unlike the expression-level join. |
| Guards | dominated `if` conditions: `starts_with` whose receiver resolves back to a `canonicalize` call, or `components` + `ParentDir` | a `File::create` inside `if canonical.starts_with(prefix)` is not a counterexample; the same value written after the `if` is. |
| Macro bodies | `expand_macro_call` → walk the expansion | `try!(File::create(path))` and `assert!(matches!(..))` hide their calls in a token tree; the expansion is a real syntax tree whose nodes resolve. |
| Suppressions | `lint_attrs(file_id, crate, item)` over the item's ancestors | `#[allow(safeify::exec_basename)]` works at function, module and crate level, including `cfg_attr` and `#[expect]`; a `// safeify: allow(...)` comment covers the function. |
| Feature and target coverage | `CfgDiff` from the package manifest's features, plus `--extra-cfg` | code gated by `feature = ".."` is analyzed by default; `--extra-cfg windows,target_family=windows` analyzes the Windows branch of `#[cfg]` code.|

## 5c. Two rust-analyzer behaviours worth knowing

**`no_deps` leaks into the sysroot.** `CargoConfig::no_deps` is also passed to
the sysroot workspace load, so `cargo metadata --no-deps` runs on
`rust-src/library` and std loses its `alloc`/`core` edges. The crate graph then
contains `std` with an empty dependency list, and everything re-exported from
`alloc` (`String`, `Vec`, `Box`) or resolved through std impls (`Deref`,
`AsRef`, `ToString`) silently fails to resolve — `String::new()` comes back as a
type error. The engine carries a one-line fix in
[`patches/rust-analyzer-sysroot-deps.patch`](../../research/detect/engine/patches/rust-analyzer-sysroot-deps.patch)
(pass `false` for the sysroot load; `no_deps` describes the analysed package
only), applied by `cargo.sh`. Without it, measured resolution on fixtures drops
from `String`/`PathBuf` methods resolving to *nothing* resolving.

**Item identity needs the crate and the impl container.** Rendering a
resolved item as `module::name` is not enough: `std::fs::write` (free function)
and the `write` method of `impl Write for &File` both render as `fs::write`,
and a crate-local `write` in `sys::unix::io` renders the same way. The engine
takes the crate name from `Crate::display_name`, strips only one leading
`std::`/`core::`/`alloc::` for table lookup, and strips references from the
impl's self type so `impl Write for &File` becomes `File::write`. Without this,
mio 0.6.22 produced two false positives from `(&self.fd).write(src)`, which is
a socket write, not a file write.

**Expression macros are not reachable from `expand_macro_call` in every
configuration.** `format!`/`concat!` inside a body currently expand to nothing
in this setup, so macro arguments stay `unknown` and their sinks are not
reported. Item-level macro calls, derived impls and declarative macros that
produce items are covered by name resolution; expression-macro arguments are a
known gap (see §7).

## 6. Reproducibility

- One local patch to the vendored tree (sysroot dependency edges, §5c),
  checked in as a patch file and applied by `cargo.sh`.
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

## 6b. Porting the frozen inventory (next)

The frozen NIRM-3 evaluation does not use `lint_safe.py`: it uses
[`inventory.py`](../../research/detect/inventory.py), which finds `unsafe`
regions, the calls inside them, raw-pointer dereferences and the function's
guard context by scanning masked text. That is the last regex analysis on the
critical path, and it feeds `detect.py` → `verdict.py` → the 0.2000 accuracy on
the 97-file split.

Port plan, with the same discipline as the rules:

1. `safeify-lint --inventory <crate>` emits one JSON object per file:
   regions (`block`/`fn`), their call sites (resolved path, argument spans),
   raw-pointer derefs (`ast::PrefixExpr` with `UnaryOp::Deref` whose operand
   type is `*const`/`*mut`, which the text engine guessed from the preceding
   word), and the enclosing function's context (name, params, visibility,
   guards: `is_null`, `assert`, `with_capacity`, `len`/`capacity`,
   `saturating_*`/`checked_*`, `matches!` — each a resolved call).
2. A parity harness diffs the per-file `(region range, call callee, deref
   offset)` sets against `inventory.py` on the frozen 288/69/97 files.
3. Only when the diff is empty or explained does `detect.py` switch its
   `inventory.*` calls to the adapter; then the frozen evaluation is re-run and
   the 0.2000 / FP-on-N 0/27 / M-rate numbers are re-measured. If the inventory
   changes, the numbers change and the report says by how much.

Until that lands, the frozen numbers keep describing the text implementation
and no claim in this note applies to them.

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

Corpus-wide differential (329 crate versions, 8,426 files), text engine census
(2026-11-19) vs the semantic engine (host pass ∪ Windows pass, 2026-11-20).
Artifacts:
[`lint_corpus_semantic_2026-11-20.json`](../../research/detect/out/lint_corpus_semantic_2026-11-20.json),
driver [`run_semantic_corpus.py`](../../research/detect/run_semantic_corpus.py).
Semantic engine: **259 findings in 92 files** (census: 251 in 91); severity
distribution 65 `warn` / 194 `info` (census: 31 `warn`).

| Rule | old | new | common | old-only | new-only |
|---|---|---|---|---|---|
| `exec_basename` | 85 | 58 | 57 | 28 | 1 |
| `exec_tainted_cmd` | 14 | 18 | 14 | 0 | 4 |
| `fs_tainted_path` | 141 | 168 | 132 | 9 | 36 |
| `build_outside_out_dir` | 4 | 2 | 2 | 2 | 0 |
| `env_read_dangerous` | 5 | 5 | 5 | 0 | 0 |
| `fs_special_path`, `fs_traversal_literal`, `exec_shell_tainted`, `exec_written_path`, `env_set_dangerous` | 0 | 0 | 0 | 0 | 0 |

Old-only (31), every one checked against the source:

- **27 × a script that is not a Cargo target**: `slice-deque/ci/deploy_and_run_on_ios_simulator.rs`
  is never compiled, so the crate graph does not contain it and the semantic
  engine never scans it. The text engine scanned every `.rs` file it found.
- **4 × `format!` arguments**: `simd-json/examples/perf.rs` writes
  `format!(".baseline/{}.json", name)`; macro *arguments* are still `unknown`
  (§5c), so the sink is not reported. This is the one real recall gap.

New-only (41):

- **mdbook `init.rs`/`fs.rs` (14)**: the text engine lost provenance through a
  re-bound local (`let themedir = self.root.join(themedir)`); resolving the
  actual `LetStmt` reports the writes uniformly with the 21 it already found.
  Same class, under-reporting bug in the text engine.
- **openssl-src `lib.rs` (13)**: `Build::out_dir()` stores a caller value into
  the field, so the field summary is `param`; the library's own writes to it are
  reported at `info`/`warn`. This is the deliberate may-analysis behaviour of
  the field summary (taint dominates trust), and the audit labels judge it.
- **`store_sqlite_tests.rs` (4), `main.rs` (2), `output.rs`/`build.rs` (4)**:
  writes/execs from parameters or environment in test modules and examples that
  the text engine missed through binding/field resolution.
- **1 × `exec_basename`**: a `Command::new("cmd")` in a `#[cfg(windows)]` block,
  recovered by the Windows pass.

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

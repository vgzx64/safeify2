# Semantic engine — replacing the regex front end

> **Status: milestone 4 (rules ported; macro bodies, suppressions, feature and
> cross-target coverage; crate-local calls interpreted at the call site;
> `format!` arguments resolved) · 2026-11-21**
>
> Code: [`safeify-lint/`](../../safeify-lint/).
>
> The engine is the rust-analyzer implementation of `safeify-lint`. The removed
> regex-era Python files are no longer maintained or used for parity.
>
> Naming: the project is **Safeify**. The engine binary is `safeify-lint` and
> the lint namespace is `safeify::<rule>` (`#[allow(safeify::fs_special_path)]`
> or `// safeify: allow(fs_special_path)`; a Cargo `[lints]` table is not read
> because the engine sees source attributes, not rustc flags). "NIRM 3"
> survives only in historical note paths and frozen evaluation artifacts,
> which are cited by filename and are not rewritten.

## 1. Why the regex front end has to go

The counterexample lints were built on masked source text plus regular
expressions. That was a scaffold to get 39 fixtures and a corpus census
quickly, and it worked for the easy half of the problem: literal paths,
literal program names, `env::set_var("PATH", …)`. Three measurements show
where it stops:

| Evidence | What it is really saying |
|---|---|
| 445 of 915 filesystem sink calls classify `unknown` (49%) | The lattice cannot see through a function return, a struct field, or a helper call, because text has no resolution. These calls can never fire, at any severity. §7 measures what the resolved engine actually closes: 331/821, and the remainder is dominated by *unresolved dependencies*, not by function depth. |
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

A Rust binary, `safeify-lint`, that links rust-analyzer **as a library**,
from the vendored source tree (`vendors/rust-analyzer`, git `aa198229`) through
path dependencies, so the analysis engine is pinned to code checked into this
repository. It is not an LSP client: no JSON-RPC, no hover round-trips, no text
parsing. The pipeline is:

```
cargo metadata --no-deps        one shot per crate, ~50 ms, writes no Cargo.lock
  → ProjectWorkspace (crate graph: local package + sysroot)
  → RootDatabase (incremental, salsa)
  → Semantics                     name resolution + type inference, the same
                                  code paths the `rust-analyzer` binary uses
  → rules                         AST visitor over *resolved* nodes
  → findings.json                 [{rule, level, path, line, col, message}]
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
| Is there a guard before the call? | regex over the statement window, matched by callee name | resolved calls on the dominated path: `canonicalize`, `starts_with`, `components`, `ParentDir`, `file_name` |
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
values are tracked *through* calls, returns and struct fields. Cross-crate
depth is out of scope in `no_deps` mode (§4.4).

### 4.1 Implemented: interpretation at the call site

Calls into the analyzed package are **interpreted, not summarised**. When a
call resolves to a `hir::Function` whose crate is the analyzed one
(`Crate::origin(db).is_local()`), the engine:

1. evaluates the actual arguments in the caller's context (each is already a
   `Prov` on the lattice of §5);
2. binds them to the callee's parameters — `Function::assoc_fn_params` gives the
   parameter list (index 0 is `self` for a method), `Param::as_local` the
   `hir::Local`, and `Local::primary_source` the exact pattern node that the
   substitution is keyed by, so every use of that parameter resolves through
   the binding;
3. evaluates the callee's tail expression *and* every `return` expression that
   belongs to it — a `return` inside a nested closure or `fn` belongs to that
   closure and is skipped; and
4. returns the join, which is the value the caller sees.

Method calls take the same path with the receiver bound to `self`. The body is
evaluated because it is *crate-local*, not because its name looks like a sink:
a local `fn join(..)` is interpreted rather than classified by name, and a
local `fn file_name(..)` is not assumed to be `Path::file_name`.

This is context-sensitive by construction. One body serves any number of call
sites, each with its own argument values; there is no shared summary table to
invalidate and no fixed point to iterate. With a five-point lattice and small
path helpers, re-evaluating a body at a call site is cheaper than building,
joining and re-joining per-function summaries, and it is more precise where it
matters: `fn resolve_binary()` is `trusted` only where it actually canonicalises.

Bounds, both in [`safeify-lint/src/prov.rs`](../../safeify-lint/src/prov.rs):
`MAX_DEPTH = 24` expression levels and `MAX_CALL_DEPTH = 8` crate-local calls
along one path. A function already on the traversal stack is not entered again,
so a recursive helper yields `unknown` on that branch; because `unknown`
absorbs in the lattice, the site goes silent instead of inventing a verdict.
Interprocedural evaluation is switched off while the field index is built
(§4.2), where the only question is "what is assigned to this field".

Measured effect on the corpus is in §7; the regression fixture
([`fixtures/interproc`](../../safeify-lint/fixtures/interproc)) fixes
five behaviours: a helper, a two-hop chain and a local method carry the
caller's path into the sink; a literal return makes the sink see the literal; a
callee that keeps only `file_name()` is trusted (silent); a recursive return is
cut (silent).

### 4.2 Field summaries

Per `(struct, field)`, the provenance written anywhere in the crate: record
literals (`S { f: v }`), the shorthand form (`S { f }`), and assignments
(`self.f = v`). The index is context-insensitive on purpose — the question is
"can this field ever carry a caller value" — and the join is **taint-dominant**:
one caller-controlled write makes every read of that field caller-controlled.
`self.out_dir` initialised from `OUT_DIR` therefore stays trusted, while the
same field written from a parameter does not. Reads use the summary when the
crate writes the field at all, and otherwise inherit the base value's
provenance (§5b).

### 4.3 What is *not* implemented, and the report must say so

- **No sink summary propagated to callers.** A sink written inside a helper is
  reported where it is written, with the helper's parameter as `param`; it is
  not re-reported at each caller. Duplicating the finding at call sites would
  inflate counts without new information.
- **No branch-sensitive dataflow.** Only the dominated-`if` guard of §5b is
  modelled (including the early-return form, decided syntactically: the `if`
  body must end in `return`/`break`/`continue`/`panic!`); there is no SSA, no
  path condition, no sanitiser catalogue, and a validation split across
  functions or hidden in a `let ... else`/`match` is not recognised.
- **No heap or aliasing model.** Fields are tracked per type, not per object;
  interior mutability (`Cell`, `Mutex`) is invisible.
- **No cross-crate summaries.** With `no_deps`, dependency sources are not
  loaded, so a wrapper in another crate is `unknown` (§4.4).
- **Proc macros** are not expanded; declarative and `#[derive]` expansions are.
- **One `unknown` branch silences the join.** If any `return`/tail path is
  `unknown` (unresolved dependency call, unexpanded macro, recursion cut), the
  result is `unknown` and no rule fires. This is the same "never guess" policy
  as the rest of the engine, and it is the main precision ceiling.

### 4.4 Why not summaries over a call graph

The earlier plan for this milestone was per-function sink/return summaries plus
a call graph condensed with Tarjan's algorithm and iterated to a fixed point.
Interpretation was implemented instead because the summary version is strictly
weaker for this abstraction: the lattice is five kinds, so a summary is mostly
"taint in, taint out" and the useful distinction — trusted *because* a
canonicalisation happened on this path — is exactly what a context-insensitive
summary loses. Interpretation also removes the fixed-point machinery and its
failure mode (a summary that changes after its callers were already analysed).

The trade-off is cost, bounded by the two depth limits, and precision on
recursion, where a summary would converge to a taint and interpretation cuts to
`unknown`. Recursive path helpers in the corpus are rare and return
collections, where the element provenance is `unknown` either way.

## 5. Migration, with the audit as the gate

The rule IDs, the JSON schema and the severity classes were fixed before the
port so the corpus census stayed comparable. Every rule was ported behind a
differential check: for each rule, the set of `(rule, file, line)` sites of the
text engine versus the semantic engine, where a diff had to be *explained* as
either a capability gain or the text engine's error before the text
implementation was deleted. That harness (`compare_engines.py`) and the text
engine it compared against were retired once every rule reached an explained
diff; the results are the corpus tables in §7. What stays is the Python
orchestration — corpus walking, the frozen split, report generation and the
audit sheet builder are I/O and bookkeeping, not analysis — and the
reproducible rule-level comparison against the frozen census that
[`run_semantic_corpus.py`](../../safeify-lint/corpus/run_semantic_corpus.py)
prints on every run.

## 5b. What the semantic engine does that text cannot

Eight mechanisms carry most of the depth, and each is a rust-analyzer query
rather than a text pattern:

| Mechanism | Query | Why it matters |
|---|---|---|
| Crate-local returns | `Crate::origin` (local) → `Function::assoc_fn_params` / `Param::as_local` bound into the substitution → tail expression and `return`s of the callee body | `fs::write(dest(root, name))` sees what `dest` does with `root` and `name`; a helper that returns `canonicalize(p)` returns the class of `p`. Context-sensitive, no summary table (§4). |
| Pattern bindings | `hir::Local::primary_source` → `IdentPat` → enclosing `let` / `if let` / `match` / `for` | `if let Some(p) = env::var(..).ok()` keeps the taint of the scrutinee; the text engine lost it unless the names matched its binding table. |
| Closure adapters | `resolve_method_call` → `Option::map`, then the closure body is evaluated with its parameter bound in a substitution | `env::var_os("OUT_DIR").map(|s| PathBuf::from(s).join("b"))` stays `trusted`; naive text classification either drops it or marks the whole chain tainted. |
| Field summaries | `type_of_expr` → `as_adt` → crate-wide `(struct, field)` index built from record literals and assignments | `self.out_dir` initialised from `OUT_DIR` is trusted, while a field written from a parameter is not. Field joins are taint-dominant (a single caller-controlled write wins); the expression-level maximum is reserved for branch alternatives. |
| Guards | dominated `if` conditions: `starts_with` whose receiver resolves back to a `canonicalize` call, `components` + `ParentDir`, or an early-return `if !canon.starts_with(..) { return }` whose body leaves | a `File::create` inside `if canonical.starts_with(prefix)` is not a counterexample, and neither is a write after the negated early-return form; a write after the *positive* form is. |
| Macro bodies | `expand_macro_call` → walk the expansion | `try!(File::create(path))` and `assert!(matches!(..))` hide their calls in a token tree; the expansion is a real syntax tree whose nodes resolve. |
| Suppressions | `lint_attrs(file_id, crate, item)` over the item's ancestors | `#[allow(safeify::exec_basename)]` works at function, module and crate level, including `cfg_attr` and `#[expect]`; a `// safeify: allow(...)` comment covers the function. |
| Feature and target coverage | `CfgDiff` from the package manifest's features, plus `--extra-cfg` | code gated by `feature = ".."` is analyzed by default; `--extra-cfg windows,target_family=windows` analyzes the Windows branch of `#[cfg]` code.|

## 5c. Three rust-analyzer behaviours worth knowing (and two engine bugs they hid)

**`no_deps` leaks into the sysroot.** `CargoConfig::no_deps` is also passed to
the sysroot workspace load, so `cargo metadata --no-deps` runs on
`rust-src/library` and std loses its `alloc`/`core` edges. The crate graph then
contains `std` with an empty dependency list, and everything re-exported from
`alloc` (`String`, `Vec`, `Box`) or resolved through std impls (`Deref`,
`AsRef`, `ToString`) silently fails to resolve — `String::new()` comes back as a
type error. The engine carries a one-line fix in
[`safeify-lint/patches/rust-analyzer-sysroot-deps.patch`](../../safeify-lint/patches/rust-analyzer-sysroot-deps.patch)
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

**Formatting is a node, not a macro to guess at.** `format!` expands to
`must_use({ fmt::format(format_args!(..)) })`; evaluating that expansion by hand
is where a text engine gives up. rust-analyzer lowers `format_args!` to a
dedicated `FORMAT_ARGS_EXPR` node whose `template` is an expression and whose
arguments are expressions, and `Semantics::as_format_args_parts` returns the
resolution of every *implicit capture* in the template (`{name}`), so
`format!("{root}/{name}")` and `format!("{}/{}", root, name)` are both "join of
the pieces". The engine reads exactly that node
([`prov.rs::format_args_prov`](../../safeify-lint/src/prov.rs)).
Two consequences worth recording: the result carries no literal *value* (the
pieces are formatted into a new string, so a literal-path rule must not read the
format string as the path), and a multi-line call is reported at the
*argument's* line, not at the first line of the call — the differential harness
sees that as an old-only/new-only pair even though it is the same site.

**Two tables were being consulted with the wrong key.** `is_trusted_producer`
(`path::Path::file_name`) and `taint_source`
(`net::TcpStream::connect`) are keyed by qualified path, but the method branch
looked them up with the bare method name, so `p.file_name()` never matched and
`stream.connect(...)` never became a taint source. Fixed by passing the
resolved `qualified_path`; a regression fixture pins it (`fixtures/interproc`,
`file_only`). The *guard* check (`file_name` on the sink argument) was already
keyed correctly, which is why the bug was invisible: the guard fired on
resolution while the provenance table silently did not.

**Record-expression shorthand** (`S { f }`) has no name ref: the parser stores
the bare path expression as the field's value, so a field index that reads only
`name_ref` never sees the write. `fields::field_name` falls back to the value's
last path segment. Without it, every builder that uses shorthand contributes no
field summary, and fields written from a parameter read as trusted (a silent
recall hole, not a false positive).

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
  already uses ([`safeify-ai/ra_client.py`](../../safeify-ai/ra_client.py),
  `~/.local/share/ra-detect/sysroot`), so `std::fs`/`std::process` paths
  resolve identically in both paths.
- Build wrapper [`safeify-lint/cargo.sh`](../../safeify-lint/cargo.sh)
  points `CARGO_HOME` at `.tools/cargo-home` (the global one is read-only here) and
  the target dir at `.tools/cargo-target`, outside the repository tree.

## 6b. The frozen inventory is semantic now

The frozen NIRM-3 evaluation never used `lint_safe.py`: it used `inventory.py`,
which found `unsafe` regions, the calls inside them, raw-pointer dereferences
and the enclosing function's guard context by scanning masked text. That was
the last regex analysis on the critical path.
[`safeify-ai/semantic_inventory.py`](../../safeify-ai/semantic_inventory.py)
adapts `safeify-lint --inventory <file.rs>` into the same shape, and
`detect.py` consumes it; the text scanner and its parity harness were retired
after the parity result below, with the artifacts kept for provenance.

What the engine resolves where the text scanner guessed:

- **regions**: `BlockExpr` and `Fn` nodes carrying an `unsafe` token, so nested
  blocks, `unsafe extern "C" fn`, `unsafe impl` and `unsafe trait` are
  classified by syntax rather than by matching `unsafe` against brace positions;
- **calls**: `CallExpr` (path callee) and `MethodCallExpr` with argument spans
  from the AST, the written path without turbofish (`Box::<T>::from_raw` is
  `Box::from_raw`) and the resolved item (`core::intrinsics::transmute`) when a
  detached snippet can resolve it at all;
- **calls written inside a macro invocation**: the macro is expanded and every
  node is mapped back to its original source range; when the macro itself does
  not resolve (`log::warn!` under `no_deps`) its parenthesised argument list is
  parsed as an expression, so `warn!("{}", CStr::from_ptr(p))` is inventoried;
- **derefs**: `PrefixExpr` with `UnaryOp::Deref`, operand type classified raw
  pointer / not a raw pointer / unknown. `unknown` is kept (a frozen snippet is
  full of types nothing in the file defines), `not a raw pointer` is excluded;
- **guards**: resolved call names and macro invocations, including calls found
  in macro expansions, so `assert!(p.is_null())` is a `null_check`.

### Parity over the frozen 288 / 69 / 97 files

The (now retired) `inventory_parity.py` harness diffed the two implementations
on the site sets the detector acts on — region ranges, call
callees/spans/arguments, deref offsets, and each region's function
name/signature/guards — after converting the text scanner's character offsets to
the engine's byte offsets (one non-ASCII character before a site shifts every
offset by two). Artifact:
[`inventory_parity_2026-11-20.json`](../../safeify-ai/out/inventory_parity_2026-11-20.json).

**454 files, 217 with at least one difference, 452 differences. No site the
detector acts on is lost**: zero text-only regions and zero text-only spec-DB
calls. 24 spec-DB calls are found that the regex could not match — turbofish
(`mem::transmute::<A, B>(..)`, `collect::<Vec<_>>()`) and absolute paths
(`::std::ptr::write_bytes(..)`, whose leading `::` the regex's lookbehind
rejects). Three text derefs are not recovered, each explained: one `*mut` in a
*type* position (`let (p, ..): (*mut T, ..)` — a text false positive) and two
`*cx` inside `rooted!(in(*cx) let ..)`, whose token list is not an expression.

The remaining buckets are conventions, not disagreements about a site:

| bucket | count | what it is |
|---|---:|---|
| `signature-brace` | 122 | the text scanner's unsafe-fn signature includes the `{` |
| `call-args-trailing-comma` | 75 | `copy(a, b, c,\n)`: the text scanner adds an empty fourth argument |
| `text-nonspec` / `semantic-nonspec` | 75 / 72 | calls outside the spec DB: `Some(x) =>` is a pattern, `collect::<Vec<_>>()` needs turbofish |
| `deref-snippet-truncated` | 30 | the text snippet stops at the first non-identifier character (`*ptr.offset` vs `*ptr.offset(1)`) |
| `semantic-spec-only` | 24 | the turbofish / absolute-path sites above |
| `text-junk` | 16 | the regex matched a keyword or a type fragment (`mut (`, `const (`) |
| `deref-new` | 15 | derefs the text position heuristic missed (`&mut *env`, `while *ptr`) |
| `guard-text` | 8 | the guard regex matched identifier text (`import_assertions`, `assert_abort`) or a call inside a `cfg_if!` braced body |
| `deref-not-raw` | 7 | derefs of references or `Box`, excluded by the adapter |
| `call-args` | 3 | a masked string literal moves the argument start the text scanner reports |
| `signature` | 2 | the text scanner's `rfind("fn")` lands inside a `fn(T)` parameter type |

Known limit: a braced macro body (`cfg_if! { .. }`, `lazy_static! { .. }`) that
does not resolve is skipped; the argument fallback handles parenthesised
argument lists only.

### Re-measured frozen evaluation

Same protocol as the NIRM-3 report, `detect.py` on the semantic inventory
([`nirm3_eval_lsp_semantic_score.txt`](../../safeify-ai/out/nirm3_eval_lsp_semantic_score.txt)):

| Metric | text inventory | semantic inventory |
|---|---:|---:|
| detected sinks / evaluated | 136 / 105 | **139 / 109** |
| accuracy | 0.2000 (21/105) | **0.1927 (21/109)** |
| FP-on-N (gold N → predicted Y) | 0/27 | **0/28** |
| N recall | 0.3704 | 0.3571 |
| claim rate (Y/N, M abstains) | 0.1619 | 0.1560 |
| macro-F1 | 0.2394 | 0.2325 |

Six evaluated sites are added — three turbofish `mem::transmute::<A, B>` calls,
one `::std::ptr::write_bytes`, and two raw derefs the text position heuristic
missed — and two are dropped: `ptr::deref/1-6.rs` used to report two `*ptr`
derefs of a `&mut *const u128`, i.e. derefs of a reference that the operand
type excludes. Net +4 evaluated (105 -> 109); all six new arrivals abstain
(`M low`), so 21/109 are correct instead of 21/105.
The deterministic `--no-lsp` mode tells the same story (13/105 → 13/109,
0.1238 → 0.1193, FP-on-N 0/27 → 0/28), without hover evidence in play.

Per-site verdicts in LSP mode are not attributable one-for-one: `arg_types`
comes from hover, which retries for 0.9 s and then gives up (§7.6 of the NIRM-3
report documents the sensitivity). Re-running the four files whose verdicts
moved reproduced two of them (`Box::from_raw/1-8.rs` and
`CStr::from_ptr/1-12.rs` are claimed `N`, matching the frozen gold) and one
moved back (`Vec::from_raw_parts/3-2.rs` claims `N` again) —
[recheck artifact](../../safeify-ai/out/nirm3_eval_semantic_recheck_2026-11-20.json)
— so the per-site flips are hover variance, not the inventory.

## 7. Measurements the engine must produce

Recorded here as they land, so the claim "semantic > text" is a number and not
an assertion. The semantic column is the 2026-11-21c run after the third review
pass ([counterexamples.md §8](counterexamples.md#defects-found-in-the-2026-11-21-review));
the step-2 run (2026-11-21b), the step-1 run (2026-11-21), the pre-review run
(2026-11-20) and the `_prejoin_` artifacts are retained for the deltas.

| Metric | Text engine | Semantic engine |
|---|---|---|
| filesystem sink calls classified (not `unknown`) | 470/915 (51%) | **545/821 (66%)** |
| — of which the call-site interpretation closes | — | 22 (298 → 276 `unknown`, same binary) |
| command-execution programs classified | not measured | 73/81 (90%) |
| crate-local calls interpreted / recursion cuts / depth cuts | — | 390 / 4 / 0 |
| same-function-only limitations hit by the corpus | dropper class unmeasurable | 5 `info` sites need the interpretation (tuple-return destructuring); the actionable set is unchanged |
| audit precision on the actionable census | 24/25 = 0.96 | **27/28 = 0.96** (§7.1) |
| corpus findings / `warn` | 251 rows / 31 | **286 sites / 35** |
| wall time, 329 packages (12 cores) | ~2.5–4 min | 8 min warm, 13 min cold (10 jobs) |

Corpus-wide differential (329 crate versions, 8,426 files). Artifacts, all
regenerated by [`corpus_report.py`](../../safeify-lint/corpus/corpus_report.py):

- [`lint_corpus_semantic_2026-11-21c_union.json`](../../safeify-lint/out/lint_corpus_semantic_2026-11-21c_union.json)
  — host ∪ Windows pass, **286 findings in 97 files** (census: 249 distinct
  sites in 91 files); severity 35 `warn` / 251 `info` (census: 31 `warn`).
  216 sites are shared with the census; the 33 old-only and 70 new-only sites
  are each accounted for in
  [counterexamples.md §7.2](counterexamples.md#72-corpus-prevalence-current).
  Old-only: 27 non-target `ci/` files, 4 argument-line shifts, 2 `copy`
  sources retired. New-only: 34 composed `param` writes the text engine could
  not see, 4 new warnings, 1 Windows-only `cmd`, 2 argv writes through an
  iterator adapter, 21 `parent`/`canonicalize` writes, 4 `file_name`-descendant
  writes.
- [`lint_corpus_semantic_2026-11-21c_host.json`](../../safeify-lint/out/lint_corpus_semantic_2026-11-21c_host.json) /
  [`_win.json`](../../safeify-lint/out/lint_corpus_semantic_2026-11-21c_win.json)
  — the two cfg passes (329 packages each, **273 / 278** sites; 8 host-only,
  13 Windows-only).
- [`lint_corpus_semantic_2026-11-21c_nointerproc.json`](../../safeify-lint/out/lint_corpus_semantic_2026-11-21c_nointerproc.json)
  — the same host pass with `SAFEIFY_INTERPROC=0`, the A/B for the call-site
  interpretation: it closes 22 calls (298 → 276 `unknown`) and the report
  changes by 5 `info` sites (`mdbook`/`lettre`: a local helper's tuple return is
  destructured, and the tuple carries one caller-controlled element). The
  actionable set is identical.
- [`lint_corpus_semantic_2026-11-21b_union.json`](../../safeify-lint/out/lint_corpus_semantic_2026-11-21b_union.json)
  — the step-2 run (284 sites in 97 files), kept for the delta: 21 `info`
  `parent`/`canonicalize` writes.
- [`lint_corpus_semantic_2026-11-21_union.json`](../../safeify-lint/out/lint_corpus_semantic_2026-11-21_union.json)
  — the step-1 run (263 sites in 96 files), kept for the delta: 2 `info` argv
  writes through `nth`.
- [`lint_corpus_semantic_2026-11-20_union.json`](../../safeify-lint/out/lint_corpus_semantic_2026-11-20_union.json)
  — the pre-review run (261 sites in 94 files).
- [`lint_corpus_semantic_2026-11-20_prejoin_union.json`](../../safeify-lint/out/lint_corpus_semantic_2026-11-20_prejoin_union.json)
  — the pre-fix measurement (263 sites, 65 `warn`) kept for the delta:
  `join` no longer promotes a `param` to `tainted`, so its false warnings are
  now `info` (§7.1 and counterexamples §8).
- the pre-interprocedural measurement (259 findings, commit `6c8f0d8`) stays at
  [`lint_corpus_semantic_2026-11-20.json`](../../safeify-lint/out/lint_corpus_semantic_2026-11-20.json)
  so the delta is reproducible: `corpus_report.py --union ...--baseline` on the
  two files.
- [`stats_2026-11-21c_host.jsonl`](../../safeify-lint/out/stats_2026-11-21c_host.jsonl) /
  [`_win.jsonl`](../../safeify-lint/out/stats_2026-11-21c_win.jsonl) /
  [`_nointerproc.jsonl`](../../safeify-lint/out/stats_2026-11-21c_nointerproc.jsonl)
  — per-crate classification counters behind the first four rows (the corpus
  driver aggregates them; the logs are
  [`corpus_run_2026-11-21c_host.log`](../../safeify-lint/out/corpus_run_2026-11-21c_host.log)
  and `_win.log`).

Reproduce the corpus numbers from the repository root:

```sh
R=safeify-lint/corpus/run_semantic_corpus.py; O=safeify-lint/out
python3 $R --out $O/lint_corpus_semantic_2026-11-21c_host.json --jobs 10
python3 $R --out $O/lint_corpus_semantic_2026-11-21c_win.json --jobs 10 \
    --engine-args windows,target_family=windows
SAFEIFY_INTERPROC=0 python3 $R --out $O/lint_corpus_semantic_2026-11-21c_nointerproc.json --jobs 10
python3 safeify-lint/corpus/corpus_report.py \
    --union $O/lint_corpus_semantic_2026-11-21c_host.json $O/lint_corpus_semantic_2026-11-21c_win.json \
    --baseline $O/lint_corpus_2026-11-19.json \
    --out $O/lint_corpus_semantic_2026-11-21c_union.json
```

### 7.1 Precision audit of the semantic census

The gate for every engine change is the labelled census, not the finding count.
Of the 181 unique sites, 28 are actionable (`warn`/`deny`) in 10 crates; all 28
were read with four lines of context (25 labels carry over from the text-era
sheet, 3 were new in the 2026-11-20 audit; every churn since is `info`, so all
28 keys keep their label), and the labels live in
[`lint_audit_labels_2026-11-21c.json`](../../safeify-lint/out/lint_audit_labels_2026-11-21c.json):

| Rule | sites | correct (TP+TL) | strict TP |
|---|---|---|---|
| `build_outside_out_dir` | 4 | 4 (1.00) | 4 (1.00) |
| `exec_tainted_cmd` | 9 | 8 (0.89) | 5 (0.56) |
| `exec_basename` | 13 | 13 (1.00) | 3 (0.23) |
| `fs_tainted_path` | 2 | 2 (1.00) | 0 (0.00) |
| **all** | **28** | **27 (0.96 [0.82, 0.99])** | **12 (0.43 [0.27, 0.61])** |

The crate-clustered bootstrap interval on the correctness column is
[0.84, 1.00]. The one false positive is `grep-cli` 0.1.6 (patched), unchanged
from the text-engine audit: the program path is produced by a helper in another
crate (`which`), which `no_deps` cannot see, and the field summary is a
may-join. The complete argument — including why 13 correct `exec_basename`
warnings only yield 3 strict hits — is in
[counterexamples.md §7.3](counterexamples.md#73-precision-audit-current-2026-11-21c).

```sh
python3 safeify-lint/audit_lint.py \
    --corpus safeify-lint/out/lint_corpus_semantic_2026-11-21c_union.json \
    --sheet safeify-lint/out/lint_audit_2026-11-21c.jsonl --info-sample 0
python3 safeify-lint/audit_lint.py \
    --sheet safeify-lint/out/lint_audit_2026-11-21c.jsonl \
    --labels safeify-lint/out/lint_audit_labels_2026-11-21c.json --stats
```

Statistics and the sheet are committed next to the labels
(`lint_audit_stats_2026-11-21c.txt`), so the precision and its intervals are
reproducible without re-reading the sites.

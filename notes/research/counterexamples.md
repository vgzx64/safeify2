# Counterexamples in Safe Rust — detection design

> **Status: semantic prototype · Updated 2026-11-21**
>
> Source paper: M. Hassnain, C. Stanford, *Counterexamples in Safe Rust*,
> ASEW '24, [doi:10.1145/3691621.3694943](https://doi.org/10.1145/3691621.3694943).
> Implementation: [`safeify-lint/`](../../safeify-lint/)

## 1. Why this is a separate analysis from NIRM 3's verdicts

The paper's five attack patterns are **safe** Rust: `std::fs`, `std::process`,
and `std::env` are all safe APIs. `safeify-ai` inventories `unsafe { }` regions
and applies Y/M/N replaceability judging, while `safeify-lint` analyzes these
safe-API counterexamples. They remain separate products:

| | replaceability (existing) | counterexample lints (this note) |
|---|---|---|
| input | sinks of 19 unsafe APIs | calls to 4 families of safe APIs |
| evidence | `rust-analyzer` hover types | `rust-analyzer` resolved calls and types, provenance lattice |
| output | `Y`/`M`/`N` + KB pattern | finding at `deny`/`warn`/`info` |
| ground truth | vendor KB gold | none — hand audit needed |
| evaluation | frozen 97-file split | corpus prevalence + audit |

Do not merge the numbers: the lints are not evaluated on the frozen
replaceability split, and the 0.2000 accuracy does not describe them.

## 2. Threat model (and why severity is context-dependent)

The subject is **third-party code that runs on the user's machine**: library
crates, proc-macro crates, `build.rs`. A binary's own `main` calling
`Command::new("git")` is normal engineering, not a vulnerability.

So the lints demote themselves outside that surface: `fs_tainted_path`,
`exec_basename` and `exec_tainted_cmd` are `warn` only in `pub fn` and
`build.rs`; elsewhere they are `info`. Nothing is `allow` by default except
values the analysis cannot see. `deny` is reserved for paths that are
dangerous regardless of who calls them (`/proc/*/mem`, `/dev/mem`,
`\\.\` device namespaces).

## 3. Rules

| Rule | Pattern | Fires on | Default |
|---|---|---|---|
| `fs_special_path` | 1 filesystem | literal path in the danger table: `/proc/*/mem`, `/proc/*/pagemap`, `/proc/kcore`, `/dev/{mem,kmem,port}`, `/etc/ld.so.preload`, `\\.\` and `\\?\` namespaces, writes under `/proc/sys` and `/sys` | `deny` (`warn` for kernel config) |
| `fs_traversal_literal` | 1 | absolute literal whose `..` normalises elsewhere | `warn` |
| `fs_tainted_path` | 1 | **write** sink whose path comes from env/argv/stdio/network with no guard (`warn`), or from a plain parameter (`info`). Reads of caller paths are out of scope; Cargo-provided variables (`OUT_DIR`, `CARGO_MANIFEST_DIR`, `CARGO_PKG_*`) are trusted, not taint | `warn` |
| `exec_basename` | 2 command | `Command::new("ls")` — no path separator, so PATH (and CWD on Windows) resolves it | `warn` |
| `exec_tainted_cmd` | 2 | program name from a parameter or taint source, no allowlist | `warn` |
| `exec_shell_tainted` | 2 | literal `sh`/`bash`/`cmd`… with a caller-controlled argument | `warn` |
| `exec_written_path` | 2 | executes an absolute path this same function wrote earlier (dropper shape) | `warn` |
| `env_set_dangerous` | 5 environment | `set_var`/`remove_var` on `PATH`, `LD_PRELOAD`, `RUSTC`, `RUSTFLAGS`, `TMPDIR`, `HOME`, … | `warn` |
| `env_read_dangerous` | 5 | `var`/`var_os` of the same names (a taint source) | `info` |
| `build_outside_out_dir` | 4 build-time | `build.rs` write whose path contains neither `OUT_DIR` nor `target` | `warn` |

Pattern 3 (compiler unsoundness) is deliberately out of scope: it is fixed in
the compiler, is version-dependent, and cannot be decided from source. The one
cheap exception — nightly features with known-unsound interactions (Fig. 5 uses
`#![feature(arbitrary_self_types)]`) — is a `#![feature]` table, not an
analysis, and is not implemented.

## 4. Provenance lattice

`literal < param < tainted < unknown`, plus `trusted` for values Cargo
provides (`OUT_DIR`, `CARGO_*`) that are safe whoever calls them. `unknown`
never produces a finding; precision comes from refusing to guess. Implemented in
[`safeify-lint/src/prov.rs`](../../safeify-lint/src/prov.rs):

- **literal** — string/byte/raw literal, `Path::new`, `PathBuf::from`,
  `Some(..)`/`Ok(..)`, `concat!` of literals;
- **param** — a function parameter (including `self.field`); reachable from the
  crate API;
- **tainted** — `env::var`, `env::args`, `stdin`, `read_to_string`, `read_dir`,
  `TcpStream`/`UdpSocket`, `current_dir`. `stdin().lines()` yields tainted
  elements; `read_line` returns a byte count and writes into its buffer
  argument, so it is not a value source and is not modelled;
- **propagation** — one `let` chain (depth 3), `format!`/`format_args!`
  (including implicit captures), `+` concatenation, `.to_string`/`.unwrap`/
  `.expect` adapters, iterator adapters that hand back elements (`nth`, `next`,
  `collect`, `lines`, ...) keeping the iterator's class, and **crate-local calls and methods interpreted at the
  call site**: arguments are bound to parameters and the callee's tail
  expression and `return`s are evaluated, so a helper that forwards or resolves
  a path is seen through. Field reads use a crate-wide `(struct, field)`
  summary; a recursive return is cut to `unknown`.

  **Composition is taint-dominant.** `join` (and the other path-composition
  methods), `format!`/`format_args!`, `+` and collection literals all yield a
  value as caller-controlled as their more caller-controlled part:
  `param.join("payload")` stays `param` (`info`), `tainted.join("x")` stays
  `tainted` (`warn`), and a trusted prefix does not launder a suffix
  (`format!("{OUT_DIR}/{user}")` is `param`, not `trusted`). Two literals
  concatenate, so `Path::new("/etc").join("ld.so.preload")` and
  `String::from("/etc/ld.so") + ".preload"` are the literal danger paths. An
  absolute argument discards the base, as `Path::join` does. An unseen
  component joined onto a safe base is `unknown` (it could be absolute).

  **Collections are not scalars.** An array/tuple/record literal has the
  composition of its elements' classes (one caller-controlled element makes the
  collection caller-controlled) but no single literal value; `.iter()` keeps
  the collection's class. A closure parameter bound by an adapter (`.map`,
  `.and_then`, ...) takes the receiver's value; one that no adapter bound
  (`for_each`, `find`, `sort_by`) takes the class of what it iterates, and is
  `unknown` when the closure is not passed to a method (rather than claiming
  the caller controls it).

Guards are recognised only **before** the call in the same function:
`starts_with()` whose receiver resolves back to a `canonicalize()` call
(directly or through a `let`), `components()` + `ParentDir`/`RootDir`, and
`.file_name()` extraction. A raw
`starts_with` on an uncanonicalised path is *not* accepted: prefix-confusion and
`..` components make it unsound.

## 5. Suppression

Clippy conventions, because the audience already knows them:

```rust
#[allow(safeify::exec_basename)]     // enclosing fn, item, module or crate
// safeify: allow(fs_special_path)   // anywhere in the function body
```

Attributes are read through rust-analyzer, so module/crate inheritance and
`cfg_attr` work. A Cargo `[lints.safeify]` table is *not* read: those are rustc
flags, not source attributes, and the engine resolves source. (This is a
deliberate limit; see §9.)

## 6. What this adds over Cargo Scan

The paper obtained its prevalence numbers (Table 2) by running **Cargo Scan**
and then reviewing side effects **by hand** for "triggerable using an argument
to a publicly marked (`pub`) function" — 1,903 top-500 files and 2,920 random
files reviewed manually. Cargo Scan enumerates OS side effects; it has no
notion of a *validated* path, no severity, and no suppression.

The increment here is exactly that manual step, automated and auditable:
`pub`-reachability + guard recognition + a literal danger table + per-rule
severity. The claim to make in the report is **"automates the manual
reachability review"**, not "detects the patterns" — the latter is Cargo Scan's
and the paper's.

## 7. Evaluation

### 7.1 Unit cases (current)

`./safeify-lint/cargo.sh test --release` → **8 tests**: the rule fixtures
(`rules`), interprocedural interpretation (`interproc`), macro and `format!`
evaluation (`macros`), field summaries (`fields`), `build.rs` scoping
(`buildscript`), semantic suppression (`suppress`, `suppress_crate`), the
published-advisory shapes (`advisories`) and the inventory (`inventory`). Each
fixture asserts the exact `(rule, line, level)` set, so a new finding on a
fixture is a failure just like a missing one.

The original 39-case Python suite (`test_lint_safe.py`: Figures 1, 2, 3, 6, 7
plus negatives for each precision decision) was retired together with the text
engine. Its historical result was **39/39**; the behaviours this report relies
on are pinned by the Rust fixtures above, and the two shapes that came from
real advisories are `fixtures/advisories`.

### 7.2 Corpus prevalence (current)

**Current measurement (semantic engine, 2026-11-21b).** Host ∪ Windows pass over
the same 329 package versions (147 crates, 8,426 files), findings deduplicated
by `(rule, path, line)`:

| Rule | deny | warn | info |
|---|---|---|---|
| `exec_basename` | 0 | 16 | 46 |
| `exec_tainted_cmd` | 0 | 13 | 3 |
| `build_outside_out_dir` | 0 | 4 | 0 |
| `fs_tainted_path` | 0 | 2 | 195 |
| `env_read_dangerous` | 0 | 0 | 5 |
| `fs_special_path` | 0 | 0 | 0 |
| `fs_traversal_literal` | 0 | 0 | 0 |
| `env_set_dangerous` | 0 | 0 | 0 |
| `exec_shell_tainted` | 0 | 0 | 0 |
| **total** | **0** | **35** | **249** |

**284 findings in 97 of 8,426 files** (1.2%). Artifacts:
[`lint_corpus_semantic_2026-11-21b_union.json`](../../safeify-lint/out/lint_corpus_semantic_2026-11-21b_union.json)
(host and Windows passes separately in `_host.json` / `_win.json`, and the
`SAFEIFY_INTERPROC=0` A/B in `_nointerproc.json`); the per-rule diff against the
frozen census is printed by
[`run_semantic_corpus.py`](../../safeify-lint/corpus/run_semantic_corpus.py) and
summarised in [engine.md §7](engine.md#7-measurements-the-engine-must-produce).
The step-1 run (263 sites, 2026-11-21) and the pre-review run (261 sites,
2026-11-20) are kept under their dates for the deltas.

Against the frozen census (249 distinct sites in 91 files) the union shares
**218 sites**: 31 old-only and 66 new-only, all explained.

- **Old-only, 27:** `slice-deque`'s
  `ci/deploy_and_run_on_ios_simulator.rs` (3 versions, 8 `exec_basename` + 1
  `fs_tainted_path` each) is not a Cargo target, so it is not in the crate
  graph. The text engine globbed every `.rs` file; the semantic engine analyses
  package code, which is the right surface for shipped code.
- **Old-only, 4 / new-only, 4:** the same `simd-json` `examples/perf.rs` sites,
  now reported at the *argument's* line rather than the multi-line call's first
  line (the `format!` argument; see engine.md §5c).
- **New-only, 34:** writes composed from a caller directory
  (`out_dir.join(..)`, `parent.join(..)`, `self.write().join(file)`) that the
  text engine left `unknown`: `mdbook` 14, `openssl-src` 10,
  `trust-dns-server` 4, `temporary` 2, `lettre` 2, `xcb` 2 — all `info`.
- **New-only, 2:** `cranelift-codegen`'s developer-only `regalloc-snapshot`
  feature writes into the directory named by `SERIALIZE_REGALLOC`
  (env-derived, unguarded) — a correct `warn`.
- **New-only, 2:** `xcb`'s build script runs a formatter whose path is an
  `Option<PathBuf>` parameter — a correct `warn`.
- **New-only, 1:** `openssl-src`'s Windows-only `Command::new("cmd")`, which the
  host-only census could not see.
- **New-only, 2:** `libsbc` 0.1.4/0.1.5 `examples/decode.rs` writes
  `env::args().nth(..)`; the iterator adapter now keeps argv's class (all
  `info`, so the actionable census and every audit label are unchanged).
- **New-only, 21:** writes whose path is `x.parent()`/`canonicalize(x)` with `x`
  caller-supplied — `mdbook` 14 (book, renderer and utils, two versions),
  `trust-dns-server` 4, `xcb` 2, `lettre` 1, all `info`. `parent()` used to be
  an unconditional `trusted` producer, which laundered the caller's class; it
  now keeps it. Every new site is `info`, so the actionable census and all
  labels are unchanged.

**Historical measurement (text engine, 2026-11-19).** The pilot census that
justified the port, on the same corpus:

| Rule | deny | warn | info |
|---|---|---|---|
| `exec_basename` | 0 | 16 | 69 |
| `exec_tainted_cmd` | 0 | 11 | 3 |
| `build_outside_out_dir` | 0 | 4 | 0 |
| `fs_tainted_path` | 0 | 0 | 143 |
| `env_read_dangerous` | 0 | 0 | 5 |
| **total** | **0** | **31** | **220** |

251 findings in 91 of 8,426 files; 26 in `build.rs`, 41 in
`tests/`+`examples/`; concentration `mdbook` 48, `openssl-src` 45,
`slice-deque` 27, `bam` 24, `tough` 22, `arrayfire` 16. Artifact:
[`lint_corpus_2026-11-19.json`](../../safeify-lint/out/lint_corpus_2026-11-19.json).

Caveats: this is a *pilot* corpus, not the paper's crates.io selection, so the
counts are not comparable with their Table 2 rates. `fs_tainted_path` dominates
the `info` stratum because any library that writes to a caller-supplied path
matches — that is why the parameter case is `info` and only writes are
considered.

### 7.3 Precision audit (current, 2026-11-21b)

**Frame.** Census, not a sample: after deduplicating the same code site across
crate versions, the semantic census has **180 unique sites**, of which **28 are
`warn`/`deny` in 10 crates** and 152 are `info`. All 28 were labelled by reading
each site with four lines of context; 25 carry over from the 2026-11-19 sheet
(same `rule|path|line`), 3 were new in the 2026-11-20 audit, and every addition
since (2 on 2026-11-21, 21 on 2026-11-21b) is `info`, so every label still
applies (`lint_audit_labels_2026-11-21b.json` has the same 28 keys). The sheet, labels and
statistics are reproducible:

```
python3 safeify-lint/audit_lint.py \
    --corpus safeify-lint/out/lint_corpus_semantic_2026-11-21b_union.json \
    --sheet safeify-lint/out/lint_audit_2026-11-21b.jsonl --info-sample 0
python3 safeify-lint/audit_lint.py --sheet safeify-lint/out/lint_audit_2026-11-21b.jsonl \
    --labels safeify-lint/out/lint_audit_labels_2026-11-21b.json --stats
```

**Results.** Two numbers, because "is it correct" and "is it worth a human's
attention" are different questions:

| Rule | sites | correct (TP+TL) | strict TP (actionable) |
|---|---|---|---|
| `build_outside_out_dir` | 4 | 4 (1.00) | 4 (1.00) |
| `exec_tainted_cmd` | 9 | 8 (0.89) | 5 (0.56) |
| `exec_basename` | 13 | 13 (1.00) | 3 (0.23) |
| `fs_tainted_path` | 2 | 2 (1.00) | 0 (0.00) |
| **all** | **28** | **27 (0.96 [0.82, 0.99])** | **12 (0.43 [0.27, 0.61])** |

Interval on the correctness column: Wilson 95%; the crate-clustered bootstrap is
[0.84, 1.00]. The single false positive is unchanged: `grep-cli` **0.1.6**, the
patched version. `resolve_binary()` returns an absolute `PathBuf`, but the call
site reads `Command::new(&decomp_cmd.bin)` and the field is written from a value
that comes from `which` in another crate — `no_deps` means the helper is
`unknown`, and the may-join field summary keeps the field caller-controlled.
The warning is right about the pattern and wrong about the version; cross-crate
evidence is what would separate 0.1.5 from 0.1.6, and that is out of reach by
design.

**What the census says.** The lints produce **one false positive in 28**, and
only 43% of the actionable findings would change a reviewer's decision. The
strict hits are `mdbook`'s `pub fn MDBook::test` spawning `rustdoc`, `sys-info`'s
`pub fn hostname()` on Windows, the vulnerable `grep-cli` 0.1.5 line, and six
environment-selected program names (`openssl-src`, `protobuf`, `pyo3`). The
non-actionable ones are `cmake`/`make`/`MSBuild.exe`/`git` invocations in
`build.rs` (8 from `arrayfire`, two versions), and the two `cranelift-codegen`
snapshot writes behind a developer feature.

That is the real result: **a `warn` on `Command::new("cmake")` inside
`build.rs` is correct and useless at the same time.** The pattern is genuine
(Figure 6 of the paper is precisely `Command::new("rustc")` in a build script)
and it is so common that warning on it produces more noise than signal. The
fix is not to demote it — that would hide the paper's own build-time attack —
but to add an explicit allowlist of standard build tools (`cmake`, `make`,
`ninja`, `git`, `rustc`, `cc`, `gcc`, `clang`, `pkg-config`, `install`, `cp`)
that demotes only those names, leaving unusual ones at `warn`. That remains
unimplemented: it changes the census and the strict-TP count, so it needs its
own measurement and audit.

**Not audited.** The 152 unique `info` sites were sanity-checked only (spot
review while building the sheet); no precision number is claimed for them, and
it should not be: by construction they are the "library takes a caller path"
class.

**Limitations of the audit itself.** Single reviewer (self-audit, not blind);
28 sites in 10 crates, all from one vendored corpus; labels are a judgement
about the pattern, not about exploitability in the crate's deployment.

### 7.4 Regression against known advisories (current)

`./safeify-lint/cargo.sh test --release advisory_shapes_fire` asserts three
expectations, including the deliberate negative. The retired Python suite
(`test_rustsec.py`) held the same three and recorded **3/3** on 2026-11-19; the
positive shapes are reconstructed fixtures with the vulnerable call on the
asserted line.

| Advisory | Shape | Outcome |
|---|---|---|
| RUSTSEC-2021-0071 (`grep-cli` 0.1.5) | `Command::new(&decomp_cmd.bin)` — program name is a struct field | `exec_tainted_cmd` on the real `decompress.rs:143` |
| RUSTSEC-2022-0042 (`rustdecimal`) | env check → fetch → write `/tmp` → exec an absolute path | `exec_written_path` on the reconstructed shape |
| RUSTSEC-2022-0058 (`inconceivable`) | macro injects UB behind a feature flag | **no finding** — out of scope |

**The first one initially did not fire.** The program name is a struct field
whose literal is two functions away (`bin: OsStr::new(&args[0])` in the
builder), so the lattice returned `unknown` and the linter stayed silent on the
canonical PATH-hijack advisory. The fix is a principled widening: a field of a
local or parameter value (`cmd.bin`, `self.config.program`) counts as
caller-determined rather than unknown — which is exactly the class
`exec_tainted_cmd` exists for. The regression fixture reproduces the shape (`fixtures/advisories`
`run_decompressor`), so the coverage claim is checked against a call site with
the same provenance structure.

**`rustdecimal` needed a new rule, not a tweak.** It is not a PATH-resolution
or path-taint problem: the binary name is an absolute literal, the payload is
written by the same function, and the trigger is a custom variable
(`GITLAB_CI`) that no dangerous-variable table should contain. The rule that
covers it is def-use — *execute a path this function wrote down* — and it is
implemented as `exec_written_path`: collect the literal paths written before the
call in the same function (`fs::write`, `File::create`, `fs::copy`, …), and fire
when the executed path is one of them. On the corpus it produces **zero**
findings (no crate ships a same-function dropper), so the capability is
free at the precision end. Limitation: cross-function droppers (write in one
helper, exec in another) are invisible, which is the same interprocedural wall
as everything else here.

**`inconceivable` is out of scope:** the UB lives in macro expansion behind a
feature flag. The fixture records the negative so the suite fails if someone
later claims coverage.

### 7.5 Ablation: enumeration versus filtering (done, 2026-11-19)

The original ablation script (`ablate_lints.py`) was retired with the text
engine, and its numbers describe that engine. It counted every call to a sink
family — what a Cargo-Scan-style enumerator reports — against what the lints
emitted:

| family | candidate call sites | findings | survives |
|---|---|---|---|
| filesystem | 915 | 132 | 14.4% |
| command | 115 | 99 | 86.1% |
| environment | 344 | 5 | 1.5% |
| **total** | **1,374** | **251** | **18.3%** |

At `warn` level alone: 31 of 1,374 (2.3%).

Where the filesystem drop comes from: 123 literal paths that are safe, 2
Cargo-provided (`OUT_DIR`/`CARGO_MANIFEST_DIR`), 2 guarded, 160 dynamic *reads*
(out of scope), 37 calls without a path argument. The environment drop is
almost total because `env::var` is only interesting for a fixed list of names
and only at `info`.

Two honest readings:

- **Command execution does not filter.** 88 of 115 are literal basenames, and
  nothing removes them without a tool allowlist. This is the same conclusion as
  §7.3, measured differently: the family is barely filtered because the pattern
  *is* the common case.
- **The blind spot is large.** 445 of 915 filesystem calls (49%) classified
  `unknown` — function returns and complex expressions — and were dropped
  silently. Any recall claim is bounded by that number, which was the strongest
  argument for the interprocedural step.

**Current numbers (semantic engine, 2026-11-20).** The same counters, from the
engine's `--stats` on 329 package versions: 519 of 821 filesystem sink calls are
classified (63%), 302 remain `unknown`; 73 of 81 command-execution programs are
classified; 390 crate-local calls are interpreted, 4 recursion cuts and 0 depth
cuts. With `SAFEIFY_INTERPROC=0` and the same binary, `unknown` rises to 316:
the call-site interpretation closes 14 filesystem sites, and the reported
finding set is byte-identical, so the gain is coverage, not noise. The
`unknown` remainder is dominated by dependency calls (`no_deps`), not by
function depth.

## 8. Bugs found while building this

1. **`arg_spans` dropped literal-only arguments.** `inventory._split_args`
   skipped segments that were blank after masking, so `open("/proc/self/mem")`
   had zero arguments and every such sink was invisible. Fixed: one span per
   positional argument, delimited by commas.
2. **Byte-string masking erased the rest of the line.** The `b"…"` prefix
   branch in `inventory.mask_source` started its scan at the opening quote, so
   `b"ab"` blanked only `b"`, and the closing quote then opened a "string" that
   swallowed everything to the next quote or EOF. Every `b"…"` literal could
   hide code from the analysis. Fixed (`j = i + 2`). The frozen split is
   unaffected: **0 byte-string literals in all 288/69/97 files**, so no
   reported NIRM 3 number changes; `test_detect.py` remains 8/8.
3. **Three precision defects found by the corpus run**, all fixed with
   regression cases: relative `../tests/cert.pem` flagged as traversal;
   *reading* `/proc/sys/kernel/ostype` (what `sys-info` legitimately does)
   flagged as an attack; a `pub fn` path parameter at `warn` instead of `info`.
4. **`OUT_DIR` in a binding counted as "outside OUT_DIR".** The build rule
   tested only the argument text, so
   `let out_dir = env::var("OUT_DIR")?; File::create(Path::new(&out_dir)...)`
   was a false positive — 4 of the 9 `build_outside_out_dir` hits in the first
   audit. Fixed with binding resolution (depth 3) plus a trusted-environment
   class for Cargo-provided variables.
5. **Read sinks shared the write rule.** `fs_tainted_path` fired on
   `fs::metadata`, `File::open`, `read_to_string` — reading a caller's path is
   the library contract, not the paper's counterexample (their figures write).
   Restricted to write sinks; the 137 remaining `info` findings are writes.

### Bugs found in the semantic engine (2026-11-20)

6. **`join` promoted a parameter to a taint source.** `join_prov` returned
   `Tainted` whenever *either* side was caller-controlled, and `is_tainted()`
   includes `param`, so `let out = PathBuf::from(p).join("build")` warned where
   the lattice says `info` (`param`). In the corpus this was 20 of the 23
   unlabelled actionable sites: `openssl-src` build dirs (13), `cranelift-codegen`
   (2), `temporary` (2), `tough` (3). The same function also collapsed
   `literal + literal` to `unknown`, so `Path::new("/etc").join("ld.so.preload")`
   could never reach the danger table — a recall hole, not just noise. Fixed in
   [`sink::join_prov`](../../safeify-lint/src/sink.rs) (composition keeps the
   class of the more caller-controlled part and concatenates two literals),
   pinned by `joined_caller_path` and `joined_special_path` in `fixtures/rules`.
7. **A closure parameter claimed caller control.** `local_prov` classified any
   parameter-shaped binding as `param`, including one bound by `for_each`/`find`,
   so `["python", "python3"].iter().for_each(|bin| Command::new(bin))` warned on
   a literal array (`pyo3` 0.11.1 and 0.12.4 build scripts). A closure parameter
   now takes the class of what the closure iterates (`.iter()` keeps the
   collection's class), and one not passed to a method is `unknown` rather than
   caller-controlled. Pinned by `closure_literal_program` and
   `closure_param_program`.

Both were found by sizing the precision audit (reading every unlabelled
actionable site), which is the argument for keeping the audit as the gate on
engine changes: 22 of the 23 unlabelled sites were two defects, and only the
third (`xcb`'s parameter-chosen `rustfmt`) was a genuine finding.

### Defects found in the 2026-11-21 review

8. **`stdin` was never a taint source, and the documented `read_line` source
   cannot exist at the call's type.** `qualified_path` renders `std::io::stdin`
   by its definition module (`io::stdio::stdin`), but `taint_source` listed only
   `io::stdin`, so every stdin read was `unknown` (counterexamples.md §4 said
   otherwise). `read_line` returns `Result<usize>` and writes the line into its
   `&mut String` argument; marking the method as a source would taint the byte
   count, not the buffer. Fixed by adding the definition path and treating
   `lines()` as a value-preserving adapter; `read_line` is documented as not
   modelled.
9. **The danger table and the platform checks saw only half their inputs.**
   `/proc/<pid>/{mem,pagemap}` matched only for `self` while both notes and
   README promised any PID; a Windows drive path (`C:\...`) was not absolute
   to the dropper pairing, the traversal rule or `join`; and `is_shell`
   compared the whole program string, so `powershell.exe` and `/bin/sh` never
   reached the shell rule. Fixed with a parsed `/proc` matcher, one
   `is_absolute` helper (`/`, `\`, `X:\`, `X:/`), and basename +
   case-insensitive shell matching; each is pinned by a fixture.
10. **A `#[allow]` on a nested `fn` was ignored.** Suppression was computed once
    from the item function's ancestors while the scanner walked nested
    functions too, so the attribute form and the `// safeify: allow(..)` form
    disagreed. Findings are now checked against the innermost enclosing `fn`.
11. **The CLI contract was unusable.** The help still advertised the removed
    `--debug-macro`; findings and engine errors both exited `1` (now `1` and
    `2`); and a failed `cargo metadata` silently disabled every feature cfg
    (now warns and continues).
12. **`format!`, `+` and collection literals used the expression join.**
    `Prov::join` is the Ord maximum, which puts `trusted` above `tainted`, so a
    trusted prefix laundered a caller-controlled suffix:
    `format!("{OUT_DIR}/{user}")` was `trusted` and silent while
    `Path::new(&out).join(user)` was `param` and fired. Composition now uses
    the taint-dominant table (`composition_kind`, shared with `join`), two
    literal pieces concatenate into the value they spell, and the join's detail
    no longer names the trusted side of a `param` result.
13. **`canonicalize` and `parent` were unconditional `trusted` producers.**
    They derive a new path but do not confine it, so `fs::write(canonicalize(p))`
    was silent for a caller-supplied `p`, and `p.parent()` laundered the same
    way. Both now keep the receiver's class and drop the value: 21 new `info`
    sites in the corpus (`mdbook`, `trust-dns-server`, `xcb`, `lettre`) and no
    change to the actionable census.
14. **A `const`/`static` carried no value.** `const MEM: &str = "/proc/self/mem";
    fs::write(MEM, ..)` was `literal` without a value, so a deny-level path was
    invisible behind a name. The initialiser is now evaluated like a `let`.

## 9. Known limitations

Semantic-analysis limits (the engine side is documented in
[engine.md §4.3](engine.md#43-what-is-not-implemented-and-the-report-must-say-so)):

- **Cross-crate depth is out of scope.** `no_deps` is deliberate: dependency
  sources are not loaded, so a wrapper in another crate classifies `unknown`
  and never fires. This is the dominant recall ceiling, not function depth.
- **No branch-sensitive or heap/aliasing model.** Only the dominated-`if` guard
  is modelled; fields are tracked per `(struct, field)`, not per object, so
  interior mutability (`Cell`, `Mutex`) is invisible.
- **One unseen branch silences the join.** An unresolved dependency call, an
  unexpanded proc macro or a recursion cut makes the value `unknown`, and
  `unknown` never fires. Proc macros are not expanded (declarative macros are).
- **Composition is class-preserving, not value-tracked.** `param.join(x)` is
  `info` even if `x` is a literal `../`; pointing a `param` at a danger-table
  path stays `info`. Path *values* are only known for literals.
- **Collections approximate.** An element has the collection's class; element
  types are not tracked, so a `Vec<String>` and its `Vec<PathBuf>` sibling are
  indistinguishable.
- **A sink written inside a helper is reported where it is written**, with the
  helper's parameter as `param`; it is not re-reported at each caller.
- **Severity demotion is a syntactic proxy** for reachability (`pub`,
  `build.rs`), not a call-graph result.
- **Suppression only reads source attributes**; a Cargo `[lints.safeify]` table
  has no effect (§5).

Corpus and evaluation limits:

- **Test and example code inflates counts**; filtering `tests/`/`examples/` may
  be needed before any "real defect rate" claim.
- **`exec_basename` on a standard build tool** (`cmake`, `make`, `git`) is
  correct and useless; the proposed tool allowlist (§7.3) is not implemented —
  it would change the audit numbers, so it needs its own measurement.
- **`exec_written_path` only sees a write and an exec in the same function**;
  a cross-function dropper is interpreted for provenance but not for this
  def-use rule.
- **The `info` stratum has no precision number**; the audit covers the
  actionable (`warn`/`deny`) sites only, in one vendored corpus, by a single
  reviewer.

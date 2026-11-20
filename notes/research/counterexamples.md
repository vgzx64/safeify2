# Counterexamples in Safe Rust — detection design

> **Status: semantic prototype · Updated 2026-11-20**
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
| evidence | `rust-analyzer` hover types | source-level provenance lattice |
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

`literal < param < tainted < unknown`. `unknown` never produces a finding;
precision comes from refusing to guess. Implemented in [`safeify-lint/src/prov.rs`](../../safeify-lint/src/prov.rs):

- **literal** — string/byte/raw literal, `Path::new`, `PathBuf::from`,
  `Some(..)`/`Ok(..)`, `concat!` of literals;
- **param** — a function parameter (including `self.field`); reachable from the
  crate API;
- **tainted** — `env::var`, `env::args`, `stdin`, `read_line`, `read_to_string`,
  `read_dir`, `TcpStream`/`UdpSocket`, `current_dir`;
- **propagation** — one `let` chain (depth 3), `format!`, `+` concatenation,
  `.join`, `.with_file_name`, `.to_string`/`.to_owned`/`.unwrap`/`.expect`
  adapters.

Guards are recognised only **before** the call in the same function:
`canonicalize()` + `starts_with()`, `x.starts_with(root)` on the same
identifier, `components()` + `ParentDir`/`RootDir`, `matches!`/`match`
allowlists, and `.file_name()` extraction.

## 5. Suppression and configuration

Clippy conventions, because the audience already knows them:

```rust
#[allow(nirm::exec_basename)]          // on the enclosing fn
// nirm: allow(fs_special_path)        // on the line above the call
```

```toml
[lints.nirm]
fs_tainted_path = "allow"   # exact rule id
fs = "deny"                 # or a family prefix
```

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

### 7.1 Unit cases (done)

`python detect/test_lint_safe.py` → **39/39**: Figures 1, 2, 3, 6, 7 plus
negatives for each precision decision (guarded path, absolute command,
allowlist, suppression, relative `..`, `/proc/sys` read, `pub fn` path
parameter).

### 7.2 Corpus prevalence (done, pilot)

147 crates / 8,426 files under 100 KB (generated code excluded) from
`research/transitions/external/crates`; `--edition 2021 --no-config`:

| Rule | deny | warn | info |
|---|---|---|---|
| `exec_basename` | 0 | 16 | 69 |
| `exec_tainted_cmd` | 0 | 11 | 3 |
| `build_outside_out_dir` | 0 | 4 | 0 |
| `fs_tainted_path` | 0 | 0 | 143 |
| `env_read_dangerous` | 0 | 0 | 5 |
| `fs_special_path` | 0 | 0 | 0 |
| `fs_traversal_literal` | 0 | 0 | 0 |
| `env_set_dangerous` | 0 | 0 | 0 |
| `exec_shell_tainted` | 0 | 0 | 0 |
| **total** | **0** | **31** | **220** |

251 findings in 91 of 8,426 files (1.1%); 26 are in `build.rs`, 41 in
`tests/`+`examples/`. Concentration: `mdbook` 48, `openssl-src` 45,
`slice-deque` 27, `bam` 24, `tough` 22, `arrayfire` 16. Artifact:
[`lint_corpus_2026-11-19.json`](../../safeify-lint/out/lint_corpus_2026-11-19.json).

Caveats: this is a *pilot* corpus, not the paper's crates.io selection, so the
counts are not comparable with their Table 2 rates. `fs_tainted_path` dominates
the `info` stratum because any library that writes to a caller-supplied path
matches — that is why the parameter case is `info` and only writes are
considered.

### 7.3 Precision audit (done, 2026-11-19)

**Frame.** Census, not a sample: after deduplicating the same code site across
crate versions, the corpus has **25 unique `warn`/`deny` sites in 9 crates**,
and all 25 were labelled by reading each site with four lines of context. The
sheet and labels are reproducible:

```
python safeify-lint/audit_lint.py --corpus safeify-lint/out/lint_corpus_2026-11-19.json \
    --sheet detect/out/lint_audit_2026-11-19.jsonl --info-sample 0
python safeify-lint/audit_lint.py --sheet detect/out/lint_audit_2026-11-19.jsonl \
    --labels detect/out/lint_audit_labels_2026-11-19.json --stats
```

**Results.** Two numbers, because "is it correct" and "is it worth a human's
attention" are different questions:

| Rule | sites | correct (TP+TL) | strict TP (actionable) |
|---|---|---|---|
| `build_outside_out_dir` | 4 | 4 (1.00) | 4 (1.00) |
| `exec_tainted_cmd` | 8 | 7 (0.88) | 5 (0.62) |
| `exec_basename` | 13 | 13 (1.00) | 3 (0.23) |
| **all** | **25** | **24 (0.96 [0.80, 0.99])** | **12 (0.48 [0.30, 0.67])** |

Interval on the correctness column: Wilson 95%; the crate-clustered bootstrap is
[0.80, 1.00], which is the honest width — 9 crates, `arrayfire` contributing 12
of the 25 sites.

The single false positive is `grep-cli` **0.1.6**, the patched version: the fix
resolves the decompressor with `resolve_binary()` in the builder, so `bin` is an
absolute `PathBuf`, but the call site still reads `Command::new(&decomp_cmd.bin)`
and the linter cannot see the resolution across the function boundary. The
warning is right about the pattern and wrong about the version. Cross-function
evidence (or an interprocedural guard) is what would separate 0.1.5 from 0.1.6,
and that is out of reach for this lattice.

**What the census says.** After the fixes below, the lints produce **one false
positive in 25** — the patched `grep-cli` 0.1.6 above. But only 48% of the
actionable findings would change a reviewer's decision: the strict hits are
`mdbook`'s `pub fn MDBook::test` spawning `rustdoc`, `sys-info`'s
`pub fn hostname()` on Windows, the vulnerable `grep-cli` 0.1.5 line, and six
environment-selected program names (`openssl-src`, `protobuf`, `pyo3`). The
non-actionable ones are `cmake`/`make`/`MSBuild.exe`/`git` invocations in
`build.rs`, 8 of them from a single crate (arrayfire, two versions).

That is the real result: **a `warn` on `Command::new("cmake")` inside
`build.rs` is correct and useless at the same time.** The pattern is genuine
(Figure 6 of the paper is precisely `Command::new("rustc")` in a build script)
and it is so common that warning on it produces more noise than signal. The
fix is not to demote it — that would hide the paper's own build-time attack —
but to add an explicit allowlist of standard build tools (`cmake`, `make`,
`ninja`, `git`, `rustc`, `cc`, `gcc`, `clang`, `pkg-config`, `install`, `cp`)
that demotes only those names, leaving unusual ones at `warn`. That is the next
change, and this census is its justification.

**Not audited.** The 214 `info` findings were sanity-checked only (spot review
of 40 while building the sheet; no obviously wrong instance) — no precision
number is claimed for them, and it should not be: by construction they are the
"library takes a caller path" class.

**Limitations of the audit itself.** Single reviewer (self-audit, not blind);
23 sites in 8 crates, all from one vendored corpus; labels are a judgement about
the pattern, not about exploitability in the crate's deployment.

### 7.4 Regression against known advisories (done, 2026-11-19)

`python detect/test_rustsec.py` → 3/3 expectations hold, including the
deliberate negatives.

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
`exec_tainted_cmd` exists for. The suite now asserts the hit on the real line,
so the coverage claim is checked against the vulnerable source, not a
reconstruction.

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

`python detect/ablate_lints.py transitions/external/crates --max-bytes 100000`
counts every call to a sink family — what a Cargo-Scan-style enumerator
reports — against what the lints actually emit:

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
- **The blind spot is large.** 445 of 915 filesystem calls (49%) classify
  `unknown` — function returns and complex expressions — and are dropped
  silently. Any recall claim is bounded by that number, which is the strongest
  argument for the interprocedural step.

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

## 9. Known limitations

- No interprocedural analysis: taint does not cross function boundaries, so a
  wrapper that forwards an argument hides it (one call level would cover most
  of the paper's `pkg_config` shape).
- No macro expansion: `format!` is handled syntactically; other macros are
  opaque, and proc-macro output is never seen.
- `use`-imported bare calls (`write(..)` after `use std::fs::write`) are not
  matched; only `fs::write`/`File::open` shapes are.
- `OpenOptions` aliasing (`use OpenOptions as OO`) defeats the receiver check.
- The danger tables are per-OS and incomplete by construction; Windows coverage
  is a prefix list, not a semantic model.
- Severity demotion is a syntactic proxy for reachability (`pub`, `build.rs`),
  not a call-graph result.


- Test and example code inflates counts; `cargo-scan`-style filtering of
  `tests/`, `examples/` may be needed before any "real defect rate" claim.
- `exec_basename` on a standard build tool (`cmake`, `make`, `git`) is correct
  and useless; needs a tool allowlist (see §7.3).
- `exec_written_path` only sees a write and an exec in the same function.
- 49% of filesystem call sites classify `unknown` (§7.5) and can never fire.
- The `info` stratum has no precision number; the audit covers
  the 25 actionable sites only, in 9 crates, by a single reviewer.

# Counterexamples in Safe Rust — detection design

> **Status: prototype v1 · Updated 2026-11-19 · 37/37 lint checks,
> 8/8 existing detector checks**
>
> Source paper: M. Hassnain, C. Stanford, *Counterexamples in Safe Rust*,
> ASEW '24, [doi:10.1145/3691621.3694943](https://doi.org/10.1145/3691621.3694943).
> Code: [`research/detect/lint_safe.py`](../../research/detect/lint_safe.py),
> [`provenance.py`](../../research/detect/provenance.py),
> [`test_lint_safe.py`](../../research/detect/test_lint_safe.py).

## 1. Why this is a separate analysis from NIRM 3's verdicts

The paper's five attack patterns are **safe** Rust: `std::fs`, `std::process`,
`std::env` are all safe APIs. NIRM 3's pipeline
([`inventory.py`](../../research/detect/inventory.py)) only inventories
`unsafe { }` regions, so none of these patterns enters it, and
[`verdict.py`](../../research/detect/verdict.py)'s Y/M/N replaceability model
has nothing to say about them. The consequence is a second front end:

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
precision comes from refusing to guess. Implemented in
[`provenance.py`](../../research/detect/provenance.py):

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

`python detect/test_lint_safe.py` → **37/37**: Figures 1, 2, 3, 6, 7 plus
negatives for each precision decision (guarded path, absolute command,
allowlist, suppression, relative `..`, `/proc/sys` read, `pub fn` path
parameter).

### 7.2 Corpus prevalence (done, pilot)

147 crates / 8,426 files under 100 KB (generated code excluded) from
`research/transitions/external/crates`; `--edition 2021 --no-config`:

| Rule | deny | warn | info |
|---|---|---|---|
| `exec_basename` | 0 | 16 | 69 |
| `exec_tainted_cmd` | 0 | 9 | 3 |
| `build_outside_out_dir` | 0 | 4 | 0 |
| `fs_tainted_path` | 0 | 0 | 137 |
| `env_read_dangerous` | 0 | 0 | 5 |
| `fs_special_path` | 0 | 0 | 0 |
| `fs_traversal_literal` | 0 | 0 | 0 |
| `env_set_dangerous` | 0 | 0 | 0 |
| `exec_shell_tainted` | 0 | 0 | 0 |
| **total** | **0** | **29** | **214** |

243 findings in 86 of 8,426 files (1.0%); 26 are in `build.rs`, 41 in
`tests/`+`examples/`. Concentration: `openssl-src` 45, `mdbook` 42,
`slice-deque` 27, `bam` 24, `tough` 22, `arrayfire` 16. Artifact:
[`lint_corpus_2026-11-19.json`](../../research/detect/out/lint_corpus_2026-11-19.json).

Caveats: this is a *pilot* corpus, not the paper's crates.io selection, so the
counts are not comparable with their Table 2 rates. `fs_tainted_path` dominates
the `info` stratum because any library that writes to a caller-supplied path
matches — that is why the parameter case is `info` and only writes are
considered.

### 7.3 Precision audit (done, 2026-11-19)

**Frame.** Census, not a sample: after deduplicating the same code site across
crate versions, the corpus has **23 unique `warn`/`deny` sites in 8 crates**,
and all 23 were labelled by reading each site with four lines of context. The
sheet and labels are reproducible:

```
python detect/audit_lint.py --corpus detect/out/lint_corpus_2026-11-19.json \
    --sheet detect/out/lint_audit_2026-11-19.jsonl --info-sample 0
python detect/audit_lint.py --sheet detect/out/lint_audit_2026-11-19.jsonl \
    --labels detect/out/lint_audit_labels_2026-11-19.json --stats
```

**Results.** Two numbers, because "is it correct" and "is it worth a human's
attention" are different questions:

| Rule | sites | correct (TP+TL) | strict TP (actionable) |
|---|---|---|---|
| `build_outside_out_dir` | 4 | 4 (1.00) | 4 (1.00) |
| `exec_tainted_cmd` | 6 | 6 (1.00) | 4 (0.67) |
| `exec_basename` | 13 | 13 (1.00) | 3 (0.23) |
| **all** | **23** | **23 (1.00 [0.86, 1.00])** | **11 (0.48 [0.29, 0.67])** |

Interval on the correctness column: Wilson 95%; the crate-clustered bootstrap is
[1.00, 1.00] because no crate contains a false positive, so there is no
resampling variance to report — with 8 crates and `arrayfire` contributing 12
sites, the honest statement is "no false positive observed", not "precision is
1.00 with tight bounds".

**What the census says.** After the two fixes below, the lints produced **zero
false positives** on this corpus. But only 48% of the actionable findings would
change a reviewer's decision. The three strict `exec_basename` hits are
`mdbook`'s `pub fn MDBook::test` spawning `rustdoc`, and `sys-info`'s
`pub fn hostname()` on Windows; the ten non-actionable ones are
`cmake`/`make`/`MSBuild.exe`/`git` invocations in `build.rs`, 8 of them from a
single crate (arrayfire, two versions).

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

### 7.4 Regression against known CVEs (next)

Must fire on:

- RUSTSEC-2021-0071 (`grep-cli`): Windows CWD-relative executable resolution
  → `exec_basename`;
- RUSTSEC-2022-0058 (`inconceivable`): build-time UB injection →
  `build_outside_out_dir` / `exec_basename` in `build.rs`;
- `rustdecimal`: env-var-triggered payload → `env_read_dangerous` +
  `exec_tainted_cmd`.

### 7.5 Ablation (next)

Baseline = "Cargo-Scan-style": flag every `fs`/`process`/`env` call
unconditionally. Report how many of our findings survive guard filtering — the
difference is the increment of the provenance layer, and the only fair way to
claim it.

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
- The `info` stratum (214 findings) has no precision number; the audit covers
  the 23 actionable sites only, in 8 crates, by a single reviewer.

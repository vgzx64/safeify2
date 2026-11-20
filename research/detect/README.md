# detect — stable-only replaceable-unsafe detector

> **Status: experimental (NIRM 3) · Updated: 2026-11-19**
>
> Evaluation protocol and current caveats:
> [notes/nirm3/report.md](../../notes/nirm3/report.md) and
> [notes/nirm3/results.md](../../notes/nirm3/results.md). This README documents
> the detector itself; it does not claim a final result.

Detects unsafe sinks in Rust code and emits **Y/M/N replaceability verdicts**
grounded in the SafeNet knowledge base, the synth rule cells, and CULPA specs —
using a pure-Python LSP client against a stable rust-analyzer. No nightly, no
CULPA build.

## Pipeline

```
.rs file
  └─ semantic_inventory.py
                    engine/cargo.sh build --release, then `safeify-lint
                    --inventory <file>`: unsafe { } / unsafe fn spans, the
                    calls inside them with resolved items, raw derefs (operand
                    type checked), guards (null_check, assert, ...) — all from
                    rust-analyzer's syntax tree.
  └─ ra_client.py   rust-analyzer over stdio: didOpen -> hover evidence
                    (arg types, e.g. `owner: &String` vs `*mut i32`)
  └─ spec_db.py     42 rule cells (research/synth/rules/*.yaml) + gold Y/M/N
                    per (api, pattern_id) from research/synth/splits/kb_verdicts.json
  └─ verdict.py     family table + LSP evidence -> Y/M/N + reason + safe
                    alternative + encapsulate hint; claims pattern-level gold
                    ONLY with real evidence
  └─ verify.py      optional rustc --emit=metadata gate (same recipe as
                    research/synth/verify/check.py)
```

## One-time setup

The detector needs a stable `rust-analyzer` binary and a `rust-src` sysroot.
This checkout pins the `2026-08-24` release; `.tools/` is gitignored.

```sh
# from the repository root
mkdir -p .tools/ra-bin .tools/ra-home
curl -fsSL -o .tools/ra-bin/rust-analyzer.gz \
  https://github.com/rust-lang/rust-analyzer/releases/download/2026-08-24/rust-analyzer-x86_64-unknown-linux-gnu.gz
gunzip .tools/ra-bin/rust-analyzer.gz
chmod +x .tools/ra-bin/rust-analyzer

# Normal environment with a writable $HOME:
sh detect/setup_rust_src.sh
```

If `$HOME` is read-only (this sandbox), point `HOME` at a writable workspace
directory for both setup and runs, while keeping the real Rust toolchain homes:

```sh
export RUSTUP_HOME=/path/to/.rustup CARGO_HOME=/path/to/.cargo
HOME="$PWD/.tools/ra-home" sh detect/setup_rust_src.sh
```

`setup_rust_src.sh` downloads the `rust-src` component matching the local
stable rustc (network: static.rust-lang.org), builds a symlink-farm sysroot in
`$HOME/.local/share/ra-detect/sysroot`, and installs a `rustc` shim that only
redirects `--print sysroot`. The shim is prepended to PATH **only for the
rust-analyzer child process** (`ra_client.ra_env`); nothing system-wide changes.
`ra_env()` resolves the shim through `Path.home()`, so the `HOME` used to run
`setup_rust_src.sh` must also be set when running the detector.

## Usage

```sh
source ../.venv/bin/activate          # PyYAML only; python >= 3.10
# when using the workspace-local setup above:
export PATH="$PWD/.tools/ra-bin:$PATH"
export HOME="$PWD/.tools/ra-home"
python detect/test_detect.py          # 8-test suite (LSP e2e included)
python detect/score_frozen.py --report detect/out/report.json \
    --split test                      # confusion, per-class P/R/F1, risk-coverage,
                                      # file-clustered 95% CIs
python detect/export_retrieval.py detect/out/report.json \
    --out detect/out/retrieval.json   # pattern hints -> eval_protocol --retrieval-preds
python detect/detect.py ../vendors/SafeNet/testdata/ptr::read \
    --json detect/out/report.json     # LSP mode (default)
python detect/detect.py file.rs --no-lsp    # syntactic only, no rust-analyzer
python detect/detect.py dir/ --json -       # JSON report to stdout
```

The LSP e2e test is timing-sensitive: one run in the 2026-11-18 audit failed
transiently and three consecutive reruns passed. The same timeouts affect
verdicts: six `from_raw`/`CStr` sinks changed between two full test-split runs
with no code change, and a three-times re-run of the affected files produced
one flip. Treat a single LSP run as non-deterministic by a few sinks; see
[report.md §7.6](../../notes/nirm3/report.md#7-failure-analysis).

Example (synth `ptr::read` p1 snippet, LSP mode):

```
synth/out/snippets/ptr::read/1-synth-1295-unsafe.rs: 1 sink(s), 1 unsafe region(s)
  L5    ptr::read   std::ptr::read(owner)  -> Y (high) gold=Y
```

## Safe-Rust counterexample lints

A second, independent front end for the attack patterns of Hassnain & Stanford,
"Counterexamples in Safe Rust" (ASEW '24): safe `std::fs` / `std::process` /
`std::env` / `build.rs` code that violates memory safety through OS interfaces.
These are implemented in the rust-analyzer semantic engine, not source-text
regexes. They are **not** part of the Y/M/N model and are **not** scored on the
frozen split. Design, threat model, corpus numbers and limitations:
[notes/research/counterexamples.md](../../notes/research/counterexamples.md).

```sh
engine/cargo.sh test --release
.tools/cargo-target/engine/release/safeify-lint --crate path/to/package
```

Suppress a rule with `#[allow(safeify::fs_special_path)]` on the function,
module or crate (resolved by rust-analyzer, so `cfg_attr` and `#[expect]`
work), or with a `// safeify: allow(fs_special_path)` comment in the function.

Calls into the analyzed package are *interpreted at the call site*: the
arguments are bound to the callee's parameters and its tail expression and
`return`s are evaluated, so `fs::write(dest(root, name))` sees what `dest` does
with `root` and `name` (calls are cut to `unknown` at recursion and at depth 8).
`format!("{root}/{name}")` is read from rust-analyzer's `FORMAT_ARGS_EXPR`,
including implicit captures.

The frozen NIRM-3 evaluation (`detect.py`) consumes this inventory through
`semantic_inventory.py`, so the unsafe regions, calls, raw derefs and guard
context there come from the syntax tree and resolved types, not from masked
source text. Historical parity records are retained under
`research/detect/out/` for provenance.

`--stats <FILE>` (or `--stats -` for one stderr line) writes classification
counters: how many filesystem/exec sink calls were `literal`/`param`/`tainted`/
`trusted`/`unknown`, and how many crate-local calls were interpreted or cut.
`SAFEIFY_INTERPROC=0` turns the call-site interpretation off; the corpus driver
(`--stats-out`) aggregates both, which is how the coverage numbers in
[engine.md](../../notes/research/engine.md) §7 are produced.

Known limits: calls whose callee lives in an unresolved dependency are
invisible (`no_deps`); a recursive return is cut to `unknown` (so its site goes
silent); and code that no Cargo target includes is not analyzed at all.

## Verdict policy (v1)

| family | default | upgrade rules (evidence needed) |
|---|---|---|
| unchecked\* | **Y** high | always (KB: unchecked family is uniformly replaceable) |
| unchecked arith | **Y** high | use `+`/`checked_*` |
| transmute | M low | Y when hover shows primitive->primitive types |
| ptr::read | M low | Y only for a **local** owner (KB p1/p5: `&s`, `&this.inner`, `&v[i]` with local `v`); a `&`-borrow rooted at a parameter or `self` (`&self.entries[i]`, `&v[0]` with `v: &mut [T]`) is **N** high (KB p2); `_param_names()` supplies the parameter list, `&a as *const _` casts stay raw evidence |
| ptr::deref / as_ref | M low | Y when signature has owner/ref (KB p1) |
| from_raw\* / from_ptr | M low | N when arg hover is `*mut/*const` (KB p1, owner outside) |
| set_len / copy / zeroed / offset_from | M low | guarded M variants; encapsulate hint |

Invariants: Y/M/N matches `kb_verdicts.json` taxonomy; pattern-level gold
(`kb_gold`) is reported only when pattern-1-style evidence was actually
observed; unclassifiable sinks stay **M/low** (never guess Y/N); the frozen
splits (288/69/97) are read-only inputs.

## JSON schema (per sink)

`file, line, col, api, kind, callee, call_text, args, span, region, fn{name,
signature,guards}, evidence{arg_types,ret_type,lsp}, verdict{v, confidence,
reason, safe_alternative, encapsulate, pattern_hint, kb_gold, rules}`

## rust-analyzer notes (this build, tag 2026-08-24)

- Bare `rust-analyzer` is the stdio LSP server (no `--stdio` flag).
- Loose files are analyzed via a temp Cargo project whose `src/lib.rs` is a
  symlink to the original; **documents must be opened at the in-workspace
  symlink path** or hover returns null.
- Readiness = first `publishDiagnostics` for the opened doc (crate loaded);
  hovers before that return null, so `Analyzer._wait_ready` waits for it.
- Pipe reads must use `read1` (plain `read(65536)` blocks until 64KB arrive).
- `shutdown`/`exit` may exit nonzero; the client ignores it.

## Limitations (v1)

- Pattern classification beyond p1 (dataflow-heavy KB patterns) is out of
  scope: those sinks are M/low with the rule contracts attached.
- `safe_alternative` is a suggestion string, not an automated patch; the
  verify gate currently checks whole files/snippets only.
- `.as_ref()` on non-pointer receivers inside unsafe blocks can match the
  `as_ref` API (acceptably rare; refine with receiver-type evidence later).
- One rust-analyzer process per file (~2.6–9.4 s each): fine for targeted
  files, slow for whole-repo sweeps (batching = reuse one server with multiple
  didOpens, future work).
- Verdicts are not fully reproducible: `ra_client` timeouts (15 s request, 45 s
  readiness) can drop hover evidence to `{unknown}` and turn an `N` into `M`.
  Evidence caching or a loud readiness failure is the planned fix.
- Never fabricates metrics; no evaluation numbers are produced here — scoring
  stays in `research/synth/splits/eval_protocol.py` and
  `research/detect/score_frozen.py` against the frozen splits.

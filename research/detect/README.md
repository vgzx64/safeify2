# detect — stable-only replaceable-unsafe detector

> **Status: experimental (NIRM 3) · Updated: 2026-10-24**
>
> Evaluation protocol and current caveats:
> [notes/nirm3/results.md](../../notes/nirm3/results.md). This README documents
> the detector itself; it does not claim a final result.

Detects unsafe sinks in Rust code and emits **Y/M/N replaceability verdicts**
grounded in the SafeNet knowledge base, the synth rule cells, and CULPA specs —
using a pure-Python LSP client against a stable rust-analyzer. No nightly, no
CULPA build.

## Pipeline

```
.rs file
  └─ inventory.py   unsafe { } / unsafe fn spans (offset-preserving masker),
                    sink calls matched against the spec DB, raw-deref fallback,
                    syntactic guards (null_check, assert, with_capacity, ...)
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

```sh
# rust-analyzer on PATH (already at ~/.local/bin/rust-analyzer)
sh detect/setup_rust_src.sh   # rust-src shim; needed for hover/type evidence
```

`setup_rust_src.sh` downloads the `rust-src` component matching the local
stable rustc (network: static.rust-lang.org), builds a symlink-farm sysroot in
`~/.local/share/ra-detect/sysroot`, and installs a `rustc` shim that only
redirects `--print sysroot`. The shim is prepended to PATH **only for the
rust-analyzer child process** (`ra_client.ra_env`); nothing system-wide changes.

## Usage

```sh
source ../.venv/bin/activate          # PyYAML only; python >= 3.10
python detect/detect.py ../vendors/SafeNet/testdata/ptr::read \
    --json detect/out/report.json     # LSP mode (default)
python detect/detect.py file.rs --no-lsp    # syntactic only, no rust-analyzer
python detect/detect.py dir/ --json -       # JSON report to stdout
python detect/test_detect.py          # 7-test suite (LSP e2e included)
```

Example (synth `ptr::read` p1 snippet, LSP mode):

```
synth/out/snippets/ptr::read/1-synth-1295-unsafe.rs: 1 sink(s), 1 unsafe region(s)
  L5    ptr::read   std::ptr::read(owner)  -> Y (high) gold=Y
```

## Verdict policy (v1)

| family | default | upgrade rules (evidence needed) |
|---|---|---|
| unchecked\* | **Y** high | always (KB: unchecked family is uniformly replaceable) |
| unchecked arith | **Y** high | use `+`/`checked_*` |
| transmute | M low | Y when hover shows primitive->primitive types |
| ptr::read | M low | Y when arg hover is `&T` (KB p1, owner in frame) |
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
- Never fabricates metrics; no evaluation numbers are produced here — scoring
  stays in `research/synth/splits/eval_protocol.py` and
  `research/detect/score_frozen.py` against the frozen splits.

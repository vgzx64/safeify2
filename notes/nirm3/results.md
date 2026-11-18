# NIRM 3 — results and protocol

> **Status: provisional audit · Updated: 2026-11-18 · Not a final result**
>
> The numbers below were produced from the working tree after pinning
> `rust-analyzer 0.3.3025` (2026-08-24) on `rustc 1.100.0`. They replace the
> 2026-10-24 audit and the archived v1/v2/v3 notes. The test split has been
> reused; this is exploratory, not a clean holdout result.
>
> Authoritative narrative: [report.md](report.md).

## Protocol

- Frozen real test split: `research/synth/splits/test.txt`, seed 1234;
  `make_splits.py --check` → `OK` (train 288 / valid 69 / test 97).
- 97 test files, 136 detected sinks, **105 evaluated**; 31 sinks are excluded as
  `api_mismatch` because the file contains more than one API.
- Gold: `research/synth/splits/eval_manifest.json`; verdict taxonomy and
  per-pattern gold in `research/synth/splits/kb_verdicts.json`.
- Scorer: `research/detect/score_frozen.py`.
- Metrics are per sink against the file-level gold verdict. Sinks in the same
  file are correlated; 105 sinks come from 97 files and 68 `(api, pattern)`
  cells, so treat the sample as clustered, not independent.
- **Test reuse caveat:** the test split was used for v1 → v2 → v3 bug-fix
  iterations and again for the 2026-10-24/2026-11-18 audits. The “report test
  once” rule was not followed. The current run is exploratory until a fresh
  holdout or an explicit disclosure is in place.

## Current run (2026-11-18)

### LSP mode

| Metric | Value |
|---|---:|
| Accuracy | 0.1714 (18/105) |
| `FP-on-N` | **2/27** |
| `recall_N` | 0.2593 (7/27) |
| Y predictions / precision | 4 / 0.5000 |
| Decisive claims | 14/105 |
| Pattern claims / correct | 14 / 7 (0.5000) |
| Abstention (`M`) rate | 0.8667 (91/105) |

Per class:

| Gold | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Y | 69 | 0.5000 | 0.0290 | 0.0548 |
| M | 9 | 0.0989 | 1.0000 | 0.1800 |
| N | 27 | 0.7000 | 0.2593 | 0.3784 |

Macro-F1 is **0.2044**. The 14 decisive claims are 4 `Y` and 10 `N`; 9 are
correct (2 `Y` + 7 `N`).

### No-LSP mode

| Metric | Value |
|---|---:|
| Accuracy | 0.1048 (11/105) |
| `FP-on-N` | **2/27** |
| `recall_N` | 0.0000 |
| Y predictions / precision | 4 / 0.5000 |
| Decisive claims | 4/105 |
| Pattern claims / correct | 4 / 1 (0.2500) |

Confusion (LSP, rows = gold, cols = pred):

| gold | Y | M | N |
|---|---:|---:|---:|
| Y | 2 | 64 | 3 |
| M | 0 | 9 | 0 |
| N | 2 | 18 | 7 |

No-LSP shifts the 3 LSP-only `Y -> N` false negatives back to `M`: gold Y is
`2 Y / 67 M / 0 N`, so no-LSP has no false `N` but also no `N` recall.

### Baselines

On the same 105 sinks, constant-`Y` gives accuracy `0.657` and macro-F1 `0.265`
(but 27 `FP-on-N`, so it is not a usable detector); constant-`M` gives accuracy
`0.086`. The headline accuracy is therefore not evidence of useful
classification — the operative result is the selective one: 14 claims, 9
correct verdicts, 7 correct patterns.

### The false positives

Both current `FP-on-N` cases are the same file and expression:

```rust
// vendors/SafeNet/testdata/ptr::read/2-1.rs, lines 26 and 52
self.entries[j] = std::ptr::read(&self.entries[i]);
```

Gold is `ptr::read` **p2 = N**. The `owner_shaped` branch in
`research/detect/verdict.py` treats the dotted/indexed argument as an in-frame
owner and emits `Y/high` without concrete type evidence. This affects both LSP
and no-LSP modes and is a direct violation of the “no dangerous false positives”
claim. At file level it is 1/23 N files; at sink level it is 2/27.

A separate p1-only assumption in the reconstruction (`from_raw*`) rule produces
false `N` in LSP mode on three gold-Y files: `Box::from_raw/4-1.rs`,
`Rc::from_raw/1-1.rs`, and `Vec::from_raw_parts/4-3.rs`. These are conservative
in direction but still wrong verdicts.

### Pattern hints

Only 14 hints are claimed, 7 correct. The wrong hints are p1-biased:
`Box::from_raw/3-1` (p1 vs p3), `Box::from_raw/4-1` (p1 vs p4),
`Vec::from_raw_parts/3-2` (p1 vs p3), `Vec::from_raw_parts/4-3` (p1 vs p4),
`ptr::read/2-1` (p1 vs p2, twice), and `ptr::read/5-3` (p1 vs p5). Pattern
classification beyond p1 needs dataflow; NIRM 3 does not attempt it.

## Change from the 2026-10-24 audit

The 2026-10-24 run gave accuracy `0.1714`, `FP-on-N 2/27`, `recall_N 0.2593`,
13 claims / 6 correct. The 2026-11-18 rerun gives the same accuracy and FP, but
one more gold-Y sink moves to `N` (14 claims / 7 correct, M-rate 0.8667 instead
of 0.8762). The likely cause is the pinned `rust-analyzer`/`rustc` pair: the
2026-10-24 run used an older stable toolchain, and the LSP evidence path was
never pinned. The archived v3 note (`0.162`, `0/27`, `0.296`) remains
non-reproducible.

Do not mix tables from different runs. The 2026-11-18 numbers are the current
baseline; the archived v1/v2/v3 and 2026-10-24 numbers are history.

## Failure analysis

1. **Gold-Y remains mostly `M`:** 64/69 gold-Y sinks are predicted `M` in LSP
   mode. The classifier is p1-shaped; patterns that need inter-procedural
   dataflow are deliberately left for NIRM 4. This is a design limitation, not a
   bug.
2. **Gold-N recall is low:** 18/27 gold-N sinks remain `M`; the detector is
   conservative. The 7 correct N claims concentrate in `CStr::from_ptr`,
   `CString::from_raw`, `Rc::from_raw`, and `Vec::from_raw_parts`, which have
   usable pointer evidence at the reconstruction site.
3. **Evidence quality is compilability-bound:** many SafeNet testdata files are
   fragments (WinRT FFI, truncated sources) that do not compile standalone;
   hover yields `{unknown}` and the sink stays `M`. The report must say this.
4. **Corpus defects:** 20 excluded files, 14 label-conflict duplicate groups,
   6 cross-API identical sequences, 31 `api_mismatch` sinks. These are
   documented in `research/synth/splits/stats.json`; no sensitivity analysis has
   been done for the excluded sinks.
5. **No intervals:** there are no confidence intervals or clustered bootstrap
   estimates. With 105 sinks and 14 decisive claims, the uncertainty is large.

## Limitations

- Pattern classification beyond p1 needs dataflow; NIRM 3 does not attempt it.
- `M/low` is the default, so the tool abstains on most sinks.
- LSP evidence depends on the file compiling in a detectable crate context.
- One rust-analyzer process per file (~10 s/file here); no repo-scale batching.
- `safe_alternative` is a suggestion string; no automated patch.
- MIR/borrowck is not implemented and currently has no owning milestone.
- Results are verdict-level, not pattern-retrieval results.
- The test split has been reused; a fresh holdout is still required.

## Reproduce

```bash
cd research
export PATH="$PWD/../.tools/ra-bin:$PATH"
export HOME="$PWD/../.tools/ra-home"
export RUSTUP_HOME=/home/user/.rustup CARGO_HOME=/home/user/.cargo
source ../.venv/bin/activate

python detect/test_detect.py
python synth/splits/make_splits.py --check
python synth/splits/check_train_leakage.py

T=synth/splits/test.txt
sed "s|^|../vendors/SafeNet/testdata/|" "$T" | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --json detect/out/nirm3_eval_lsp.json
sed "s|^|../vendors/SafeNet/testdata/|" "$T" | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --no-lsp --json detect/out/nirm3_eval_nolsp.json

python detect/score_frozen.py --report detect/out/nirm3_eval_lsp.json \
  --report2 detect/out/nirm3_eval_nolsp.json \
  | tee detect/out/nirm3_eval_score.txt
```

Artifacts:

- [LSP score report](../../research/detect/out/nirm3_eval_lsp_score.txt)
- [No-LSP score report](../../research/detect/out/nirm3_eval_nolsp_score.txt)
- [LSP raw JSON](../../research/detect/out/nirm3_eval_lsp.json)
- [No-LSP raw JSON](../../research/detect/out/nirm3_eval_nolsp.json)

# NIRM 3 — results and protocol

> **Status: provisional audit · Updated: 2026-10-24 · Not a final result**
>
> The numbers below were produced from the uncommitted working tree. They are
> recorded to expose a reproducibility problem, not to replace a frozen
> evaluation. Re-run after the tree is committed and the `ptr::read` regression
> is fixed.

## Protocol

- Frozen real test split: `research/synth/splits/test.txt`, seed 1234.
- 97 test files, 136 detected sinks, **105 evaluated**; 31 sinks are excluded as
  `api_mismatch` because the file contains more than one API.
- Gold: `research/synth/splits/eval_manifest.json`; verdict taxonomy and
  per-pattern gold in `research/synth/splits/kb_verdicts.json`.
- Scorer: `research/detect/score_frozen.py`.
- Metrics are per sink against the file-level gold verdict. Sinks in the same
  file are correlated; 105 sinks come from 97 files and 68 `(api, pattern)`
  cells, so treat the sample as clustered, not independent.
- **Test reuse caveat:** the test split was used for v1 → v2 → v3 bug-fix
  iterations. The “report test once” rule in the archived plan was not
  followed. The current run is exploratory until a fresh holdout or an explicit
  disclosure is in place.

## Known discrepancy

The archived v3 note reports:

| Metric | Archived v3 (2026-10-19) | Current tree (2026-10-24) |
|---|---:|---:|
| 3-way accuracy | 0.162 (17/105) | **0.171 (18/105)** |
| `FP-on-N` (gold N → pred Y) | **0/27** | **2/27** |
| `recall_N` | 0.296 (8/27) | **0.259 (7/27)** |
| Pattern claims / correct | 10 / 5 | **13 / 6** |
| Y precision | table says 4 Y; confusion has 0 Y | **0.500 (4 Y)** |

`research/detect/verdict.py` was modified on 2026-10-22, three days after the
archived note, and the result was never updated. The archived table is also
internally inconsistent: it lists four Y predictions while its confusion matrix
has zero entries in the Y column. The raw report files named in the archive no
longer exist.

## Current run

### LSP mode (2026-10-24)

| Metric | Value |
|---|---:|
| Accuracy | 0.1714 (18/105) |
| `FP-on-N` | **2/27** |
| `recall_N` | 0.2593 (7/27) |
| Y predictions / precision | 4 / 0.500 |
| Decisive claims | 13/105 |
| Pattern claims / correct | 13 / 6 (0.462) |
| Abstention (`M`) rate | 0.8762 |

Per class:

| Gold | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Y | 69 | 0.500 | 0.029 | 0.055 |
| M | 9 | 0.098 | 1.000 | 0.178 |
| N | 27 | 0.778 | 0.259 | 0.389 |

Macro-F1 is **0.207**. Baselines on the same 105 sinks: constant-`Y` gives
accuracy `0.657` and macro-F1 `0.265` (but 27 `FP-on-N`, so it is not a usable
detector); constant-`M` gives accuracy `0.086`. The headline accuracy is
therefore not evidence of useful classification — the operative result is the
selective one: 13 decisive claims, 9 with the right verdict, 6 with the right
pattern.

### No-LSP mode (2026-10-24)

| Metric | Value |
|---|---:|
| Accuracy | 0.1048 (11/105) |
| `FP-on-N` | **2/27** |
| `recall_N` | 0.000 |
| Y predictions / precision | 4 / 0.500 |
| Decisive claims | 4/105 |
| Pattern claims / correct | 4 / 1 |

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
false `N` on two gold-Y files (`Box::from_raw/4-1.rs`,
`Vec::from_raw_parts/4-3.rs`): it assumes p1 whenever it sees a raw pointer.
These are conservative in direction but still wrong verdicts.

## Superseded history

Do not cite these as current results. They are retained to explain why the
protocol needs a fresh run.

| Run | Accuracy | `FP-on-N` | Notes |
|---|---:|---:|---|
| no-LSP v1 | 0.143 (15/105) | 1 | evidence-free transmute Y |
| LSP v1 | 0.133 (14/105) | 0 | hover parsing bugs |
| no-LSP v2 | 0.086 (9/105) | 0 | after three bug fixes |
| LSP v3 | 0.162 (17/105) | 0 | claimed final; not reproducible now |

Source: [archive index](../archive/README.md). The two archived NIRM notes
disagree on some v1/v2 details; neither is authoritative.

## Failure analysis

1. **Gold-Y remains mostly `M`:** 65/69 gold-Y sinks are predicted `M`. The
   classifier is p1-shaped; patterns that need inter-procedural dataflow are
   deliberately left for NIRM 4. This is a design limitation, not a bug.
2. **Gold-N recall is low:** 18/27 gold-N sinks remain `M`; the detector is
   conservative. The 7 correct N claims are concentrated in `CStr::from_ptr`,
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
   estimates. With 105 sinks and 13 decisive claims, the uncertainty is large.

## Limitations

- Pattern classification beyond p1 needs dataflow; NIRM 3 does not attempt it.
- `M/low` is the default, so the tool abstains on most sinks.
- LSP evidence depends on the file compiling in a detectable crate context.
- One rust-analyzer process per file (~2.6–9.4 s); no repo-scale batching.
- `safe_alternative` is a suggestion string; no automated patch.
- MIR/borrowck is not implemented and currently has no owning milestone.
- Results are verdict-level, not pattern-retrieval results.

## Reproduce

```bash
export PATH="$HOME/.local/bin:$PATH"
cd research && source ../.venv/bin/activate

python detect/test_detect.py
python synth/splits/make_splits.py --check

T=synth/splits/test.txt
sed "s|^|../vendors/SafeNet/testdata/|" "$T" | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --json detect/out/nirm3_eval_lsp.json
sed "s|^|../vendors/SafeNet/testdata/|" "$T" | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --no-lsp --json detect/out/nirm3_eval_nolsp.json

python detect/score_frozen.py --report detect/out/nirm3_eval_lsp.json \
  --report2 detect/out/nirm3_eval_nolsp.json \
  | tee detect/out/nirm3_eval_score.txt
```

## Artifacts

- [LSP score report](../../research/detect/out/nirm3_eval_lsp_score.txt)
- [No-LSP score report](../../research/detect/out/nirm3_eval_nolsp_score.txt)
- [LSP raw JSON](../../research/detect/out/nirm3_eval_lsp.json)
- [No-LSP raw JSON](../../research/detect/out/nirm3_eval_nolsp.json)

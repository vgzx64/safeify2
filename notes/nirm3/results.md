# NIRM 3 — results and protocol

> **Status: provisional audit · Updated: 2026-11-18 · Not a final result**
>
> The numbers below come from the working tree after pinning
> `rust-analyzer 0.3.3025` (2026-08-24) on `rustc 1.100.0` and after the
> `ptr::read` fix (`00f83e9`). They replace the 2026-10-24 audit and the
> archived v1/v2/v3 notes. The test split has been reused; this is exploratory,
> not a clean holdout result.
>
> Authoritative narrative: [report.md](report.md).

## Protocol

- Frozen real test split: `research/synth/splits/test.txt`, seed 1234;
  `make_splits.py --check` → `OK` (train 288 / valid 69 / test 97).
- 97 test files, 136 detected sinks, **105 evaluated**; 31 sinks are excluded as
  `api_mismatch` because the file contains more than one API.
- Gold: `research/synth/splits/eval_manifest.json`; verdict taxonomy and
  per-pattern gold in `research/synth/splits/kb_verdicts.json`.
- Scorer: `research/detect/score_frozen.py` — confusion, per-class P/R/F1,
  macro-F1, coverage/risk, risk–coverage, pattern hints, and file-clustered
  bootstrap 95% intervals (2,000 resamples of files, seed 1234).
- Metrics are per sink against the file-level gold verdict. Sinks in the same
  file are correlated; 105 sinks come from 97 files and 68 `(api, pattern)`
  cells, so the sample is clustered, not independent — hence file-level
  resampling.
- **Test reuse caveat:** the test split was used for v1 → v2 → v3 bug-fix
  iterations and again for the 2026-10-24/2026-11-18 audits. The “report test
  once” rule was not followed. The current run is exploratory until a fresh
  holdout or an explicit disclosure is in place.

## Current run (2026-11-18, post-fix)

### LSP mode

| Metric | Value |
|---|---:|
| Accuracy | 0.2000 (21/105) |
| `FP-on-N` | **0/27** |
| `recall_N` | 0.3704 (10/27) |
| Y predictions / precision | 2 / 1.0000 |
| Decisive claims (coverage) | 17/105 (0.1619) |
| Errors among claims (risk) | 5 / 0.2941 |
| Pattern claims / correct | 17 / 10 (0.5882) |
| Abstention (`M`) rate | 0.8381 (88/105) |

Per class:

| Gold | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Y | 69 | 1.0000 | 0.0290 | 0.0563 |
| M | 9 | 0.1023 | 1.0000 | 0.1856 |
| N | 27 | 0.6667 | 0.3704 | 0.4762 |

Macro-F1 is **0.2394**. The 17 decisive claims are 2 `Y` and 15 `N`; 12 are
correct (2 `Y` + 10 `N`). All claims are `high` confidence, so risk–coverage has
a single operating point: coverage 0.1619, risk 0.2941 (`Y` claims risk 0.0000,
`N` claims risk 0.3333).

File-clustered 95% intervals: accuracy `[0.1238, 0.2925]`, `recall_N`
`[0.1724, 0.6000]`, macro-F1 `[0.1583, 0.3923]`; `FP-on-N` is 0/27 in every
resample of this run.

Confusion (rows = gold, cols = pred):

| gold | Y | M | N |
|---|---:|---:|---:|
| Y | 2 | 62 | 5 |
| M | 0 | 9 | 0 |
| N | 0 | 17 | 10 |

### No-LSP mode

| Metric | Value |
|---|---:|
| Accuracy | 0.1238 (13/105) |
| `FP-on-N` | **0/27** |
| `recall_N` | 0.0741 (2/27) |
| Y predictions / precision | 2 / 1.0000 |
| Decisive claims (coverage) | 4/105 (0.0381) |
| Errors among claims (risk) | 0 / 0.0000 |
| Pattern claims / correct | 4 / 3 (0.7500) |
| Abstention (`M`) rate | 0.9619 (101/105) |

Macro-F1 is **0.1193**; 95% intervals: accuracy `[0.0588, 0.2020]`,
`recall_N` `[0.0000, 0.2400]`, macro-F1 `[0.0700, 0.2413]`. No-LSP makes only
four claims, so its zero risk is close to vacuous.

Confusion (rows = gold, cols = pred):

| gold | Y | M | N |
|---|---:|---:|---:|
| Y | 2 | 67 | 0 |
| M | 0 | 9 | 0 |
| N | 0 | 25 | 2 |

No-LSP shifts the five LSP-only `Y -> N` false negatives back to `M` and keeps
the two `ptr::read` `N` claims, so it has no false `Y` but almost no `N` recall.

### DoD #3: retrieval

`detect/export_retrieval.py` exports the modal sink `pattern_hint` per file as
`{id, pattern_id}`; files without a hint get `0` (a miss). This is a
**substitution and a lower bound** — the detector is not a retrieval model.

| Mode | Queries | Files with a claim | Top-1 pattern accuracy | Macro per-API recall | Recall on `N` |
|---|---:|---:|---:|---:|---:|
| LSP | 97 | 22 (0.227) | 0.0928 | 0.0988 | 5/23 = 0.2174 |
| No-LSP | 97 | 7 (0.072) | 0.0206 | 0.0159 | 1/23 = 0.0435 |

`eval_protocol.py` scores per **snippet** (23 `verdict=N` snippets), not per
sink, so these denominators differ from the tables above.

### Baselines

On the same 105 sinks, constant-`Y` gives accuracy `0.657` and macro-F1 `0.265`
(but 27 `FP-on-N`, so it is not a usable detector); constant-`M` gives accuracy
`0.086`. The headline accuracy (0.2000) is still below constant-`Y`, so it is
not evidence of useful classification — the operative result is the selective
one: 17 claims, 12 correct verdicts, 10 correct patterns, 0 dangerous-direction
errors.

### The false positives (fixed)

The two previous `FP-on-N` cases were the same expression:

```rust
// vendors/SafeNet/testdata/ptr::read/2-1.rs, lines 26 and 52
self.entries[j] = std::ptr::read(&self.entries[i]);
```

Gold is `ptr::read` **p2 = N**. `owner_shaped` treated the indexed argument as
an in-frame owner and emitted `Y/high` without concrete type evidence. The rule
now distinguishes a local owner (KB p1/p5: `ptr::read(&this.inner)`,
`ptr::read(&v[i])`, `ptr::read(&me.buf)` → `Y`) from a `&`-borrow rooted at a
parameter or `self` (KB p2: `&self.entries[i]`, `&v[0]` with `v: &mut [T]`,
`&b.1` with `b: Self` → `N`). Both modes now give `N` on `2-1.rs`; regression
test `test_ptr_read_borrowed_param_n`.

A separate p1-only assumption in the reconstruction (`from_raw*`) rule produces
false `N` in LSP mode on five gold-Y files: `Box::from_raw/4-1`,
`CString::from_raw/4-4`, `Rc::from_raw/1-1`, `Rc::from_raw/1-3`,
`Vec::from_raw_parts/4-3`. These are conservative in direction but still wrong
verdicts.

### Pattern hints

17 hints are claimed, 10 correct. The seven wrong hints are all p1 over-claims:
`Box::from_raw/3-1` (p1 vs p3), `Box::from_raw/4-1` (p1 vs p4),
`CString::from_raw/3-4` (p1 vs p3), `CString::from_raw/4-4` (p1 vs p4),
`Vec::from_raw_parts/3-2` (p1 vs p3), `Vec::from_raw_parts/4-3` (p1 vs p4), and
`ptr::read/5-3` (p1 vs p5). Pattern classification beyond p1 needs dataflow;
NIRM 3 does not attempt it.

## Change from the 2026-10-24 audit

The 2026-10-24 run gave accuracy `0.1714`, `FP-on-N 2/27`, `recall_N 0.2593`,
13 claims / 6 correct. The 2026-11-18 post-fix run gives `0.2000`, `0/27`,
`0.3704`, 17 claims / 12 correct. Two effects are mixed here:

1. the `ptr::read` fix: `FP-on-N` 2/27 → 0/27, +2 `N` claims;
2. `rust-analyzer` run variance: six `from_raw`/`CStr` verdicts differ from the
   previously committed run with no code change (`CStr::from_ptr/1-12` `N→M`;
   `CString::from_raw/3-4`, `CString::from_raw/4-4`, `Rc::from_raw/1-3`,
   `Vec::from_raw_parts/1-3`, `ptr::deref/4-8` `M→N`). Re-running three of
   those files three times produced one flip (`ptr::deref/4-8`). Mechanism:
   `ra_client` hover/diagnostics timeouts (15 s request, 45 s readiness) leave
   `{unknown}` evidence on a slow start.

Do not mix tables from different runs, and do not treat a single run as a
stable measurement. The 2026-11-18 post-fix numbers are the current baseline;
the archived v1/v2/v3 and 2026-10-24 numbers are history.

## Failure analysis

1. **Gold-Y remains mostly `M`:** 62/69 gold-Y sinks are predicted `M`, 5 `N`,
   2 `Y`. The classifier is p1-shaped; patterns that need inter-procedural
   dataflow are deliberately left for NIRM 4. This is a design limitation, not a
   bug.
2. **Gold-N recall is low:** 17/27 gold-N sinks remain `M`; the detector is
   conservative. The 10 correct N claims concentrate in `CStr::from_ptr`,
   `CString::from_raw`, `Rc::from_raw`, and `Vec::from_raw_parts`, which have
   usable pointer evidence at the reconstruction site.
3. **Evidence quality is compilability-bound:** many SafeNet testdata files are
   fragments (WinRT FFI, truncated sources) that do not compile standalone;
   hover yields `{unknown}` and the sink stays `M`. The report must say this.
4. **Corpus defects:** 20 excluded files, 14 label-conflict duplicate groups,
   6 cross-API identical sequences, 31 `api_mismatch` sinks. These are
   documented in `research/synth/splits/stats.json`; no sensitivity analysis has
   been done for the excluded sinks.
5. **Verdicts are not fully reproducible:** see “Change from the 2026-10-24
   audit” above; the noise is confined to the raw-pointer-evidence family and is
   bounded by ±6 sinks here. Evidence caching (or failing loudly on readiness
   timeout) is the follow-up.

## Limitations

- Pattern classification beyond p1 needs dataflow; NIRM 3 does not attempt it.
- `M/low` is the default, so the tool abstains on 83.81% of sinks.
- LSP evidence depends on the file compiling in a detectable crate context.
- One rust-analyzer process per file (~10 s/file here); no repo-scale batching.
- `rust-analyzer` timeouts make a few verdicts run-dependent.
- `safe_alternative` is a suggestion string; no automated patch.
- MIR/borrowck is not implemented and currently has no owning milestone.
- Results are verdict-level; retrieval is a `pattern_hint` export, not a model.
- The test split has been reused; a fresh holdout is still required.

## Reproduce

```bash
cd research
export PATH="$PWD/../.tools/ra-bin:$PATH"
export HOME="$PWD/../.tools/ra-home"
export RUSTUP_HOME=/home/user/.rustup CARGO_HOME=/home/user/.cargo
source ../.venv/bin/activate

python detect/test_detect.py                 # 8/8
python synth/splits/make_splits.py --check   # OK
python synth/splits/check_train_leakage.py   # OK

T=synth/splits/test.txt
sed "s|^|../vendors/SafeNet/testdata/|" "$T" | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --json detect/out/nirm3_eval_lsp.json
sed "s|^|../vendors/SafeNet/testdata/|" "$T" | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --no-lsp --json detect/out/nirm3_eval_nolsp.json

python detect/score_frozen.py --report detect/out/nirm3_eval_lsp.json \
  --report2 detect/out/nirm3_eval_nolsp.json \
  | tee detect/out/nirm3_eval_score.txt

python detect/export_retrieval.py detect/out/nirm3_eval_lsp.json \
  --out detect/out/nirm3_retrieval_lsp.json
python synth/splits/eval_protocol.py --retrieval-preds \
  detect/out/nirm3_retrieval_lsp.json | tee detect/out/nirm3_retrieval_score.txt
```

Artifacts:

- [Combined score](../../research/detect/out/nirm3_eval_score.txt)
- [LSP score report](../../research/detect/out/nirm3_eval_lsp_score.txt)
- [No-LSP score report](../../research/detect/out/nirm3_eval_nolsp_score.txt)
- [LSP raw JSON](../../research/detect/out/nirm3_eval_lsp.json)
- [No-LSP raw JSON](../../research/detect/out/nirm3_eval_nolsp.json)
- [Retrieval score](../../research/detect/out/nirm3_retrieval_score.txt)

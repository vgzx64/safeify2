# safeify-data/transitions — CVE transition mining

> **Status: v0.2 FROZEN · 2026-11-08 · 433 rows · 8 gates pass · split leakage 0 · binary label target verified by two blind spot-checks**
>
> Design: [transition dataset plan](../../notes/research/transition-dataset.md)
> Findings: [pilot report](../../notes/research/transition-dataset-pilot.md)

This directory contains three independent extractors over
`rust_ecosystem/CVEfixes.db` and the cloned repositories:

- `extract_candidates.py` — analyzer-first. Starts from `unsafe_block`, keeps
  blocks whose exact key is absent from `unsafe_block_fix` while the function
  still exists, then checks the real parent/fix snapshots and the diff.
- `mine_diff.py` — diff-first. Starts from `file_change.diff`, isolates the
  deleted lines that contain `unsafe`, and keeps hunks whose added code is
  safe (or still unsafe) and whose before/after text is present in the
  repository objects.
- `mine_patterns.py` — targeted API patterns (`set_len`, `get_unchecked`,
  `uninit`, `from_raw*`, `Pin::new_unchecked`, ...). It also records
  `conditional` rows where the unsafe API disappears but unsafe code remains.

All three write one row per candidate with commit, parent, path, function, spans,
old/new snippets, and a provisional type. `build_manifest.py` merges them,
deduplicates by the actual old text, joins CVE metadata, and writes the audit
CSVs.

## Commands

```bash
cd safeify-data/transitions
python extract_candidates.py
python mine_diff.py
python mine_patterns.py
python build_manifest.py
python cap_negatives.py
python zero_shot_eval.py
python collect_hunks.py
python adjudication/make_queue.py --pilot 30 --name pilot_002
python rebuild_v01.py
python check_split_leakage.py
python baseline_tfidf.py
python train_model.py
python score_spotcheck.py
python label_reliability.py
python freeze_v02.py
# baseline suite (2026-11-21): no GPU, no external drive needed
python baseline_suite.py            # TF-IDF / GB / RF, repo-grouped CV + valid
python embed_modernbert.py          # frozen ModernBERT-base cache (CPU ~24 min)
python baseline_embeddings.py       # linear / kNN probes on the cache
python baseline_concat.py           # char TF-IDF + embedding concat probe
```

The DB is opened read-only. Parent commits come from `ext_commits`, because
`git rev-parse <hash>^` fails for some of the local mirrors.

## Outputs

| File | Content |
|---|---|
| `out/candidates.jsonl` | analyzer-first candidates (59) |
| `out/diff_candidates.jsonl` | diff-first candidates (433) |
| `out/pattern_candidates.jsonl` | targeted pattern candidates (44) |
| `out/manifest.jsonl` | merged, deduplicated candidates (454) |
| `labels_safe.csv` | stable manual labels for 90 safe + 6 conditional rows (replayed by `build_manifest.py`) |
| `out/safe_audit.csv` | safe candidates with manual labels |
| `out/conditional_audit.csv` | 6 conditional/guard candidates |
| `out/unsafe_audit.csv` | unsafe-to-unsafe candidates, unreviewed |
| `out/negative_sample_audit.csv` | 29-row pre-recovery negative audit |
| `out/negative_pool_capped.csv` | capped non-signature negative pool (84) |
| `out/negative_audit_v2_sample.csv` | 28-row capped negative audit |
| `out/zero_shot/summary.json` | detector zero-shot results |
| `out/all_hunks.jsonl` | 772 strict unsafe-changing CVEfixes hunks |
| `adjudication/queue.jsonl` | 458-row LLM adjudication queue |
| `adjudication/labels_002.jsonl` | 30 clean pilot labels |
| `out/rustsec_hunks.jsonl` | 189 unsafe-changing RustSec PR/commit hunks |
| `out/source_inventory.json` | counts for CVEfixes, SafeNet, synth, RustSec, crates.io, docs, Linux |
| `adjudication/reviewed_all.jsonl` | 607 adjudicated rows (CVEfixes + crates.io + RustSec + Linux) |
| `adjudication/reviewed_all_stats.json` | 104 Y / 166 M / 259 N / 78 U, 76 vetoed |
| `out/positive_union.jsonl` | 119 candidate positives / 109 families |
| `out/negative_core.jsonl` | 425 reviewed M/N rows (259 N, 166 M) |
| `out/transitions_core_draft.jsonl` | 231-row unfrozen core draft (118 Y / 57 M / 56 N) |
| `out/transitions_core_v0.2_draft.jsonl` | 433-row pre-freeze draft (109 Y / 193 N / 131 M) |
| `out/transitions_core_v0.2.jsonl` | **frozen** 433-row core, binary `target` field, `frozen: true` |
| `out/transitions_core_v0.2_quality.json` | gate report: 8 gates pass, 0 split leakage, label verification |
| `out/manifest_v0.2.json` | freeze manifest (sha256 of core + quality) |
| `out/splits_v0.2.json` | canonical-repository split (216/87/130) |
| `out/label_reliability.json` | three blind spot-check passes and the binary-vs-M/N finding |
| `adjudication/corrections.jsonl` | reviewer corrections replayed on every rebuild |
| `adjudication/spotcheck2_*.jsonl`, `spotcheck3*_*.jsonl` | blind samples and second-annotator labels |
| `out/repo_identity.json` | cached crates.io package -> repository identity |
| `out/baseline_valid.json` | valid-split smoke-test baseline (TF-IDF + logistic regression) |
| `out/context_v0.2.jsonl` | 60-line pre-fix context window per row (`train_model.py`) |
| `out/train_v0.2.json` | first training run: snippet vs context, grouped CV + valid |
| `out/baseline_suite_v0.2.json` + `.md` | 2026-11-21 baseline suite: majority, TF-IDF (word/char/union) + LR, TF-IDF+SVD + GB/RF; repo-grouped CV + valid |
| `out/baseline_modernbert_v0.2.json` + `.md` | frozen ModernBERT-base embeddings + linear/kNN probes, same protocol |
| `out/baseline_concat_v0.2.json` + `.md` | char TF-IDF + embedding concatenation probe |
| `adjudication/gate_batches.json` | gate-closing run: 161 queue rows + 170 expansion families |
| `adjudication/labels_gate_*.jsonl` | 11 adjudication batch outputs (331 rows) |
| `out/spotcheck_gate.json` | documented spot-check correction (1 Y -> M) |
| `out/split_leakage.json` | repo-alias/cross-split duplicate audit (`check_split_leakage.py`) |
| `out/splits_draft.json` | repo-level 70/10/20 draft split |
| `out/stats.json`, `out/diff_stats.json`, `out/pattern_stats.json` | extractor counters and rejects |
| `out/manifest_stats.json` | merged distributions |

## Baseline suite (2026-11-21)

All three suites use the same protocol: repository-grouped 5-fold CV on
`train` (216 rows / 54 positives), fit on `train`, score `valid` (87 rows /
22 positives), `test` (130 rows) sealed. Input is `old_snippet` only.

| probe | CV AUC | valid AUC | valid F1(Y) | valid AP |
|---|---:|---:|---:|---:|
| majority | 0.500 | 0.500 | 0.000 | 0.253 |
| char TF-IDF + LR | 0.868 | 0.641 | 0.378 | 0.397 |
| word TF-IDF + LR | 0.716 | 0.544 | 0.256 | 0.317 |
| TF-IDF + SVD + GB | 0.582 | 0.601 | 0.138 | 0.335 |
| TF-IDF + SVD + RF | 0.563 | 0.559 | 0.000 | 0.302 |
| frozen ModernBERT + LR | 0.716 | 0.634 | 0.400 | 0.412 |
| char TF-IDF + ModernBERT | 0.699 | 0.633 | 0.391 | 0.415 |

The CV-to-valid drop is the point: grouped CV over `train` repositories is
optimistic, and no representation transfers cleanly to the 31 unseen
`valid` repositories. All valid 95% bootstrap CIs overlap (AUC ~0.49-0.78),
so the differences between the best probes are inside noise. This is a
baseline report, not a model claim; the frozen encoder is not yet worth
fine-tuning on this label budget (109 positives total), and the next lever is
label expansion plus audit, not architecture.

## Important caveats

- **Frozen, with a binary target.** v0.2 is frozen at 433 rows and eight
  gates. The three-class Y/M/N target is *not* reproducible: two independent
  annotators agreed on 95% of the Y-vs-not-Y decisions (kappa 0.82) but only
  kappa 0.42-0.52 on M vs N. Train and report `target` (Y = 1, M/N = 0); use
  `M` only as a descriptor. Repository identity is canonical
  (`host/owner/repo`) via `repo_identity.py`; 30 alias groups merge into 154
  repositories and `check_split_leakage.py` reports 0 cross-split duplicates.
  Three rows keep a `pkg:`/`name:` fallback identity (`abox`, `atom`,
  `torvalds_linux`).
- **Split is label-stratified, not source-stratified.** 216 train / 87 valid /
  130 test by whole canonical repository, with positives 54 / 22 / 33; every
  split holds CVEfixes, crates.io and RustSec rows, but the mix is not forced.
- **Training does not transfer yet.** Grouped CV reaches 0.831 AUC on `train`,
  but the same model gets 0.665 on held-out repos and a 60-line context window
  drops to 0.388. Do not present a one-sided trained model as a result; 54
  training positives across 22 of the 42 training repositories is the ceiling.
  The next model trains on synthetic pairs (`research/synth`) and uses this
  core as external validation.
- **Early extraction had known noise.** The original 90 safe rows included 2
  duplicates, 7 false positives, 1 signature-only change, and 6 unclear rows;
  the 347 unsafe-to-unsafe rows were mostly refactors/signature changes. The
  strict hunk pass and LLM adjudication superseded that pool.
- **Hunk-level, not token-level.** A safe snippet is the added lines in the
  overlapping hunk; it is a semantic review of a diff pair, not a verified
  patch. LLM adjudication plus human spot-checks are mandatory.
- **Short hashes exist upstream.** Eight candidate rows carry a short commit
  hash from `commits`/`file_change`; resolve them to full hashes before a
  release (the v0.2 freeze keeps them as-is; they are stable row ids).
- **Missing snapshots.** 50 diff-mined hunks still had no loadable parent/fix
  file after PR-URL and path normalization; 360 were deleted/renamed files.
  These are skipped, not silently treated as conversions.
- **Syntax gate is partial.** 82/90 fixed files parse with the bundled
  `syn 1.0.72` extractor; 8 fail, usually because the parser is older than the
  source or the file is macro/truncated. Do not treat a parse failure as proof
  that the source is invalid.
- **Reject rows are aggregate only.** The pilot writes rejection counts to
  `stats.json`; it does not persist one row per rejected block. Per-row reject
  records are a v0.2 requirement.

LLM adjudication uses [adjudication/RUBRIC.md](adjudication/RUBRIC.md). The
first queue was contaminated by generic `ptr::deref`/`as_ref` matches (31/60
vetoes); the strict queue uses only actual `unsafe` keywords/known unsafe APIs.
The adjudicated set is 607 rows: 104 Y / 166 M / 259 N / 78 U, with 76 vetoes
(367 CVEfixes + 194 crates.io + 45 RustSec + 1 Rust-for-Linux). Queue coverage
is 367/458 (80.1%). The reconciled positive union is 120 candidates across
110 families.

The reviewed negative core is 425 rows (259 N, 166 M), collapsing to 325
families. The 2026-11-07 gate-closing run added 331 rows: 161 CVEfixes queue
rows and 170 crates.io/RustSec families. One new Y claim was demoted to M on
spot-check. The old 84-row capped audit found 12 guards, 15 refactors, 1
different-unsafe row, and 0 hard negatives; the newer retained batches added
real N/M rows. The detector zero-shot run on 74 positives produced no sink for
31, a Y for only 18, and predicted Y on both known hard negatives.

Splits are keyed on canonical repository identity (`repo_identity.py`): 189
source-level names collapse to 154 repositories after 30 alias groups merge
(CVEfixes `owner_repo`, crates.io package, RustSec fix URL, and repository moves
such as `jgallagher/rusqlite` -> `rusqlite/rusqlite`). `check_split_leakage.py`
now reports 0 cross-split duplicate groups and 0 repo/commit/CVE overlap; the
old alias problem is gone. The frozen split is 216 train / 87 valid / 130 test
(49.9 / 20.1 / 30.0), with positives 54 / 22 / 33.

A smoke-test baseline (`baseline_tfidf.py`) trains on `old_snippet` only and
scores 0.759 accuracy, 0.400 F1(Y) and 0.665 AUC on `valid`, only 1.2 pp above
the 0.747 majority class. The first full training run (`train_model.py`) confirms
the gap: grouped CV 0.831 AUC, held-out valid 0.665; a pre-fix context window
around the hunk scores 0.388 on valid. Snippet text carries a shallow signal and
raw neighbouring code does not transfer, so the next model needs curated
API/contract features (and more positives) rather than a text window. The test
split is untouched and is reported only after freeze.

See the [pilot report](../../notes/research/transition-dataset-pilot.md) for the
counts, audit, examples, and decision.

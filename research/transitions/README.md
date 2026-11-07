# research/transitions — CVEfixes transition mining

> **Status: v0.2 draft · 2026-11-07 · all gates pass; not frozen**
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
cd /mnt/wd2023/home/dev2/Code/safeify2
python research/transitions/extract_candidates.py
python research/transitions/mine_diff.py
python research/transitions/mine_patterns.py
python research/transitions/build_manifest.py
python research/transitions/cap_negatives.py
python research/transitions/zero_shot_eval.py
python research/transitions/collect_hunks.py
python research/transitions/adjudication/make_queue.py --pilot 30 --name pilot_002
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
| `out/positive_union.jsonl` | 120 candidate positives / 110 families |
| `out/negative_core.jsonl` | 425 reviewed M/N rows (259 N, 166 M) |
| `out/transitions_core_draft.jsonl` | 231-row unfrozen core draft (118 Y / 57 M / 56 N) |
| `out/transitions_core_v0.2_draft.jsonl` | 435-row family-level v0.2 draft (110 Y / 194 N / 131 M) |
| `out/transitions_core_v0.2_quality.json` | gate report: all five gates pass; not frozen |
| `out/splits_v0.2.json` | family-core repo split (225/83/127) |
| `adjudication/gate_batches.json` | gate-closing run: 161 queue rows + 170 expansion families |
| `adjudication/labels_gate_*.jsonl` | 11 adjudication batch outputs (331 rows) |
| `out/spotcheck_gate.json` | documented spot-check correction (1 Y -> M) |
| `out/splits_draft.json` | repo-level 70/10/20 draft split |
| `out/stats.json`, `out/diff_stats.json`, `out/pattern_stats.json` | extractor counters and rejects |
| `out/manifest_stats.json` | merged distributions |

## Important caveats

- **Not a dataset yet.** The 90 safe rows include 2 duplicates, 7 false
  positives, 1 signature-only change, and 6 unclear rows. The 347
  unsafe-to-unsafe rows are mostly refactors/signature changes; 6 additional
  rows are conditional.
- **Hunk-level, not token-level.** A safe snippet is the added lines in the
  overlapping hunk; it is a semantic review of a diff pair, not a verified
  patch. LLM adjudication plus human spot-checks are mandatory.
- **Short hashes exist upstream.** Eight candidate rows carry a short commit
  hash from `commits`/`file_change`; resolve them to full hashes before a freeze.
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

See the [pilot report](../../notes/research/transition-dataset-pilot.md) for the
counts, audit, examples, and decision.

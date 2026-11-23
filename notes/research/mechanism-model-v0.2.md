# Mechanism model v0.2 — scaling with version-history transitions

> **Status:** second result · 2026-11-23 · 383 mined pairs from 62 crates · 240
> audited (153 Y) · train Y 84 → 185 (2.2×) · conditional top-1 0.455 → 0.636,
> family top-1 0.409 → 0.636 on the frozen 22 valid Y rows · abstention still weak.

Follows [mechanism-model-v0.1.md](mechanism-model-v0.1.md), which replaced the
binary replaceability target with the safe-remediation mechanism and hit the
84-train-Y label ceiling (conditional top-1 0.455, top-3 0.864). This round
scales the labels using crate version history, where a diff between two
published releases is an objective old→new pair: no CVE database, no maintainer
judgement, no LLM labels needed to *find* candidates — only to label a sample.

## 1. Mining (`mine_version_history.py`)

The 139 cached crates were re-mining targets: for each crate the newest 8
non-yanked versions were downloaded (cached tarballs, 6 parallel workers) and
consecutive versions diffed. A hunk is kept when the deleted code contains an
unsafe operation and the added code does not — the same `safe_candidate`
predicate as the CVEfixes pipeline.

| quantity | value |
|---|---:|
| crates processed | 139 |
| crates with rows | 62 |
| mined pairs | 383 |
| crates failed | 1 |

Volume is honest but modest: most consecutive releases do not remove `unsafe`,
and one crate (nalgebra, 50 rows) still contributes a large share. Every pair
is a real release-to-release transition, so no sampling artifact is involved in
*being* a transition.

## 2. Audit

`make_version_audit_queue.py` deduplicated against the existing corpus (383
mined → 330 new), capped 12 rows per package (→ 252) and sampled 240,
stratified by the rule labeller's guess so that mechanism classes stay covered.
Six batches were adjudicated under the same rubric plus the mechanism taxonomy.

| verdict | rows |
|---|---:|
| Y (safe replacement) | 153 |
| M (guard only) | 6 |
| N (unsafe retained) | 47 |
| U (unrelated) | 34 |

The Y mechanism mix is materially different from the CVE-fix corpus — this is
the point of new data:

| mechanism | new Y rows | v0.1 train Y |
|---|---:|---:|
| safe_wrapper | 51 | 17 |
| restructure | 37 | 13 |
| unnecessary | 23 | 7 |
| checked_api | 20 | 20 |
| slice_view | 10 | 1 |
| interior_mutability | 7 | 3 |
| init_memory | 4 | 16 |
| pin_api | 1 | 0 |

`merge_version_audit.py` rejects malformed labels; it also caught a real bug in
the shared "unsafe operation" regex: `\btransmute` matched the safe API
`transmute_bool_permissive`, so two Y rows were flagged. The regex now requires
a token boundary and is imported by every script that validates labels.

## 3. Why the rules are not the supervisor

`mechanism_rules.py` (ordered high-precision rules over the new snippet) was
built to label mined pairs automatically. Scored against the 139 audited
mechanisms it fires on 47 % of rows with 0.65 fine-class precision (0.71 at
family level), and it cannot recognise `safe_wrapper`, `ownership` or most
`checked`/`restructure` cases at all. That is a labelling function, not a
teacher: using it as supervision would mostly distil its own blind spots. It is
kept for stratification and as a baseline, and the weak labels stay out of
training.

## 4. Dataset

`build_mechanism_plus.py` adds the audited version transitions to the v0.3
mechanism dataset, dropping U rows and any row whose repository is already in
the frozen valid/test sets, so those splits remain exactly frozen:

| split | rows | Y rows |
|---|---:|---:|
| train | 596 | 185 |
| valid (frozen) | 87 | 22 |
| test (sealed) | 130 | 33 |
| **total** | **813** | **240** |

New repositories join train, the same rule as v0.3.

## 5. Results

Conditional on the 22 frozen valid Y rows (the mechanism-suggestion question):

| model | top-1 | top-3 | macro-F1 |
|---|---:|---:|---:|
| v0.1 conditional (84 train Y) | 0.455 | 0.864 | 0.338 |
| **v0.2 conditional (185 train Y)** | **0.636** | 0.864 | **0.438** |
| v0.2 family view | 0.636 | 0.909 | 0.407 |
| constant mechanism baseline | 0.455 | 0.500 | - |
| constant family baseline | 0.136 | 0.636 | - |

Top-1 is 14/22 (95 % CI 0.409-0.818) against a 0.455 constant baseline;
family top-3 0.909 against 0.636. The predicted distribution also moved toward
the valid mix (`safe_wrapper` 12, `init_memory` 5, `checked_api` 3,
`restructure` 1, `capacity_ops` 1) instead of collapsing on one class.

Joint task on the 87 valid rows (mechanism or retain):

| model | accuracy | macro-F1 | mechanism on M/N rows | retain on Y rows |
|---|---:|---:|---:|---:|
| char TF-IDF + LR | 0.598 | 0.203 | 18 | 14 |
| char TF-IDF + api + LR | 0.540 | 0.238 | 26 | 8 |

Abstention got worse, not better: with more Y rows the joint model is less
retain-biased and emits mechanisms on 26 of 65 M/N rows. Accuracy falls below
the majority baseline (0.747) for the first time. The joint task needs a
calibrated abstention rule or a two-stage design; it is not the same problem as
mechanism choice.

Within-source stability (repo-grouped 5-fold CV over the 101 version-history Y
rows, 34 packages): top-1 0.449 (folds 0.35-0.55), top-3 0.788. Mechanism
choice is genuinely hard at 10 classes; the frozen-valid number is higher
because those 22 rows are drawn from a narrower mechanism mix.

## 6. Verdict

Scaling real labels helped: 2.2× train Y bought +18 pp conditional top-1 at
unchanged top-3, and moved the model off the dominant-class guess. That is the
first positive scaling signal in this track — and it says the previous ceiling
was data, not architecture.

Two limits remain: 22 valid Y rows (CI ±0.2) and weak abstention. The next
steps are a second mining round (wider version windows, more crates about to
raise the label count to ~2-3×), then either an abstention calibration stage or
a pair-level ranker (old→candidate new), which is where the repair assistant's
suggestion quality ultimately lives.

## 7. Files and commands

```bash
cd safeify-data/transitions
python mine_version_history.py --versions 8 --jobs 6      # out/version_pairs.jsonl
python make_version_audit_queue.py --sample 240           # adjudication/version_audit/
# ... six audited batches ...
python merge_version_audit.py --write
python build_mechanism_plus.py                            # out/mechanism_dataset_plus.jsonl
python baseline_mechanism.py --dataset out/mechanism_dataset_plus.jsonl --tag v0.4-plus
python mechanism_rules.py                                 # rule labeler self-check
python score_mechanism_rules.py                           # rules vs audited mechanisms
```

Artifacts: `out/version_pairs.jsonl`, `adjudication/version_audit/`,
`out/mechanism_dataset_plus.jsonl` + stats, `out/baseline_mechanism_v0.4-plus.{json,md}`,
`out/mechanism_rules_score.json`. v0.1 artifacts and the frozen splits are
unchanged.

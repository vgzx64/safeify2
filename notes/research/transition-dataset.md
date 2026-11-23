# Unsafe-to-safe transition dataset — plan

> **Status: plan v1 · 2026-11-08 · `transitions-core` v0.2 FROZEN (433 rows); 8 gates pass; split leakage 0; binary label target verified by two blind spot-checks; no trained model yet**
>
> Scope: **classification and retrieval** for NIRM 4. Patch generation is
> intentionally delegated to an LLM downstream and is not trained here.
>
> This plan is not final until the pilot audit in §10 is complete. Do not cite
> it as a protocol before the freeze date.
>
> Pair-model first path: [bert-pair-model.md](bert-pair-model.md).

## 1. Decision

We will build one dataset with two tasks:

| Task | Input | Output | Why |
|---|---|---|---|
| **Classification** | unsafe region + function/file context | “is there a safe replacement” (binary; `Y` vs `M`/`N`), with `M`/`N` and `action` (`replace/guard/encapsulate/keep`) as descriptors | NIRM 4's required ML deliverable; the binary target is the only reproducible one |
| **Retrieval** | unsafe region | ranked candidate safe snippets | Supports the LLM patch stage without training a generator |

The LLM patch stage consumes the retrieved candidates and the classification
labels. It is not evaluated by 3-way accuracy and is not part of this dataset's
training target.

**Scope note.** The formal NIRM 4 text names classification with Gradient
Boosting / Random Forest. Retrieval is an extension. Keep the classifier as the
milestone deliverable; retrieval is an additional experiment.

## 2. What this dataset must fix

The current evidence base cannot support either task as-is:

- `rust_ecosystem` RQ4 has **114 candidate rows, all positive**, from **29
  CVEs**; 56/114 come from two CVEs. It has no curated negative class.
- The RQ4 label is function-level: "the containing function has no unsafe
  blocks after the fix." That is not proof that the block became safe.
- 36/80 extracted pair texts have no safe snippet; 2/80 "safe" snippets still
  contain `unsafe`.
- SafeNet's 97-file test split has already been reused across detector versions.
- The current detector abstains on ~83.8% of sinks (LSP, 2026-11-18 post-fix)
  and has `FP-on-N 0/27` with `recall_N 0.37`; it cannot be used as an automatic
  labeler.

The dataset therefore needs **block-level alignment, explicit negatives, and a
fresh holdout** before any model is trained.

## 3. Definitions

### 3.1 Unit

The primary unit is one **unsafe sink or unsafe region** in a vulnerable
snapshot, with:

- repository, CVE/advisory, fix commit, parent commit;
- file, function, span;
- API and pattern id where available;
- the unsafe snippet and its surrounding function context.

File-level counts are context, not labels.

### 3.2 Positive

A positive requires all of:

1. the old unsafe operation is removed or replaced in the same function;
2. the diff hunk overlaps the old span;
3. the safe snippet is non-empty and contains no `unsafe`;
4. the change is not only a rename, move, or formatting change;
5. an LLM adjudicator applies the rubric in §3.5 and returns a replacement
   verdict with quoted old/new evidence;
6. a human spot-check accepts the row (10–20% sample; 100% for the first 100
   positives).

Compilation, tests, and Miri are **not** label gates. They answer “does this
patch work?”, not “does a safe replacement exist?”. They are optional checks for
full-crate rows and for a small high-risk audit subset.

Function-level disappearance is a **candidate**, never a positive by itself.

### 3.3 Negative

Use two tiers:

| Tier | Definition | Label |
|---|---|---|
| **Hard negative** | Same API/pattern and repository; the fix touches the function but leaves unsafe code; manual review confirms no safe replacement in this frame | `N` or action `keep` |
| **Control** | Same API/pattern; the fix does not touch the function; no evidence either way | `U` / `unknown`, **not** `N` |

A block that was replaced by a *different* unsafe operation is
`different_unsafe`, not a safe positive and not an irreplaceable negative.

### 3.4 Labels

Keep three dimensions separate:

| Dimension | Values | Meaning |
|---|---|---|
| `replaceability` | `Y` | a reviewed safe replacement exists |
| | `M` | replacement exists but needs restructuring/preconditions |
| | `N` | no safe replacement in this frame |
| | `U` | insufficient evidence; do not train on it |
| `action` | `replace` | use the safe API/expression |
| | `guard` | add checks/contract and keep a narrower unsafe use |
| | `encapsulate` | keep unsafe inside a checked safe wrapper |
| | `keep` | no safe alternative; retain unsafe with justification |
| | `unknown` | unresolved |
| `scope` | `block` | exact region (preferred) |
| | `function` | whole-function evidence (weak) |
| | `file` | file-level count (weakest; not a label source) |

`encapsulateable` is an **action**, not a fourth replaceability class. A block
can be `N` for direct replacement and still have action `encapsulate`.

SafeNet's `Y/M/N` maps to `replaceability`; the action dimension is reviewed by
the same rubric.

### 3.5 Label adjudication

Labels are decided by an LLM reviewer with the
[adjudication rubric](../../safeify-data/transitions/adjudication/RUBRIC.md), not by
a compiler:

1. Quote the old unsafe operation and the proposed replacement.
2. State whether the replacement is semantically valid in this function.
3. Check preconditions/guards and whether `unsafe` remains.
4. Assign `replaceability`, `action`, and confidence (`high/medium/low`).
5. Return `U` when the diff context is insufficient; never guess `N`.
6. A human spot-check accepts/rejects a sample; disagreements are adjudicated
   again with the quoted evidence.

The LLM is a **labeling aid, not an oracle**. Store the rubric version, reviewer
prompt/model, confidence, and human decision. A row cannot enter
`transitions-core` on an unreviewed LLM label alone.

## 4. Sources and roles

| Source | Role | Allowed use | Not allowed |
|---|---|---|---|
| `rust_ecosystem` fix commits | Primary real transitions | candidate generation, positives, hard negatives | auto-label without audit |
| `rust_ecosystem` vulnerable snapshots | Context and controls | function/file context, control sampling | treating "untouched" as `N` |
| SafeNet `testdata` (474; 97 test) | External benchmark | final test only | training after freeze |
| SafeNet `knowledgebase` (142) | Retrieval gallery | safe/unsafe examples | query/test leakage |
| `safeify-data/synth` (333 distinct) | Pretraining/curriculum | train only | valid/test |
| RustSec / OSV / GHSA | Provenance and gap filling | advisory IDs, patched versions, missing commits | duplicate counting |
| crates.io / docs.rs / `rust-src` | API contracts and alternatives | gallery candidates, guard rules | automatic labels |
| rustc test suite / Miri / UCG | Optional verification | compile/Miri/UB cases for selected full-crate rows | replacement labels |
| LLM reviewer | Label adjudication | rubric-based `Y/M/N/action` + confidence | unreviewed gold |
| Rust-for-Linux, Tokio, Actix, Rayon | Encapsulation examples | `encapsulate` candidates | unverified training data |
| CVEfixes / Big-Vul / CrossVul | Comparison | coverage checks | assumed Rust relevance |

The `vul_safe_unsafe` table (332 rows) is a **candidate filter only**. It does
not identify which block changed. Collected source counts are in
[source_inventory.json](../../safeify-data/transitions/out/source_inventory.json).

**Collection has no date cutoff.** Use every available CVEfixes/RustSec/OSV/GHSA
and commit example, including 2026 and earlier. Dates are used only to define an
evaluation holdout, never to exclude training data.

## 5. Dataset tiers

| Tier | Content | Labels | Use |
|---|---|---|---|
| `transitions-wide` | all block-level candidates from the 350 CVEs with unsafe blocks | automatic, weak | pretraining, coverage analysis |
| `transitions-core` | stratified sample | LLM-adjudicated + human spot-check | supervised training, test |
| `transitions-external` | SafeNet test + a fresh RustSec/OSV holdout | gold benchmark | final test only |

`transitions-wide` must never be reported as a result. `transitions-core` is the
only tier that can support a headline number.

Materialize manifests with commit hashes, not copies of the 41 GB mirror. Raw
third-party source stays outside git; snippets are included only when the
license permits.

## 6. Schema

One JSONL row per transition:

```json
{
  "id": "rust_ecosystem:17:framed::next_item:252-254",
  "source": "rust_ecosystem",
  "repo_url": "https://github.com/actix/actix-net",
  "repo_name": "actix_actix-net",
  "cve_id": "17",
  "advisory_id": "RUSTSEC-...",
  "commit": "c41b5d8...",
  "parent_commit": "...",
  "file_before": "actix-codec/src/framed.rs",
  "file_after": "actix-codec/src/framed.rs",
  "fn_name": "framed::next_item",
  "api": "Pin::new_unchecked",
  "pattern_id": null,
  "span_before": [252, 254],
  "span_after": [248, 251],
  "unsafe_snippet": "...",
  "safe_snippet": "...",
  "transition": "replace",
  "replaceability": "Y",
  "action": "replace",
  "scope": "block",
  "evidence": {
    "diff_aligned": true,
    "llm_review": true,
    "llm_confidence": "high",
    "human_spot_check": true,
    "compile_optional": null,
    "miri_optional": null
  },
  "provenance": {
    "extractor": "transitions-v1",
    "analyzer": "unsafe_analysis_ra@...",
    "reviewer": "initials",
    "date": "2026-10-24"
  },
  "split": "train"
}
```

Required fields: `id`, `source`, `repo_url`, `commit`, `parent_commit`,
`file_before`, `fn_name`, `span_before`, `unsafe_snippet`, `transition`,
`replaceability`, `action`, `scope`, `evidence`, `provenance`, `split`.

`split` is `unassigned` until the freeze script assigns it. `pattern_id` is
`null` when the API is outside the SafeNet taxonomy; do not force an unrelated
API into a knowledge-base cell.

## 7. Splits

- Group by **repository + CVE + fix commit**; never split a group.
- Prefer a **time holdout** for the external test (recent advisories) in
  addition to repository grouping.
- `train`: `rust_ecosystem` train repos/CVEs + SafeNet train + synthetic.
- `valid`: held-out repos/CVEs; used for thresholds and model selection only.
- `test`: `transitions-core` holdout + SafeNet test + fresh external holdout.
- No normalized-AST duplicate across all sources, and no same function, same
  CVE, or same repository may cross splits.
- Synthetic rows appear only in `train`.
- Freeze `splits.json` and verify with a `--check` command before every run.

A 20% repo split of the current 29-CVE RQ4 set is about six CVEs. That is a
smoke test, not a benchmark. If the core set does not reach the gates in §11,
the external SafeNet/RustSec test is the only defensible test set.

## 8. Construction pipeline

1. **Candidate generation.** Join `commits`, `unsafe_block`, `unsafe_block_fix`,
   and `file_change`; require a fixed-version analysis output. Do not interpret
   a missing fixed analysis as "no unsafe".
2. **Diff alignment.** Align the vulnerable span to the diff hunk; reject rows
   whose hunk does not overlap the span.
3. **Source extraction.** Read the parent and fix snapshots; extract the
   function and the aligned old/new lines. Reject renames and moves.
4. **Label assignment.** Apply §3.2–§3.5. Default to `U`, never to `N`, when
   evidence is missing.
5. **Negative mining.** For each positive, sample 2–3 hard negatives from the
   same repository/API and 1 control. Match on function size and context.
6. **Label adjudication.** Run the LLM reviewer on the aligned pair; quote
   evidence, assign `Y/M/N` + action + confidence, and mark `U` when the context
   is insufficient. Compile/Miri only on optional full-crate checks.
7. **Deduplication.** Normalize AST/sequence; collapse duplicates; keep the
   best-provenance row.
8. **Manual audit.** Review every `transitions-core` row. Double-review 10% for
   agreement.
9. **Freeze.** Write `manifest.jsonl`, `stats.json`, `splits.json`, and hashes.

## 9. Quality gates

A row is admissible only if:

- `evidence.diff_aligned` is true and the hunk overlaps the sink;
- the LLM reviewer returns a label with quoted old/new evidence and confidence;
- `safe_snippet` is non-empty, differs from the unsafe snippet, and contains no
  `unsafe` (except an explicitly reviewed `encapsulate` case);
- the row is not a rename/move/format-only change;
- the fixed analysis actually exists for that repo/commit/function;
- a human spot-check accepts the row;
- provenance (commit, parent, extractor version, rubric, reviewer) is complete.

Rejected rows should stay in `rejects.jsonl` with a reason. The pilot currently
persists aggregate counts only; per-row rejects are a v0.2 requirement.

## 10. Pilot before freeze

The original pilot design was a one-day pass on **30 candidates** stratified across APIs and repositories:

- 10 from the RQ4 set;
- 10 from other `rust_ecosystem` CVEs;
- 10 hard negatives/controls.

Measure:

- yield of aligned, LLM-adjudicated positives;
- share of `replace` vs `guard` vs `encapsulate` vs `keep`;
- auto-label precision against manual review;
- time per reviewed row;
- repository/API coverage.

**Decision rule:** if fewer than 50% of candidates survive, or auto-label
precision is below 80%, revise the extractor before scaling. If the pilot
succeeds, freeze schema and split rules, then build v1.

### Pilot result (2026-10-24)

The pilot was executed against `CVEfixes.db` and the cloned repositories:

- 454 unique candidates: 90 safe rows, 6 conditional rows, 347 unsafe-to-unsafe
  rows, 11 removed.
- 74 of the 90 safe rows survived manual review as clear replacements.
- 32 CVEs, 27 repositories, 32 fix commits.
- 82/90 fixed files pass the bundled `syn` syntax gate.
- The 347 unsafe-to-unsafe rows and 6 conditional rows are not a curated
  negative class. A capped 28-row sample contains 12 guards, 15 refactors, 1
  different-unsafe row, and **0 hard negatives**.
- PR-URL normalization plus per-line diff validation recovered 470 file changes
  and raised the clear count from 38 to 74. These were existing CVEfixes rows,
  not new CVEs.
- The targeted pattern pass added only 5 new conditional rows and no new clear
  positives.
- Zero-shot on 74 positives: 31 produce no sink, only 18 have a Y; both known
  hard negatives are predicted Y.
- LLM adjudication now covers 607 rows: 367 CVEfixes, 194 crates.io, 45
  RustSec, 1 Rust-for-Linux; 104 `Y`, 166 `M`, 259 `N`, 78 `U`, 76 vetoed.
  The reconciled positive union is 120 rows / 110 families.
- The 2026-11-07 gate-closing run added 331 rows (161 CVEfixes queue rows +
  170 crates.io/RustSec families) and produced the v0.2 draft: 435 family rows,
  110 positives, 325 negatives, 130 test rows, queue coverage 367/458 (80.1%).

Verification then froze the artifact: two blind spot-checks plus a focused M/N
re-label changed two labels and dropped one row, and they showed that the
three-class Y/M/N target is not reproducible (M/N kappa 0.42-0.52) while the
binary Y-vs-not-Y target is (0.95 agreement, kappa 0.82 over 83 rows). The
frozen core therefore carries a binary `target` (`safe_replaceable`, Y = 1) and
keeps `M` only as a descriptor. Eight gates pass:

- 433 rows: 109 Y / 193 N / 131 M; 154 canonical repositories.
- Splits regenerated on canonical keys: 216 train / 87 valid / 130 test
  (positives 54 / 22 / 33); 0 cross-split duplicate groups, 0 repo/commit/CVE
  overlap.
- Queue coverage 367/458 = 80.1%; freeze manifest with sha256 in
  `out/manifest_v0.2.json`.

Supporting results:

- `repo_identity.py` resolves every row to `host/owner/repo` (repo URL, fix URL,
  current crates.io metadata, then historical `Cargo.toml`); the 189 source-level
  names collapse to 154 repositories, and `check_split_leakage.py` reports 0
  cross-split duplicate groups and 0 repo/commit/CVE overlap.
- A smoke-test baseline (`baseline_tfidf.py`, TF-IDF + logistic regression on
  `old_snippet` only) scores 0.759 accuracy / 0.400 F1(Y) / 0.665 AUC on
  `valid`, only 1.2 pp above the 0.747 majority class. Snippet text alone barely
  carries signal; the model needs API/contract context. The test split was not
  touched.
- `train_model.py` is the first supervised training harness (snippet vs
  pre-fix 60-line context, char TF-IDF + logistic regression). Grouped CV on
  `train` reaches 0.831 AUC, but held-out `valid` gets 0.665; the context window
  gets 0.388. No model transfers yet.
- Labels were verified by two independent blind spot-checks; the M/N boundary
  remains an explicitly non-trainable descriptor.
- `safeify-data/synth` remains the synthetic pretraining corpus; `experiments/gnn` is
  still an unwired prototype.

Full results: [transition dataset pilot](transition-dataset-pilot.md).

## 11. Capacity and stop conditions

| Gate | Threshold | If missed |
|---|---|---|
| Core positives | ≥100 | do not train; use as stress test |
| Core negatives | ≥300 | expand matched sampling before training |
| Repositories in core | ≥20 | report per-repo results only; no global claim |
| Test repositories | ≥5 | rely on external SafeNet/RustSec test |
| Auto-label precision | ≥80% | manual audit more; do not scale |
| Per-API support | ≥5 core rows | leave that API out of the headline |

A small, honest core set is more useful than a large noisy one.

## 12. Evaluation

### Classification

- per-class precision/recall/F1, macro-F1;
- `FP-on-N` (gold `N` predicted `Y`) as the safety-critical metric;
- coverage and risk–coverage curve;
- cluster bootstrap by repository/CVE, not by row;
- constant-`Y`, constant-`M`, and the current rule detector as baselines.

### Retrieval

- Recall@1, Recall@5, MRR;
- per-API and per-pattern breakdown;
- hard-negative false-positive rate;
- manual acceptance of the top candidate.

### Patch stage (downstream, LLM)

- compile rate;
- test pass rate;
- no new `unsafe`;
- Miri on small cases;
- manual acceptance.

Do not report a single accuracy number as the headline. The current 3-way
accuracy is below a constant-`Y` baseline, so accuracy alone is misleading.

## 13. Sequencing

| When | Work |
|---|---|
| 2026-10-24 | This plan |
| 2026-10-25–27 | 30-row pilot; estimate yield |
| 2026-10-28 | v0.1 exploratory: 109 positive families; negative/queue gates blocked |
| 2026-11-07 | Gate-closing run: +331 rows; v0.2 draft passes all five gates |
| 2026-11-07 | Canonical repo identity: leakage 0; splits 218/87/130; valid-split baseline run |
| 2026-11-07 | First training run: grouped CV 0.831 AUC, valid 0.665; raw context 0.388 |
| 2026-11-08 | Second + focused M/N spot-checks; 3 corrections; M/N shown non-reproducible; **v0.2 frozen** (433 rows, binary target) |
| 2026-10-29–11-08 | NIRM 3 report is the priority; do not start the full build |
| 2026-11-08 | Freeze `transitions-core` v0.2 |
| 2026-11-22 | v0.3 draft: 469 untouched rows audited (+243 usable, 30 Y); held-out AUC flat (0.624); no operating point reaches precision 0.7 → no fine-tune. See [transition-expansion-v0.3.md](transition-expansion-v0.3.md) |
| 2026-11-23 | Target reframed to safe-remediation mechanism: 139 Y rows labelled; conditional top-1 0.455 / top-3 0.864 (22 valid Y). See [mechanism-model-v0.1.md](mechanism-model-v0.1.md) |
| 2026-11-23 | Mechanism labels scaled with version-history mining (+240 audited pairs, train Y 84→185); conditional top-1 0.636, family 0.636. See [mechanism-model-v0.2.md](mechanism-model-v0.2.md) |
| 2026-11-23 | rust_ecosystem git mirrors mined (17,276 pairs, 569 repos); +200 audited (155 Y), train Y 314; fine top-1 saturates at ~0.6, family 0.682. See [mechanism-model-v0.3.md](mechanism-model-v0.3.md) |
| 2026-11-23 | Abstention stage: best suggestion precision 0.545 on valid, target 0.8; calibration cannot fix the snippet-only model. See [abstention-v0.1.md](abstention-v0.1.md) |
| 2026-11-23 | Pair-level ranker baseline: hard-negative AUC 0.97-0.99 but the signal is six numeric features; near-miss ranking at chance (0.611). See [pair-ranker-v0.1.md](pair-ranker-v0.1.md) |
| 2026-11-23 | Classifier view: binary AUC 0.655, family macro-F1 0.322; labels reproducible (blind κ 0.96 / 0.80) so the fix-vs-warning gap is the issue. See [classification-v0.1.md](classification-v0.1.md) |
| 2026-11-23 | Hazard taxonomy (12 classes) + classifier: 0.684 acc / 0.519 macro F1 vs human valid labels; rules vs human κ 0.765. See [hazard-classifier-v0.1.md](hazard-classifier-v0.1.md) |
| 2026-11-23 | Human-supervised hazard classifier: 300 blind train labels, 0.696 acc / 0.550 macro F1 on human valid. See [hazard-classifier-v0.1.md](hazard-classifier-v0.1.md#human-supervised-run) |
| Pair model (not NIRM 4) | Train the SafeNet-style pair classifier on `safeify-data/synth/out/train_mixed.csv` (8,580 clean pairs after the 2026-11-18 rebuild; `splits/check_train_leakage.py` must pass); evaluate on the frozen core as external validation. First path: frozen-BERT cache + pair head, see [bert-pair-model.md](bert-pair-model.md) |

The dataset build must not delay the NIRM 3 report. The pilot is enough to
validate the plan; the full build belongs to NIRM 4.

## 14. Open decisions

1. **`encapsulate` as action, not class** — recommended; confirm the label
   rubric with the supervisor.
2. **Minimum core size** — proposed 100 positives / 300 negatives; confirm
   against available time.
3. **Holdout strategy** — repository + CVE + recent time; confirm whether the
   external RustSec holdout is available.
4. **Raw-source storage** — manifest only, or licensed snippets in-repo;
   confirm the policy before extraction.
5. **Double-review** — 10% of core rows; confirm who reviews.

## 15. Related documents

- [NIRM 3 status](../nirm3/README.md)
- [NIRM 3 results and protocol](../nirm3/results.md)
- [Synthetic data theory](synthetic-data-theory.md)
- [Research vectors](research-vectors.md)
- [Synthetic pipeline](../../safeify-data/synth/README.md)
- [Frozen SafeNet split](../../safeify-data/synth/splits/README.md)
- [Transition pipeline](../../safeify-data/transitions/README.md)
- [safeify-ai limitations](../../safeify-ai/README.md)
- [Pilot results](transition-dataset-pilot.md)
- [Detector limitations](../../safeify-lint/README.md)
- [SafeNet corpus](../../vendors/SafeNet/README.md)
- [Dissertation plan](../../papers/my_dissertation_plan.md)

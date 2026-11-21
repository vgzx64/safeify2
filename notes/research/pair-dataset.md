# The Safeify pair-classification dataset

> **Status: active · 2026-11-21 · no model trained**
>
> Scope: the dataset used to train and evaluate the NIRM 4 **pair classifier**
> — the binary model that decides whether two Rust snippets instantiate the
> same unsafe-API pattern, and (through its pattern labels) whether the unsafe
> side has a known safe replacement. It is *not* the real-crate corpus used to
> evaluate `safeify-lint` (see
> [counterexamples.md](counterexamples.md)) and *not* the CVE-derived
> transition corpus (see [transition-dataset.md](transition-dataset.md)).
>
> Canonical sources: [safeify-data/synth/README.md](../../safeify-data/synth/README.md)
> (construction), [splits/README.md](../../safeify-data/synth/splits/README.md)
> (freeze and evaluation protocol),
> [bert-pair-model.md](bert-pair-model.md) (model plan). All counts below are
> verified against the committed artifacts on 2026-11-21; the reproduction
> commands are given in §4.

## 1. Sources

The dataset combines one real query corpus, one curated knowledge base and a
deterministic synthesis pipeline. The real corpora come from the SafeNet
benchmark vendored under `vendors/SafeNet`; the synthetic corpus is generated
locally from the same knowledge-base taxonomy. No data outside that benchmark
are used, and no language model is used. Snippets are represented as preorder
AST token sequences (the baseline's input format), never as raw source in the
training CSVs.

| # | source | role | raw size | usable |
|---|---|---|---:|---:|
| S1 | `vendors/SafeNet/testdata/` (GitHub) | real **queries**, held-out | 474 `.rs`, 18 APIs, 76 (api, pattern) cells | 454 |
| S2 | `vendors/SafeNet/knowledgebase/` | fixed retrieval gallery, gold verdicts, real training rows | 142 `.rs`, 18 APIs | 141 |
| S3a | counterfactual injection (5 safe seeds) | synthetic **safe→unsafe** pairs | 174 candidate snippets | 57 kept |
| S3b | rule templates (42 rule cells) | synthetic unsafe / safe / encapsulated variants | 2,250 candidate snippets | 276 kept |
| S4 | SafeNet shipped `train.csv` | format reference only | — | not used |

**S1 — GitHub queries.** The 474 files are hand-curated unsafe-Rust examples
organised as `testdata/<api>/<pattern>-<k>[-safe].rs`; the API directory and the
numeric filename prefix supply the gold `(api, pattern_id)` cell, and a
`-safe` suffix marks the safe counterpart. Eighteen APIs are represented
(`Box::from_raw`, `ptr::copy`, `ptr::copy_nonoverlapping`, `ptr::read`,
`ptr::write`, `ptr::write_bytes`, `ptr::deref`, `offset_from`, `mem::transmute`,
`mem::transmute_copy`, `mem::zeroed`, `assume_init`, `as_ref`, `set_len`,
`Rc::from_raw`, `CStr::from_ptr`, `CString::from_raw`,
`Vec::from_raw_parts`), spanning 76 cells. These are the only *queries* that are
ever evaluated.

**S2 — Knowledge base.** The 142 knowledge-base files document the same 18
APIs with prose contracts and the benchmark's Y/M/N replaceability verdicts
(Y = replaceable, M = conditional, N = irreplaceable). The knowledge base is
never a query: it is the fixed retrieval gallery (141 usable entries) and the
source of the per-cell gold verdicts, transcribed verbatim into
`splits/kb_verdicts.json`; 15 knowledge-base cells have no counterpart in
`testdata/` (e.g. `Box::from_raw/p6`, `mem::transmute/p4`, `ptr::read/p3`).
Five of these also have synthetic rules, while the other ten appear only in
the gallery. The knowledge base also contributes real training snippets.

**S3 — deterministic synthesis.** Two strategies implement the "ground truth by
construction" principle of
[synthetic-data-theory.md](synthetic-data-theory.md). Strategy A starts from
five safe seed programs (`cast_transmute`, `bytes_transmute`,
`slice_unchecked`, `rc_roundtrip`, `zeroed_init`) and applies the known inverse
of a safe idiom — `as` → `transmute`, `from_le_bytes` → `transmute`,
bounds-checked indexing → `get_unchecked`, `clone` → `into_raw`/`from_raw`,
literal/`Default` → `zeroed` — emitting the unmodified safe render as the
label-1 counterpart. Strategy B renders 42 YAML rule files, one per
`(api, pattern_id)` cell, each pinning the knowledge-base replaceability and
contract and carrying a parameter grid plus `unsafe`, `safe` (for Y cells) and,
where defined, `encap` templates (the unsafe operation wrapped in a checked
`pub unsafe fn` with `assert!` and a `SAFETY` comment). Every record is emitted
in three structural contexts — plain, inside `mod synth_m1 {…}`, and inside
`mod synth_m1 { mod synth_m2 {…} }` — because identifier- and type-only
variation is normalised away by the baseline representation, so module nesting
is the only augmentation axis that produces genuinely distinct sequences.
Before filtering, S3 yields 2,424 candidate snippets (2,250 template, 174
injection).

## 2. Transformations, filters and checks

The pipeline is deterministic and CPU-local: the same inputs, seed and tool
versions produce byte-identical artifacts.

### 2.1 Representation (applies to S1, S2, S3)

Every snippet is parsed with `syn 1.0.72` (`{:#?}` dump), converted to the
baseline AST form by a port of SafeNet's `simplifyast.py` and `addnumtree.py`,
and serialised as a whitespace-separated preorder token sequence (`varN` for
identifiers and type names, `*_token` for punctuation/keywords). The port
reproduces the shipped conventions, including the literal preservation of known
identifiers (`mem`, `transmute`, `NonNull`) and the baseline's prefix-collision
quirk. As a fidelity check, 583 of the 595 processed real snippets (98.0 %)
contain at least one verbatim 8-token window of their computed sequence in the
shipped `train.csv`; the residual gap is attributable to script revisions and
post-export source edits, and is documented rather than repaired.

### 2.2 Filters per source

* **S1.** A file is *usable* only if it has a numeric pattern id in its
  filename **and** survives the extraction chain into a non-empty token
  sequence. Of 474 files, 454 are usable; the 20 exclusions are one
  pattern-less file (`Rc::from_raw/pending.rs`) and 19 pre-existing parse
  failures (lex errors and truncations, e.g.
  `ptr::write_bytes/2-1.rs`, `set_len/1-5.rs`). The failures are skipped, never
  repaired, and are itemised in `splits/stats.json`.
* **S2.** 142 knowledge-base files yield 141 usable sequences; the remaining
  file (`CStr::from_ptr/1-funparraw-unsafe.rs`) has no obtainable token
  sequence and is excluded from the gallery.
* **S3.** Each candidate must pass a `rustc --edition 2021 --crate-type lib
  --emit=metadata` compile (2,424/2,424 pass), the AST extraction and
  preprocessing steps, and exact-sequence deduplication within its
  `(api, kind)` cell. A compile-broken file can never reserve a sequence slot.
  Deduplication removes 2,091 of the 2,424 candidates (86.2 %), because grids
  that vary only type or identifier names collapse to the same normalised
  sequence; 333 snippets remain (276 template, 57 injection). All 2,424
  attempts remain in the provenance manifest with `ok`/`dropped` flags and
  per-snippet verification records (`compile` true; `miri`, `tests` and
  `clippy` deliberately null).

### 2.3 Labels

No per-file labels are assigned by hand. The `(api, pattern_id)` cell is read
from the source filename (S1) or rule file (S3), and the Y/M/N replaceability
verdict is transcribed from the knowledge-base README (S2). A pair is labelled
**+1 iff both snippets carry the same `(api, pattern_id)` cell**, and −1
otherwise; this is the shipped `converttrainset.py` semantics extended with the
API, because the same pattern number means different things in different APIs.
Encapsulated variants are labelled `encapsulatable` (a replaceability class
distinct from Y/M/N): the unsafe operation is kept but wrapped in a checked
safe API. The 14 duplicate groups whose identical sequence carries conflicting
gold pattern ids (a known corpus defect, e.g. `ptr::copy/4-13.rs` versus
`ptr::copy/1-2(4-14).rs`) are itemised in `stats.json` and kept within one
split so that no conflicting label crosses the held-out boundary.

### 2.4 The frozen split

The 454 usable query snippets are partitioned 70/10/20 **per
`(api, pattern_id)` stratum**, with a per-file stable seed (1234, no global RNG
state) so the assignment is byte-identical across runs and machines; duplicate
groups are kept atomic. This gives 288 training, 69 validation and 97 test
files. The membership lists, per-file sequence hashes and the stratum table are
committed, and `python splits/make_splits.py --check` verifies the freeze. The
leakage audit finds **0 same-API sequence overlaps** between splits; six
cross-API identical sequences and the 14 label-conflict groups are recorded as
informational (the six are additionally removed from the training rows in
§2.5), with the same-API audit being the one that matters for generalisation.

| split | files | replaceable (Y) | conditional (M) | irreplaceable (N) | cells |
|---|---:|---:|---:|---:|---:|
| train | 288 | 188 | 23 | 77 | 76 |
| valid | 69 | 44 | 6 | 19 | 64 |
| test | 97 | 65 | 9 | 23 | 68 |

The frozen files are evaluation-only: they are never paired into the training
CSVs.

### 2.5 Pair assembly

Training pairs are generated in four variants from the *training* rows only:

* `train_synth.csv` — within-API pairs among synthetic rows (333 rows).
* `train_real.csv` — within-API pairs among real rows: the 141 knowledge-base
  snippets plus the 282 usable GitHub training snippets (**423 rows**; the 288
  training files lose six whose normalised sequence also occurs in valid or
  test, dropped at the sequence level).
* `train_mixed.csv` — within-API pairs over the union (423 + 333 = 756 rows).
* `train_hard.csv` — cross-API negatives only: 500 same-pattern-id pairs
  (adversarial, because the pattern number matches across APIs) and 500 random
  cross-API pairs, at least one side synthetic; all label −1.

Within-API pairs are enumerated exhaustively, labelled by cell identity, then
**balanced 50/50** by keeping `min(#positive, #negative)` pairs per file and
shuffling with seed 1234; the format is byte-compatible with the shipped
`train.csv` (the `,text1,text2,label` header, sentence-pair columns). The resulting
files contain 2,628 (1,314/1,314), 2,688 (1,344/1,344), 8,580 (4,290/4,290) and
1,000 (0/1,000) pairs respectively. Contamination is checked twice: an
in-memory assertion before writing and an independent re-check of the written
CSVs, both reporting **0/69 valid and 0/97 test snippets in every file**.
The shipped SafeNet `train.csv` is not used for training at all, because it
contains 25 test and 23 validation snippets.

### 2.6 Evaluation sets

Two protocols score the frozen queries. The shipped small sets pair held-out
snippets with each other only: 10 validation pairs (5 positive / 5 negative)
and 76 test pairs (38/38); the test set contains no both-N *negatives* (its
three both-N pairs are gold positives). The enlarged sets
(`splits/make_eval_full.py`) add, for each query, pairs against the fixed
training-side gallery (the retrieval deployment task) as well as within-split
query pairs:

| stratum | test | valid |
|---|---:|---:|
| POS-QG — query × gallery, same cell | 174 | 118 |
| POS-QQ — query × query, same cell | 38 | 5 |
| NEG-HARD-QG — query × gallery, same API, different pattern | 581 | 405 |
| NEG-HARD-QQ — query × query, same API, different pattern | 199 | 104 |
| NEG-XAPI-QG — query × gallery, different API (3 per query) | 291 | 207 |
| **total** | **1,283** | **839** |

The test set has 212 positives and 1,071 negatives (16.5 % positive), 44 both-N
negatives and 140 recommend-on-irreplaceable pairs (N query × Y/M gallery, same
API); the validation set has 123/716 (14.7 % positive), 34 both-N negatives and
111 recommend-on-irreplaceable pairs. Only 5 of the 123 validation positives
are held-out (QQ) pairs, so the validation set selects the retrieval threshold
while grouped cross-validation on `train` remains the held-out tuning signal;
the test set supplies 38 held-out positives and is scored once per model. All
pair files are deterministic and hash-pinned: each pair manifest records the
CSV's SHA-256, a mismatch is rejected by the scorer, and
`make_eval_full.py --check` rebuilds the four artifacts byte-for-byte. Metrics
exclude the 8 test and 6 validation pairs whose two texts are identical
(known corpus label conflicts).

## 3. What the dataset contains in the end

The committed dataset consists of 595 processed real snippets (141 gallery +
454 queries), 333 distinct synthetic snippets surviving deduplication from
2,424 candidates, and the derived pair sets. Training artifacts live under
`safeify-data/synth/out/`; the frozen split and evaluation artifacts live under
`safeify-data/synth/splits/`.

| artifact | contents | size |
|---|---|---:|
| real snippets | SafeNet knowledge base + GitHub queries, token sequences | 595 |
| query split | frozen train / valid / test membership | 288 / 69 / 97 |
| retrieval gallery | fixed knowledge-base entries, 18 APIs | 141 |
| synthetic snippets | 276 template + 57 injection (177 unsafe, 105 safe, 51 encap) | 333 |
| `train_synth.csv` | synthetic within-API pairs | 2,628 |
| `train_real.csv` | real within-API pairs (KB + train-split GitHub) | 2,688 |
| `train_mixed.csv` | real + synthetic within-API pairs | 8,580 |
| `train_hard.csv` | cross-API negatives (500 hard + 500 easy) | 1,000 |
| small eval pairs | valid / test | 10 / 76 |
| enlarged eval pairs | valid / test | 839 / 1,283 |
| provenance | per-snippet manifest, per-pair manifests, split statistics | — |

Label composition of the kept synthetic snippets is 207 replaceable, 27
conditional, 48 irreplaceable and 51 encapsulatable. The full dataset is
deterministic, leakage-gated (0/69 validation, 0/97 test), format-identical to
the baseline's training CSV, and traceable to individual rule cells and source
files through `out/pairs_manifest.jsonl` and the evaluation manifests. Its known
defects are the 20 unusable GitHub files (19 parse failures and one
pattern-less file), one unusable knowledge-base file,
14 label-conflict duplicate groups, six cross-API duplicate sequences that are
removed from training, and 15 knowledge-base-only cells; the identifier/type
normalisation also caps how much variation synthetic grids can contribute. No
MIRI run is recorded, so injected code is compile-safe but not UB-proven, and
`slice::from_raw_parts` is excluded because it has no knowledge-base entry.

## 4. Reproduction

```bash
cd safeify-data/synth
python build.py                              # generate -> verify -> pair -> report
python splits/make_splits.py --check         # freeze unchanged (3x OK)
python splits/make_eval_full.py --check      # enlarged pairs reproduce byte-identically
python splits/check_train_leakage.py         # 0/69 and 0/97 in all four CSVs
python splits/eval_protocol.py               # audit: sizes, leakage, verdict coverage
```

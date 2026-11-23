# Mechanism model v0.3 — rust_ecosystem as the scale source

> **Status:** third result · 2026-11-23 · rust_ecosystem git mirrors mined
> (17,276 pairs / 569 repos) · 220 audited (166 Y) · train Y 84 → 318 (3.8×) ·
> conditional top-1 0.591, top-3 0.864, family top-1 0.682 · fine-grained top-1
> saturated after ~185 Y; abstention is now the blocker.

Follows [mechanism-model-v0.2.md](mechanism-model-v0.2.md). The label budget was
the ceiling; this round asks whether the existing rust_ecosystem corpus can lift
it, and what it is actually good for.

## 1. What rust_ecosystem contributes

The mounted study directory (`/mnt/tc2015_p5/Code/rust_ecosystem`, read-only)
contains five usable assets. Only one is a label/scale source; the others are
structural:

| asset | content | use for this track |
|---|---|---|
| `repos_mirror/` (41 GB, 811 bare git repos) | full commit history of the vulnerable repositories | **the scale engine**: every commit is an objective old→new transition, no CVE dependency, no network |
| `CVEfixes.db` (2.7 GB) | advisories, fix commits, `file_change` diffs, `unsafe_block`/`unsafe_block_fix` **spans only** | already the source of the v0.2/v0.3 corpus; block tables carry no text, so they add locations, not labels |
| `compiler_result_v3/` (1.2 GB) | compiler-plugin output: functions, blocks, unsafe traits/impls with spans per vulnerable/fixed version | structural features later (block inside `unsafe fn`, function boundaries); no verdicts |
| `repos_worktree/` (5.2 GB) | checked-out source trees at the studied versions | context windows and patch verification later; no labels |
| `fix_pattern_analysis_by_type.csv`, `RQ/` | aggregate fix-pattern statistics by vulnerability category | thesis context: fixes *add* unsafe blocks far more often than they remove them (e.g. Resource Management: 97.6 % of blocks added), which explains the low yield of CVE-only mining |

So the honest answer: the vulnerability study is not a source of mechanism
labels, but its **git mirrors are the best scale source available offline**,
and its aggregate tables are useful for framing the dataset's rarity.

## 2. Mining the mirrors (`mine_git_history.py`)

For each bare repository: `git log -p --no-merges -Gunsafe -- '*.rs'`, parsed as
a stream, keeping hunks where the deleted code has an unsafe operation and the
added code does not. Streaming with a 90 s per-repository budget fixed an early
hang (a single huge history produced gigabytes of diff and stalled the run);
the run is resumable by repository.

| quantity | value |
|---|---:|
| repositories with rows | 569 |
| mined pairs | 17,276 |
| unique new after dedupe vs corpus/version pairs | 13,298 |
| rows after 4-per-repository cap | 1,641 |
| sampled and audited | 220 |

Four 40-row batches and three 20-row batches completed; three subagent batches
were killed mid-run, so 220 of the 240 sampled rows were audited. That is enough
for this scale point.

Audit verdicts: **166 Y / 0 M / 23 N / 31 U**. The zero-M result is expected:
commit-to-commit hunks that remove unsafe rarely add a guard instead.

## 3. Dataset

`build_mechanism_plus.py --audit version,git,git_small` adds the audited rows to
the frozen base, dropping U rows, rows from repositories already in the frozen
valid/test sets, and duplicates:

| split | rows | Y rows |
|---|---:|---:|
| train | 745 | 318 |
| valid (frozen) | 87 | 22 |
| test (sealed) | 130 | 33 |
| **total** | **962** | **373** |

Train Y growth: 84 (v0.1) → 185 (v0.2) → 318 (v0.3).

## 4. Results

Conditional on the 22 frozen valid Y rows:

| model | top-1 | top-3 | macro-F1 | family top-1 | family top-3 |
|---|---:|---:|---:|---:|---:|
| v0.1 (84 train Y) | 0.455 | 0.864 | 0.338 | 0.409 | - |
| v0.2 (185 train Y) | 0.636 | 0.864 | 0.438 | 0.636 | 0.909 |
| **v0.3 (318 train Y)** | 0.591 | 0.864 | 0.480 | **0.682** | **0.955** |
| constant baseline | 0.455 | 0.500 | - | 0.136 | 0.636 |

Fine-grained top-1 moved 0.455 → 0.636 between the first two scale points and
then stopped (0.591 is one flipped row on n = 22). Top-3 is flat at 0.864.
Macro-F1 and the family view kept improving: 0.480 and 0.682/0.955, against
constant baselines of 0.455 and 0.136/0.636.

Within-source stability, repository-grouped 5-fold CV:

| source | Y rows | repos | top-1 | top-3 |
|---|---:|---:|---:|---:|
| crate version pairs | 101 | 34 | 0.449 | 0.788 |
| git commits | 133 | 101 | 0.482 | 0.755 |

So on real commit data the mechanism is learnable to roughly 0.45-0.48 top-1
and 0.76-0.79 top-3 across held-out repositories.

Joint task (mechanism or retain) on the 87 valid rows:

| model | accuracy | macro-F1 | mechanism on M/N rows | retain on Y rows |
|---|---:|---:|---:|---:|
| char TF-IDF + LR | 0.391 | 0.169 | 37 | 9 |
| char TF-IDF + api + LR | 0.368 | 0.261 | 47 | 3 |

Abstention degraded further with more mechanism examples: the joint model now
suggests a mechanism for 47 of 65 M/N rows. It is not a usable gate; only the
conditional ranker is.

## 5. Verdict

Three scale points on the same frozen test set give a clear curve: the label
budget was the binding constraint up to ~185 train Y, and beyond that the
snippet-only representation saturates at roughly 0.6 fine top-1, while family
accuracy keeps improving. This is the evidence needed to stop scaling the same
recipe and switch the problem shape.

What this means for the thesis: the mechanism label is real, learnable, and
best reported at family level with a top-3 suggestion; the binary "is there a
safe replacement" question remains out of reach from the snippet alone.

Next levers, ranked:

1. **Abstention stage** — a separate fitted gate or class-threshold rule on the
   joint model; without it the tool cannot be silent, and silence is the
   behaviour that makes a suggestion acceptable.
2. **Pair-level ranker** — given `old` and a candidate `new`, score validity.
   Objective labels come from the same mirrors (real transitions as positives;
   mismatched pairs as negatives) and it is the actual assistant component.
3. **Structural features** — use `compiler_result_v3` spans (block inside
   `unsafe fn`, function boundaries) and `repos_worktree` context; test whether
   the saturation is representation, not concept.

## 6. Files and commands

```bash
cd safeify-data/transitions
python mine_git_history.py --max-rows 200 --max-commits 2000   # out/git_history_pairs.jsonl (not committed, 31 MB)
python make_git_audit_queue.py --sample 240 --rows-per-batch 40
python make_git_audit_queue.py --sample 160 --rows-per-batch 20 \
       --dest adjudication/git_audit_small --seed 13
# ... audit batches ...
python merge_git_audit.py --allow-partial --dir adjudication/git_audit --write
python merge_git_audit.py --allow-partial --dir adjudication/git_audit_small --write
python build_mechanism_plus.py \
  --audit adjudication/version_audit/labeled.jsonl,adjudication/git_audit/labeled.jsonl,adjudication/git_audit_small/labeled.jsonl \
  --out out/mechanism_dataset_v05.jsonl --stats out/mechanism_dataset_v05_stats.json
python baseline_mechanism.py --dataset out/mechanism_dataset_v05.jsonl --tag v0.5
```

The mined pool (`out/git_history_pairs.jsonl`) is git-ignored: it is 31 MB and
regenerable from the mirrors with the committed script. The audited rows,
dataset, and results are committed.

# Transition dataset — source expansion plan

> **Status: active plan · 2026-10-26**
>
> Existing v0.1 exploratory core: [pilot results](transition-dataset-pilot.md).
> This page defines the new sources and what must be reworked. It is deliberately
> short; detailed counts live in the pilot/QA artifacts.

## Rework answer

No full rework of the extraction or labels. Keep:

- CVEfixes strict hunk mining and adjudication.
- RustSec PR/commit/issue mining.
- The 276 reviewed labels and the v0.1 exploratory family core.
- The LLM rubric.

What must be reworked:

1. **Source tags and dedupe.** New sources need `source`, `advisory_id`,
   `crate`, `version_before/after`, `docs_url`, `commit`/`patch_url` fields.
2. **Assembly, not raw mining.** New rows must be deduped against existing
   `(repo, path, function, old_text)` families before counting.
3. **Splits and gates.** Splits must be regenerated with new repositories and
   the manual/LLM tracks must be reconciled before any freeze.
4. **Unit separation.** Official docs contracts and Rust-for-Linux encapsulation
   examples are not automatically new `Y` transitions. They need their own
   `unit`/`action` labels.

## Sources and roles

| Source | Role | Expected contribution |
|---|---|---|
| CVEfixes + RustSec/OSV/GHSA | CVE transition pairs | existing 119 rows / 109 families |
| **crates.io version pairs** | vulnerable→patched published versions | **new Y/M families** |
| **official Rust docs / rust-src** | `# Safety` contracts, canonical safe alternatives | `N`/`encapsulate` candidates, retrieval gallery, guard rules |
| **Rust-for-Linux `rust/kernel`** | safe wrappers around unsafe kernel/FFI code | `encapsulate`/`M` examples; not CVE positives |
| SafeNet | external benchmark | evaluation only, not training |

OSV/GHSA is treated as already covered by CVEfixes/RustSec aliases. Do not
duplicate it unless a separate artifact is supplied.

## crates.io version pairs

Do **not** search commits. Use advisory version ranges:

```text
last affected version → first patched version
```

Pipeline:

1. Parse RustSec/OSV/GHSA `patched` ranges.
2. Download immutable `.crate` tarballs from crates.io.
3. Extract and run the strict unsafe inventory on both versions.
4. Diff only files/functions whose unsafe footprint changed.
5. Require an aligned old/new operation and LLM-adjudicate it.
6. Record crate, versions, advisory, file, function, old/new text, confidence.

Commits are optional provenance only. Tags are not reliable enough to be the
primary key.

## Official Rust docs

Sources: extracted `rust-src` (`library/core`, `library/std`, `library/alloc`)
and official std docs. Mine:

- `# Safety` sections → caller obligations, `N`/`encapsulate` candidates.
- Doc examples/doctests → canonical safe alternatives.
- `SAFETY:` comments in std source → guard/contract language.

This is **contract/alternative data**, not a transition pair by itself. Do not
count a doc example as a new `Y` family unless there is an actual old/new code
pair with the same operation.

## Rust-for-Linux

The upstream Linux kernel's Rust support (`rust/kernel/`). Encapsulation patches
add a safe public API around an unsafe kernel/C/FFI operation, with `# Safety`
docs and internal `unsafe`. They are `encapsulate`/`M` examples, not CVE fixes.
Mine Linux history/patch series filtered to `rust/`, not the whole kernel.

## Pilot results (2026-10-26)

### crates.io

- 200 advisories with simple `patched` ranges were paired.
- 872 unsafe-changing hunks; 191 safe candidates.
- 54 adjudications: 23 `Y`, 5 `M`, 3 `N`, 23 `U`/veto.
- crates.io added the families that pushed the union past 100; the current
  reconciled union is **119 rows / 109 families**. Many version pairs still
  contain no unsafe change.

The first implementation had a path bug (tarball root included
`<crate>-<version>`), which produced zero rows. Fixing relative paths made the
miner work. The current pilot is reproducible via `mine_cratesio.py`.

### Official Rust docs

`rust-src` 1.99.1 mining produced:

- **897** `# Safety` sections (including internal/vendor code);
- **310** public `pub` safety contracts after filtering vendor/sys;
- **469** doc code examples containing unsafe/related APIs.

These are contract/alternative data, not transition pairs. They are not yet
merged into the core.

### Rust-for-Linux

A pilot adapter was added (`mine_rust_for_linux.py`). Eight Linux `rust/`
abstraction commits produced 3 unsafe-changing hunks: 2 unsafe-added and 1
retained. No safe-candidate row appeared. It remains an `encapsulate` source,
not a CVE-positive source.

## Next phases

1. Finish the retained queue toward 300 negatives.
2. Rebuild a source-stratified split with adequate train/valid/test.
3. Adjudicate more of the 310 public doc contracts and 469 examples.
4. Freeze only after all quality gates pass.

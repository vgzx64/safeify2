# НИРМ 3 — Phase 1 first approbation run (2026-10-19)

> **ARCHIVED — historical only.** Superseded by
> [notes/nirm3/results.md](../../nirm3/results.md). The v1 numbers below are
> retained for provenance and must not be cited as current results.

> **SUPERSEDED:** final numbers after Phase-2 bug fixes are in
> `notes/nirm3_phase2_analysis.md` (lsp v3: accuracy 0.162, FP-on-N 0/27,
> recall_N 0.296). This file is kept as the v1 baseline record.

Environment repaired + first full scoring of the detector on the frozen
97-file test split. Raw outputs: `/tmp/nirm3_lsp.json`, `/tmp/nirm3_no_lsp.json`,
`/tmp/nirm3_score.txt` (tmp — re-runnable via commands below).

## Env fixes made (Phase 0)

1. `~/.local/bin/rust-analyzer` was a broken symlink (`/home/developer` gone).
   Installed official component: `rustup component add rust-analyzer` →
   `rust-analyzer 1.99.1 (58cf8f9 2026-10-13)`, matching `rustc 1.99.1`.
2. `.venv` was broken (target `python3.14` removed). Rebuilt for python 3.13.5
   with `uv` (+ pyyaml 6.0.3, pandas 3.0.6). `test_detect.py 7/7` after rebuild.
3. `detect/setup_rust_src.sh` bugs fixed:
   - version parsed from `rustc --print sysroot | sed 's/.*-//'` → `gnu` under
     rustup; now `rustc --version | awk '{print $2}'`.
   - `curl -sO` → `curl -fsSL -o` (redirects).
   - sysroot farm rebuilt for 1.99.1; stale rust-src-1.97.1 removed.
4. **`ra_client.open_file` bug (major):** `find_project_root()` found
   `vendors/SafeNet/Cargo.toml` above testdata files, so each file opened the
   whole SafeNet crate (~60 s/file, and doc not a crate target → hover null).
   Fix: honor the project root only when the file is under its `src/`;
   otherwise use the detached temp-crate path. Now ~2.6–9.4 s/file.

## Results (frozen test split, seed 1234, 97 files, 136 sinks, 105 evaluated)

Gold: `research/synth/splits/eval_manifest.json` (same manifest as
`eval_protocol.py`). Scorer: `research/detect/score_frozen.py` (new).

| metric | no-lsp | lsp | note |
|---|---|---|---|
| accuracy (3-way Y/M/N vs file gold) | 0.1429 (15/105) | 0.1333 (14/105) | corpus is ~2/3 gold-Y; without dataflow we stay M (by design) |
| **FP-on-N (gold N → pred Y)** | **1** | **0** | dangerous direction — LSP evidence removes the false Y |
| recall_N (gold N → pred N) | 0.0000 | 0.1852 (5/27) | hover arg types (`*mut/*const`) unlock N claims |
| Y precision | 0.8571 (7 Y) | n/a (0 Y preds) | LSP is stricter than syntactic mode |
| pattern claims (hint set) | 7 (4 correct, 0.571) | 6 (5 correct, **0.833**) | claims only with real evidence, per policy |
| api_mismatch sinks (excluded) | 31 | 31 | multi-API files: extra sinks ≠ file's gold API |

Confusion (LSP, rows=gold): `Y: 0/68/1 (Y/M/N)`, `M: 0/9/0`, `N: 0/22/5`.
Per-API highlights: `set_len 4/5`, `CStr::from_ptr 3/6`, `CString::from_raw
2/4`; `ptr::*` and `offset_from` families 0 (all default M — dataflow-bound
patterns beyond p1, expected).

## Reading (for the report)

1. Detector is conservative **by design**: never claims Y/N without evidence →
   0 dangerous FPs on irreplaceable code with LSP (the `research_vectors.md`
   FP-reduction target).
2. Low 3-way accuracy is not a bug: 68/105 sinks are gold-Y non-p1 patterns
   requiring inter-procedural dataflow — exactly the NIRM 4 ML handoff.
3. LSP value is measurable: FP-on-N 1→0, recall_N 0→0.185, hint accuracy
   0.571→0.833.
4. `mem::transmute` flips the other way (no-lsp 3/3 → lsp 0/3): syntactic
   prim-name check in `verdict.decide` claims Y from call text; hover types
   (`*mut u8 as ...`) demote to M. Investigate in Phase 2 — may be a
   verdict-table refinement, not a regression.

## Reproduce

```bash
export PATH=~/.local/bin:$PATH   # rustup RA + rust-src shim
cd research && source ../.venv/bin/activate
python detect/test_detect.py                      # 7/7
python synth/splits/make_splits.py --check        # OK x3
T=synth/splits/test.txt
sed "s|^|../vendors/SafeNet/testdata/|" $T | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --no-lsp --json /tmp/nirm3_no_lsp.json
sed "s|^|../vendors/SafeNet/testdata/|" $T | tr '\n' '\0' \
  | xargs -0 python -u detect/detect.py --json /tmp/nirm3_lsp.json   # ~4.5 min
python detect/score_frozen.py --report /tmp/nirm3_lsp.json \
    --report2 /tmp/nirm3_no_lsp.json | tee /tmp/nirm3_score.txt
```

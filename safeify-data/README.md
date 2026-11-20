# safeify-data

Supporting data and corpus tooling for Safeify.

## Subprojects

- `transitions/` — CVEfixes, RustSec and Rust documentation transition mining
- `synth/` — deterministic synthetic snippets and held-out split assets
- `cve/` — CVE pair extraction and validation helpers

## Key rules

- Synthetic data is augmentation, never held-out evidence.
- Frozen datasets must preserve provenance and hashes.
- Mining scripts write generated artifacts under `out/` or `/tmp`, depending on their scope.
- Label and split changes require leakage and validation checks.

## Common commands

```sh
cd safeify-data/synth
python build.py
python splits/make_splits.py --check
```

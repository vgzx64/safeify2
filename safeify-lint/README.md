# safeify-lint

`safeify-lint` is the rust-analyzer-based semantic linter for Counterexamples-in-Safe-Rust patterns.

## Modes

- `--crate <DIR>`: lint safe Rust code for filesystem, process, environment and build-script risks.
- `--inventory <FILE>`: emit unsafe regions, calls, raw derefs and function guards for `safeify-ai`.

## Build

```sh
./safeify-lint/cargo.sh build --release
./.tools/cargo-target/engine/release/safeify-lint --help
```

## Lint tests

```sh
./safeify-lint/cargo.sh test --release
```

## Important files

- `src/rules.rs` — finding and severity rules
- `src/prov.rs` — semantic provenance lattice
- `src/sink.rs` — resolved sink tables
- `src/inventory.rs` — unsafe-region inventory
- `tests/` — semantic regression suites

This product is independent of `safeify-ai` Y/M/N verdicts. Safe-Rust findings use deny/warn/info levels; unsafe replaceability judgments use Y/M/N.

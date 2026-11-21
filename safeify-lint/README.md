# safeify-lint

`safeify-lint` is the rust-analyzer-based semantic linter for the
Counterexamples-in-Safe-Rust patterns: safe `std::fs` / `std::process` /
`std::env` / `build.rs` code that becomes a security risk through OS interfaces.
Every decision is made on rust-analyzer's resolved model (name resolution,
types, macro expansion), not on source text. Design and measurements:
[`notes/research/counterexamples.md`](../notes/research/counterexamples.md) and
[`notes/research/engine.md`](../notes/research/engine.md).

## Usage

```sh
safeify-lint --crate <DIR> [--out findings.json] [--min-level warn]
safeify-lint --inventory <FILE.rs> [--out inventory.json]
```

`--crate` analyses one Cargo package and prints a JSON array of findings:

```json
{"path": "src/lib.rs", "line": 12, "col": 5,
 "rule": "fs_tainted_path", "level": "warn",
 "message": "path written by this call comes from a caller-supplied path"}
```

`--min-level <info|warn|deny>` makes the exit code a CI gate: `0` when the
crate is clean, `1` when a finding at or above that level exists, `2` when the
engine itself failed (unreadable package, cargo metadata error, bad argument).
Without `--min-level` the exit code is `0` unless the engine fails.
`--stats <FILE|->` writes classification counters, and `--extra-cfg` analyses code behind other `cfg`
atoms (for example `--extra-cfg windows,target_family=windows`).

`--inventory <FILE>` is the unsafe-region inventory consumed by
[`safeify-ai`](../safeify-ai/README.md) for replaceability judging: unsafe
regions, the calls inside them, raw derefs with the operand type classified, and
the enclosing function's guards, all as JSON. It loads a standalone snippet the
same way the LSP evidence path does, so `std::ptr::read` resolves without a
`use` statement.

## Rules

| Rule | Pattern | Fires on | Default |
|---|---|---|---|
| `fs_special_path` | filesystem | literal path in the danger table: `/proc/*/mem`, `/proc/*/pagemap` (`<pid>` is `self`, `thread-self` or a number, including the per-thread `/proc/<pid>/task/<tid>/mem`), `/proc/kcore`, `/dev/{mem,kmem,port}`, `/etc/ld.so.preload`, `\\.\` and `\\?\` device namespaces | `deny` |
| `fs_traversal_literal` | filesystem | absolute literal whose `..` normalises elsewhere | `warn` |
| `fs_tainted_path` | filesystem | **write** sink whose path comes from env/argv/stdio/network with no guard (`warn`) or from a plain parameter (`info`) | `warn`/`info` |
| `exec_basename` | command | `Command::new("ls")` — no path separator, so PATH (and CWD on Windows) decides what runs | `warn` |
| `exec_tainted_cmd` | command | program name from a parameter or taint source, no allowlist | `warn` |
| `exec_shell_tainted` | command | a shell (`sh`, `bash`, `cmd`, …) receives a caller-controlled argument | `warn` |
| `exec_written_path` | command | executes an absolute path this same function wrote earlier (dropper) | `warn` |
| `env_set_dangerous` | environment | `set_var`/`remove_var` on `PATH`, `LD_PRELOAD`, `RUSTC`, `RUSTFLAGS`, `TMPDIR`, `HOME`, … | `warn` |
| `env_read_dangerous` | environment | `var`/`var_os` of the same names (a taint source) | `info` |
| `build_outside_out_dir` | build-time | `build.rs` write whose path does not name `OUT_DIR` or `target` as a path segment | `warn` |

`fs_tainted_path`, `exec_basename` and `exec_tainted_cmd` are `warn` only in a
non-private function (any `pub*` form) or `build.rs`; elsewhere the tainted
class is `info`, because a binary's own `main` running `Command::new("git")` is
normal engineering. This is a syntactic proxy for reachability, not a call
graph. `deny` is
reserved for paths that are dangerous whoever calls them. Writes are in scope
for `fs_tainted_path`; reading a caller's path is a library contract. Cargo's
`OUT_DIR`/`CARGO_*` variables are trusted, not tainted.

Suppression follows Clippy:

```rust
#[allow(safeify::exec_basename)]     // fn, module or crate attrs, including cfg_attr
// safeify: allow(fs_special_path)   // anywhere in the function body
```

The namespace is `safeify::<rule>`. Suppressions are resolved by rust-analyzer,
so an alias or `cfg_attr` cannot slip past them. A Cargo `[lints.safeify]` table
is not read: the engine sees source attributes, not rustc flags.

## Analysis scope

Calls into the analysed package are **interpreted at the call site**: arguments
are bound to the callee's parameters and its tail expression and `return`s are
evaluated, so `fs::write(dest(root, name))` sees what `dest` does with `root`
and `name`. `format!("{root}/{name}")` is read from rust-analyzer's
`FORMAT_ARGS_EXPR`, including implicit captures, and composition is
taint-dominant in `format!`, `+` and collection literals: a trusted `OUT_DIR`
prefix does not launder a caller-controlled suffix. Iterator adapters that
hand back elements (`nth`, `next`, `collect`, `lines`, ...) keep the
iterator's class, so `env::args().nth(1)` is as caller-controlled as the `for`
loop; `canonicalize` and `parent` derive a path but keep the class of their
input. Field reads use a crate-wide `(struct, field)` summary; guards
(`canonicalize` +
`starts_with`, `file_name`, `components` + `ParentDir`) are recognised on the
dominated path; macros are expanded, including `try!`, `assert!` and
`matches!`.

Limits, measured in [`engine.md` §4.3](../notes/research/engine.md#43-what-is-not-implemented-and-the-report-must-say-so):
dependency sources are not loaded (`no_deps`), so a wrapper in another crate is
`unknown` and never fires; there is no branch-sensitive or heap/aliasing model;
a recursive return is cut to `unknown`; `read_line` writes into its buffer
argument and is not modelled (`lines()` is); test/example code is analysed like
library code.

## Build and test

```sh
./safeify-lint/cargo.sh build --release     # .tools/cargo-target/engine/release/safeify-lint
./safeify-lint/cargo.sh test --release      # 8 semantic regression tests
```

The build uses a vendored rust-analyzer (`vendors/rust-analyzer`) through path
dependencies and applies one patch
([`patches/rust-analyzer-sysroot-deps.patch`](patches/rust-analyzer-sysroot-deps.patch))
so `no_deps` describes the analysed package, not the sysroot.

## Corpus

[`corpus/run_semantic_corpus.py`](corpus/run_semantic_corpus.py) runs the engine
over the vendored corpus (329 package versions) and prints the per-rule diff
against the frozen text-engine census;
[`corpus_report.py`](corpus/corpus_report.py) unions the host and Windows passes
and diffs against the census. [`audit_lint.py`](audit_lint.py) builds the
precision-audit sheet and computes Wilson and crate-clustered intervals from
recorded labels. Regenerated numbers live in [`out/`](out/) and are summarised
in [`notes/research/engine.md` §7](../notes/research/engine.md#7-measurements-the-engine-must-produce).

This product is independent of `safeify-ai`'s Y/M/N verdicts: Safe-Rust findings
use those levels; unsafe replaceability judgments use Y/M/N, and the two are not
scored together.

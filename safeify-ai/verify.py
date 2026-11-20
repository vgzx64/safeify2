"""rustc gate — same recipe as safeify-data/synth/verify/check.py (stable only)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def rustc_check(code: str, edition: str = "2021",
                extra_args: tuple[str, ...] = ()) -> tuple[bool, str]:
    """Compile `code` as a lib with `rustc --emit=metadata`. Stable only."""
    with tempfile.TemporaryDirectory(prefix="detect_verify_") as td:
        src = Path(td) / "lib.rs"
        out = Path(td) / "lib.rmeta"
        src.write_text(code)
        cmd = ["rustc", "--edition", edition, "--crate-type=lib",
               "--emit=metadata", "-A", "warnings", "-o", str(out),
               *extra_args, str(src)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return p.returncode == 0, (p.stderr or "")


def verify_file(path: str | Path) -> tuple[bool, str]:
    """Whether a .rs file compiles standalone as a lib (best effort)."""
    return rustc_check(Path(path).read_text(errors="replace"))


if __name__ == "__main__":
    import sys

    for f in sys.argv[1:]:
        ok, err = verify_file(f)
        print(f"{'OK ' if ok else 'ERR'} {f}")
        if not ok:
            print(err[:500])

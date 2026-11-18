"""One-shot orchestration: generate -> verify -> pair -> report.

Usage:  python build.py            (from research/synth/)
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def run(script):
    print(f"\n=== {script} " + "=" * max(0, 50 - len(script)))
    proc = subprocess.run([sys.executable, script], cwd=ROOT)
    if proc.returncode != 0:
        sys.exit(proc.returncode)


def main():
    run("gen/template.py")
    run("gen/inject.py")
    run("gen/derive_contexts.py")
    run("verify/check.py")
    run("gen/pairs.py")
    run("splits/check_train_leakage.py")
    run("verify/report.py")
    print("\nbuild complete -> out/train_*.csv, out/pairs_manifest.jsonl, out/report.md")


if __name__ == "__main__":
    main()

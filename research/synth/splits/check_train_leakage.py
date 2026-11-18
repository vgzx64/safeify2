#!/usr/bin/env python3
"""Fail if a pair-training CSV contains a valid/test snippet.

Thin CLI wrapper around `splits/holdout.py`; keep the checker and the builder
using the same implementation.

    python splits/check_train_leakage.py
    python splits/check_train_leakage.py out/train_mixed.csv out/train_hard.csv
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from holdout import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

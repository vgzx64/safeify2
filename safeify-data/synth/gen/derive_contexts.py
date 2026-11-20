"""Structural context diversification.

The baseline representation normalizes identifier names and type names to varN,
so grids that vary only $T/$N collapse to one sequence under dedupe. To grow
the number of *structurally* distinct rows cheaply, every kept snippet is
re-emitted wrapped in `mod synth_m1 { ... }` and `mod synth_m1 { mod synth_m2 { ... } }`.
Item sets are self-contained, so wrappers always compile, and the extra
nesting/idents produce different preorder sequences.

Emits new records with seq offsets +1000 (mod1) and +2000 (mod2); verify/check.py
re-runs compile+AST+dedupe over everything.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (OUT_RECORDS_INJ, OUT_RECORDS_TMPL, SYNTH_ROOT, write_snippet)  # noqa: E402

CONTEXTS = [("mod1", 1000), ("mod2", 2000)]


def wrap(text, ctx):
    # keep the crate-level #![allow(...)] outside the mod
    lines = text.splitlines(keepends=True)
    header, body = [], []
    for ln in lines:
        (header if ln.startswith("#!") else body).append(ln)
    inner = "".join(body)
    if ctx == "mod1":
        wrapped = "mod synth_m1 {\n" + inner + "}\n"
    else:
        wrapped = "mod synth_m1 {\nmod synth_m2 {\n" + inner + "}\n}\n"
    return "".join(header) + wrapped


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main():
    base_records = load(OUT_RECORDS_TMPL) + load(OUT_RECORDS_INJ)
    new_records = []
    for ctx, offset in CONTEXTS:
        for rec in base_records:
            src = os.path.join(SYNTH_ROOT, "out", rec["rel_path"])
            with open(src, encoding="utf-8") as f:
                text = f.read()
            new_rec = dict(rec)
            new_rec["ctx"] = ctx
            # renumber into a private range so filenames never collide
            seq = int(rec["id"].rsplit("-", 2)[1]) + offset
            write_snippet(rec["api"], rec["pattern_id"], rec["kind"], seq,
                          wrap(text, ctx), new_rec, new_records)
    # append each record to the file of its originating generator
    for path, source in ((OUT_RECORDS_TMPL, "template"),
                         (OUT_RECORDS_INJ, "counterfactual_injection")):
        with open(path, "a", encoding="utf-8") as f:
            for rec in new_records:
                if rec.get("source") == source:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"contexts: +{len(new_records)} wrapped snippets "
          f"({len(base_records)} x {len(CONTEXTS)})")


if __name__ == "__main__":
    main()

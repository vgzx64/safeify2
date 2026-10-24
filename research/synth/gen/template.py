"""Strategy B: template/rule-based generation from rules/*.yaml.

Each rule pins (api, pattern_id, replaceability) from the SafeNet knowledge-base
README, so labels are correct by construction. Emits:
  <pattern>-synth-<k>-unsafe.rs   always
  <pattern>-synth-<k>-safe.rs     when replaceability == Y
  <pattern>-synth-<k>-encap.rs    when the rule defines an encapsulation wrapper
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (OUT_RECORDS_TMPL, SYNTH_ROOT, flush_records, grid_variants,
                    load_rules, render, write_snippet)


def main():
    records = []
    rules = load_rules(os.path.join(SYNTH_ROOT, "rules"))
    seq = 0
    counts = {"unsafe": 0, "safe": 0, "encap": 0}
    for rule in rules:
        base = {
            "source": "template",
            "api": rule["api"],
            "pattern_id": rule["pattern_id"],
            "replaceability": rule["replaceability"],
            "verdict": rule["verdict"],
            "difficulty": rule.get("difficulty", "medium"),
            "contract": rule.get("contract", ""),
            "rule": rule["_file"],
        }
        for variant in grid_variants(rule.get("grid")):
            seq += 1
            unsafe_rec = write_snippet(
                rule["api"], rule["pattern_id"], "unsafe", seq,
                render(rule["unsafe"], variant),
                dict(base, variant=variant), records)
            counts["unsafe"] += 1
            if rule["replaceability"] == "Y" and "safe" in rule:
                write_snippet(
                    rule["api"], rule["pattern_id"], "safe", seq,
                    render(rule["safe"], variant),
                    dict(base, variant=variant, parent=unsafe_rec["id"]), records)
                counts["safe"] += 1
            if "encap" in rule:
                write_snippet(
                    rule["api"], rule["pattern_id"], "encap", seq,
                    render(rule["encap"], variant),
                    dict(base, variant=variant, parent=unsafe_rec["id"],
                         replaceability="N", verdict="encapsulatable"), records)
                counts["encap"] += 1
    flush_records(records, OUT_RECORDS_TMPL)
    print(f"template: {len(rules)} rules -> {counts} "
          f"({sum(counts.values())} files, {OUT_RECORDS_TMPL})")


if __name__ == "__main__":
    main()

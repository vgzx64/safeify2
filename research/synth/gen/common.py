"""Shared helpers for synthetic snippet generation."""

import itertools
import json
import os
import re

SYNTH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_SNIPPETS = os.path.join(SYNTH_ROOT, "out", "snippets")
OUT_RECORDS_TMPL = os.path.join(SYNTH_ROOT, "out", "gen_records_template.jsonl")
OUT_RECORDS_INJ = os.path.join(SYNTH_ROOT, "out", "gen_records_inject.jsonl")
OUT_RECORDS = [OUT_RECORDS_TMPL, OUT_RECORDS_INJ]

HEADER = "#![allow(unused)]\n"


def slug(api):
    """Directory name for an API (testdata style: no '(c)' suffix, '::' kept)."""
    return api.replace("(c)", "").strip()


def render(template, variant):
    """$KEY substitution; longer keys first so $N never eats $NAME."""
    out = template
    for k in sorted(variant, key=len, reverse=True):
        out = out.replace(f"${k}", str(variant[k]))
    leftover = re.findall(r"\$[A-Za-z_]+", out)
    if leftover:
        raise ValueError(f"unsubstituted placeholders {leftover} for variant {variant}")
    return out


def grid_variants(grid):
    """Cartesian product of the YAML `grid` mapping -> list of variant dicts."""
    if not grid:
        return [{}]
    keys = list(grid)
    return [dict(zip(keys, combo)) for combo in itertools.product(*(grid[k] for k in keys))]


def write_snippet(api, pattern_id, kind, seq, text, record, records):
    """Write one .rs file and append its manifest record.

    kind: 'unsafe' | 'safe' | 'encap'   ->   <pattern>-synth-<seq>-<kind>.rs
    """
    api_dir = os.path.join(OUT_SNIPPETS, slug(api))
    os.makedirs(api_dir, exist_ok=True)
    fname = f"{pattern_id}-synth-{seq:03d}-{kind}.rs"
    path = os.path.join(api_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(HEADER + text)
    rec = dict(record)
    rec.update({
        "id": f"{slug(api)}/{pattern_id}-synth-{seq:03d}-{kind}",
        "rel_path": os.path.join("snippets", slug(api), fname),
        "kind": kind,
    })
    records.append(rec)
    return rec


def load_rules(rules_dir):
    import yaml
    rules = []
    for fname in sorted(os.listdir(rules_dir)):
        if fname.endswith(".yaml"):
            with open(os.path.join(rules_dir, fname), encoding="utf-8") as f:
                rule = yaml.safe_load(f)
            rule["_file"] = fname
            rules.append(rule)
    return rules


def flush_records(records, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

"""Check the v0.2 family core for split leakage.

Splits are keyed on canonical repository identity, so this should report zero
cross-split repository/snippet overlap. The audit also reports unresolved
identity fallbacks (`pkg:` / `name:` keys) and any duplicate old snippets that
still land in different splits.

Writes out/split_leakage.json.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
CORE = OUT / "transitions_core_v0.2_draft.jsonl"


def norm(s: str) -> str:
    return " ".join((s or "").split())


def repo(r: dict) -> str:
    return r.get("repo_key") or r.get("repo_name") or r.get("package") or "unknown"


def audit(rows: list[dict]) -> dict:
    splits = sorted({r["split"] for r in rows})

    repos: dict[str, set[str]] = {s: set() for s in splits}
    commits: dict[str, set[str]] = {s: set() for s in splits}
    cves: dict[str, set[str]] = {s: set() for s in splits}
    for r in rows:
        repos[r["split"]].add(repo(r))
        if r.get("commit"):
            commits[r["split"]].add(r["commit"])
        if r.get("cve_id"):
            cves[r["split"]].add(str(r["cve_id"]))

    pairs = {}
    for i, a in enumerate(splits):
        for b in splits[i + 1:]:
            pairs[f"{a}/{b}"] = {
                "repos": len(repos[a] & repos[b]),
                "commits": len(commits[a] & commits[b]),
                "cves": len(cves[a] & cves[b]),
            }

    groups = defaultdict(list)
    for r in rows:
        groups[norm(r.get("old_snippet"))].append(r)
    cross = [g for g in groups.values() if len({r["split"] for r in g}) > 1]
    cross.sort(key=lambda g: -len(g))

    alias: dict[str, set[str]] = defaultdict(set)
    for g in cross:
        names = {r.get("repo_name") or r.get("package") or "unknown" for r in g}
        for name in names:
            alias[name].update(names - {name})

    detail = [{
        "rows": len(g),
        "entries": [
            {"split": r["split"], "label": r["label"], "repo": repo(r),
             "repo_name": r.get("repo_name") or r.get("package"), "path": r.get("path")}
            for r in g
        ],
    } for g in cross]

    return {
        "rows": len(rows),
        "splits": {s: sum(1 for r in rows if r["split"] == s) for s in splits},
        "pairwise_overlap": pairs,
        "cross_split_snippet_groups": len(cross),
        "cross_split_rows": sum(len(g) for g in cross),
        "cross_split_rows_by_split": {
            s: sum(1 for g in cross for r in g if r["split"] == s) for s in splits
        },
        "cross_split_positives": sum(1 for g in cross for r in g if r["label"] == "Y"),
        "alias_pairs": {k: sorted(v) for k, v in alias.items()},
        "unresolved_repo_keys": sorted({
            repo(r) for r in rows if repo(r).startswith(("pkg:", "name:"))
        }),
        "groups": detail,
    }


def verdict(leak: dict) -> str:
    if leak["cross_split_snippet_groups"] or any(
        v["repos"] or v["commits"] or v["cves"] for v in leak["pairwise_overlap"].values()
    ):
        return ("Repository-identity leakage remains; regenerate splits from "
                "canonical repository keys before any training run.")
    return ("no split leakage on canonical repository keys; test split is a "
            "clean holdout.")


def main() -> int:
    rows = [json.loads(x) for x in CORE.open() if x.strip()]
    leak = audit(rows)
    report = {"core": CORE.name, **leak, "verdict": verdict(leak)}
    (OUT / "split_leakage.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("groups", "alias_pairs")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

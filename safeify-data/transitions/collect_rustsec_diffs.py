"""Collect transition hunks from RustSec PR/commit URLs (no repo clone).

Uses GitHub's ``.diff`` endpoint for /pull/<n> and /commit/<sha> URLs. This
covers advisories that are not in CVEfixes without cloning hundreds of repos.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from collect_hunks import code_only, has_code_unsafe
from extract_candidates import api_guess, parse_unified_diff, repo_name

OUT = Path(__file__).resolve().parent / "out"


def fetch(url: str) -> str | None:
    try:
        p = subprocess.run(
            ["curl", "-L", "-sS", "--max-time", "35", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return None
    if p.returncode != 0 or not p.stdout.strip():
        return None
    return p.stdout


def split_files(diff: str):
    parts = re.split(r"(?m)^diff --git ", diff)
    for part in parts:
        if not part.strip():
            continue
        text = "diff --git " + part if not part.startswith("diff --git ") else part
        m = re.search(r"(?m)^\+\+\+ b/(.+)$", text)
        if not m:
            m = re.search(r"(?m)^--- a/(.+)$", text)
        if not m:
            continue
        path = m.group(1).strip()
        if path == "/dev/null":
            continue
        yield path, text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    gaps = [json.loads(x) for x in (OUT / "rustsec_gaps.jsonl").open()]
    gaps = [r for r in gaps if r.get("url_kind") in ("pull", "commit")]
    if args.limit:
        gaps = gaps[: args.limit]

    rows = []
    stats = Counter()
    failures = []
    for r in gaps:
        url = r["url"].rstrip("/") + ".diff"
        diff = fetch(url)
        if not diff:
            failures.append({"id": r["id"], "url": url, "reason": "fetch"})
            stats["fetch_failed"] += 1
            continue
        for path, text in split_files(diff):
            for i, hunk in enumerate(parse_unified_diff(text)):
                old = "\n".join(x[1] for x in hunk["deleted"])
                new = "\n".join(x[1] for x in hunk["added"])
                old_u, new_u = has_code_unsafe(old), has_code_unsafe(new)
                if not (old_u or new_u):
                    continue
                if old_u and not new_u:
                    kind = "safe_candidate"
                elif old_u and new_u:
                    kind = "unsafe_retained"
                else:
                    kind = "unsafe_added"
                rows.append({
                    "id": f"rustsec:{r['id']}:{path}:{hunk['old_start']}:{i}",
                    "source": "rustsec",
                    "advisory_id": r["id"],
                    "package": r["package"],
                    "date": r["date"],
                    "repo_name": r.get("repo_name") or repo_name(r["url"]),
                    "url": r["url"],
                    "path": path,
                    "span_start": hunk["old_start"],
                    "span_end": hunk["old_end"],
                    "kind": kind,
                    "old_unsafe": old_u,
                    "new_unsafe": new_u,
                    "api_old": api_guess(old),
                    "api_new": api_guess(new),
                    "old_snippet": old,
                    "safe_snippet": new,
                    "old_lines": len(hunk["deleted"]),
                    "new_lines": len(hunk["added"]),
                    "review_status": "unreviewed",
                    "label": "unreviewed",
                })
                stats[kind] += 1
        stats["advisories"] += 1

    with (args.out / "rustsec_hunks.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"advisories": len(gaps), "rows": len(rows), "kinds": dict(stats),
               "failures": failures[:30], "failure_count": len(failures)}
    (args.out / "rustsec_hunks_stats.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "failures"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

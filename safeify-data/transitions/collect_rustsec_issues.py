"""Resolve RustSec issue URLs to same-repository PR/commit diffs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from collect_hunks import has_code_unsafe
from collect_rustsec_diffs import split_files
from extract_candidates import api_guess, parse_unified_diff, repo_name

OUT = Path(__file__).resolve().parent / "out"


def fetch(url: str) -> str | None:
    try:
        p = subprocess.run(
            ["curl", "-L", "-sS", "--max-time", "35", "-A", "Mozilla/5.0", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return None
    return p.stdout if p.returncode == 0 and p.stdout else None


def same_repo_fix(issue_url: str, html: str) -> str | None:
    m = re.search(r"https?://[^/]+/([^/]+)/([^/?#]+)/issues/\d+", issue_url)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    pulls = re.findall(rf"https://github\.com/{re.escape(owner)}/{re.escape(repo)}/pull/(\d+)", html)
    commits = re.findall(rf"https://github\.com/{re.escape(owner)}/{re.escape(repo)}/commit/([0-9a-f]{{7,40}})", html)
    if pulls:
        return f"https://github.com/{owner}/{repo}/pull/{pulls[0]}"
    if commits:
        return f"https://github.com/{owner}/{repo}/commit/{commits[0]}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    gaps = [json.loads(x) for x in (OUT / "rustsec_gaps.jsonl").open()]
    gaps = [r for r in gaps if r.get("url_kind") == "issues"]
    if args.limit:
        gaps = gaps[: args.limit]

    rows = []
    stats = Counter()
    failures = []
    for r in gaps:
        html = fetch(r["url"])
        if not html:
            failures.append({"id": r["id"], "url": r["url"], "reason": "issue_fetch"})
            stats["issue_fetch_failed"] += 1
            continue
        fix = same_repo_fix(r["url"], html)
        if not fix:
            stats["no_same_repo_fix"] += 1
            continue
        diff = fetch(fix.rstrip("/") + ".diff")
        if not diff:
            stats["diff_fetch_failed"] += 1
            continue
        stats["resolved"] += 1
        for path, text in split_files(diff):
            for i, hunk in enumerate(parse_unified_diff(text)):
                old = "\n".join(x[1] for x in hunk["deleted"])
                new = "\n".join(x[1] for x in hunk["added"])
                old_u, new_u = has_code_unsafe(old), has_code_unsafe(new)
                if not (old_u or new_u):
                    continue
                kind = "safe_candidate" if old_u and not new_u else "unsafe_retained" if old_u else "unsafe_added"
                rows.append({
                    "id": f"rustsec-issue:{r['id']}:{path}:{hunk['old_start']}:{i}",
                    "source": "rustsec",
                    "advisory_id": r["id"],
                    "package": r["package"],
                    "date": r["date"],
                    "repo_name": r.get("repo_name") or repo_name(fix),
                    "url": fix,
                    "issue_url": r["url"],
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
    with (OUT / "rustsec_issue_hunks.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"issues": len(gaps), "rows": len(rows), "stats": dict(stats), "failure_count": len(failures)}
    (OUT / "rustsec_issue_hunks_stats.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

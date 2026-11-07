"""Sample Rust-for-Linux encapsulation patches from Linux commit history."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.parse
from collections import Counter
from pathlib import Path

from collect_hunks import has_code_unsafe
from collect_rustsec_diffs import split_files
from extract_candidates import parse_unified_diff

OUT = Path(__file__).resolve().parent / "out"


def curl(url: str, accept: str = "") -> str | None:
    cmd = ["curl", "-L", "-sS", "--max-time", "45", "-A", "safeify-research"]
    if accept:
        cmd += ["-H", f"Accept: {accept}"]
    p = subprocess.run(cmd + [url], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.stdout if p.returncode == 0 and p.stdout else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()
    q = urllib.parse.quote("repo:torvalds/linux rust: abstraction")
    data = curl(f"https://api.github.com/search/commits?q={q}&per_page={max(args.limit*2,20)}",
                "application/vnd.github.cloak-preview+json")
    if not data:
        print("search failed")
        return 1
    items = json.loads(data).get("items", [])
    rows = []
    stats = Counter()
    seen_sha = set()
    for it in items:
        sha = it["sha"]
        if sha in seen_sha:
            continue
        seen_sha.add(sha)
        patch = curl(f"https://github.com/torvalds/linux/commit/{sha}.patch")
        if not patch:
            stats["patch_fetch_failed"] += 1
            continue
        for path, text in split_files(patch):
            if not path.startswith("rust/"):
                continue
            for i, hunk in enumerate(parse_unified_diff(text)):
                old = "\n".join(x[1] for x in hunk["deleted"])
                new = "\n".join(x[1] for x in hunk["added"])
                old_u, new_u = has_code_unsafe(old), has_code_unsafe(new)
                if not (old_u or new_u):
                    continue
                kind = "safe_candidate" if old_u and not new_u else "unsafe_retained" if old_u else "unsafe_added"
                rows.append({
                    "id": f"rfl:{sha[:12]}:{path}:{hunk['old_start']}:{i}",
                    "source": "rust-for-linux",
                    "commit": sha,
                    "repo_name": "torvalds_linux",
                    "path": path,
                    "commit_subject": it["commit"]["message"].splitlines()[0],
                    "span_start": hunk["old_start"],
                    "span_end": hunk["old_end"],
                    "kind": kind,
                    "old_unsafe": old_u,
                    "new_unsafe": new_u,
                    "old_snippet": old,
                    "safe_snippet": new,
                    "review_status": "unreviewed",
                    "label": "unreviewed",
                })
                stats[kind] += 1
        stats["commits"] += 1
        if stats["commits"] >= args.limit:
            break
    with (OUT / "rust_for_linux_hunks.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"rows": len(rows), "stats": dict(stats)}
    (OUT / "rust_for_linux_stats.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

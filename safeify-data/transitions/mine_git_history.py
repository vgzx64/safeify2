"""Mine unsafe->safe transitions from the local git mirrors of rust_ecosystem.

`/mnt/tc2015_p5/Code/rust_ecosystem/repos_mirror` holds bare clones of the 811
repositories used by the vulnerability study. Their full commit histories are a
much larger version-history corpus than the crate tarballs: every commit that
touches `unsafe` in a `.rs` file is a candidate, and a hunk where the deleted
code has an unsafe operation while the added code does not is an objective
old->new pair.

Uses `git log -p -Gunsafe --no-merges`, parses the unified diff itself and
writes rows incrementally. Resumable: repositories already in the output are
skipped. Caps rows per repository so wasmtime-sized histories cannot dominate.

Writes out/git_history_pairs.jsonl.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

from collect_hunks import has_code_unsafe
from extract_candidates import api_guess
from repo_identity import canon_url

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
MIRROR = Path("/mnt/tc2015_p5/Code/rust_ecosystem/repos_mirror")
DEST = OUT / "git_history_pairs.jsonl"
MAX_SNIPPET = 20000

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def run(cmd: list[str], cwd: Path, timeout: int = 300) -> str:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, errors="replace")
        return proc.stdout
    except Exception:
        return ""


def mine_repo(repo: Path, max_rows: int, max_commits: int,
              budget: float = 90.0) -> list[dict]:
    url = canon_url(run(["git", "config", "--get", "remote.origin.url"], repo).strip())
    label = repo.name
    cmd = ["git", "log", "-p", "--no-merges", f"-n{max_commits}",
           "-Gunsafe", "--format=commit %H %ct", "--", "*.rs"]
    rows: list[dict] = []
    commit = date = path = None
    span = 0
    deleted: list[str] = []
    added: list[str] = []
    in_hunk = False

    def flush() -> None:
        nonlocal deleted, added
        d, a = "\n".join(deleted), "\n".join(added)
        if (d.strip() and a.strip() and len(d) + len(a) <= MAX_SNIPPET
                and has_code_unsafe(d) and not has_code_unsafe(a)):
            rows.append({
                "id": f"git:{label}:{(commit or '')[:12]}:{path}:{span}",
                "source": "git",
                "repo_url": url,
                "repo_name": label,
                "commit": commit,
                "commit_date": int(date) if date else None,
                "path": path,
                "span_start": span,
                "old_snippet": d,
                "safe_snippet": a,
                "api_old": api_guess(d),
                "api_new": api_guess(a),
                "kind": "safe_candidate",
            })
        deleted, added = [], []

    proc = subprocess.Popen(cmd, cwd=repo, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True,
                            errors="replace")
    deadline = time.time() + budget
    try:
        lines = proc.stdout
    except Exception:
        return []
    for line in lines:
        if line.startswith("commit "):
            if in_hunk:
                flush()
                in_hunk = False
            parts = line.split()
            commit = parts[1] if len(parts) > 1 else ""
            date = parts[2] if len(parts) > 2 else None
        elif line.startswith("diff --git "):
            if in_hunk:
                flush()
                in_hunk = False
            m = re.match(r"diff --git a/(.*) b/", line)
            path = m.group(1) if m else path
        elif line.startswith("@@ "):
            if in_hunk:
                flush()
            m = HUNK.match(line)
            span = int(m.group(1)) if m else 0
            in_hunk = True
        elif in_hunk:
            if line.startswith("-"):
                deleted.append(line[1:])
            elif line.startswith("+"):
                added.append(line[1:])
        if len(rows) >= max_rows or time.time() > deadline:
            break
    proc.kill()
    proc.wait()
    if in_hunk:
        flush()
    return rows[:max_rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-rows", type=int, default=200, help="rows kept per repository")
    ap.add_argument("--max-commits", type=int, default=2000)
    ap.add_argument("--limit", type=int, default=0, help="0 = every mirror")
    ap.add_argument("--mirror", type=Path, default=MIRROR)
    args = ap.parse_args()

    done = set()
    if DEST.exists():
        done = {json.loads(x)["repo_name"] for x in DEST.open() if x.strip()}
    repos = sorted(p for p in args.mirror.iterdir() if p.is_dir() and p.name not in done)
    if args.limit:
        repos = repos[: args.limit]

    stats = Counter()
    t0 = time.time()
    with DEST.open("a") as f:
        for i, repo in enumerate(repos, 1):
            t = time.time()
            rows = mine_repo(repo, args.max_rows, args.max_commits)
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            stats["rows"] += len(rows)
            stats["repos_with_rows"] += 1 if rows else 0
            stats["repos"] += 1
            print(f"[{i}/{len(repos)}] {repo.name}: {len(rows)} rows "
                  f"({time.time() - t:.1f}s, total {stats['rows']}, "
                  f"{time.time() - t0:.0f}s)", flush=True)
    print(json.dumps(dict(stats), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Mine unsafe->safe transitions from consecutive published crate versions.

Version tarballs are immutable, so a diff between two releases is an objective
old->new pair: no CVE database, no maintainer judgement, no LLM labels. A hunk
is kept when the deleted code contains an unsafe operation and the added code
does not (`safe_candidate`), which is exactly the shape the mechanism labeller
and the repair assistant consume.

Crates already in `external/crates` are used as the package list; the newest
`--versions` non-yanked versions are downloaded (cached) and consecutive pairs
are diffed. Rows are appended per crate so a stalled run keeps its work.

Writes out/version_pairs.jsonl (append-safe: rows are deduplicated by id).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import unified_diff
from pathlib import Path

from collect_hunks import has_code_unsafe
from extract_candidates import api_guess, parse_unified_diff
from mine_cratesio import download, get, rs_files, versions
from repo_identity import canon_url

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
EXT = HERE / "external/crates"
MAX_SNIPPET = 20000


def repo_of(root: Path) -> str | None:
    for ct in root.rglob("Cargo.toml"):
        m = re.search(r'^\s*repository\s*=\s*"([^"]+)"', ct.read_text(errors="replace"), re.M)
        if m:
            return canon_url(m.group(1))
    return None


def pair_rows(pkg: str, repo: str, v_old: str, v_new: str,
              old_root: Path, new_root: Path) -> list[dict]:
    old_files = dict(rs_files(old_root))
    new_files = dict(rs_files(new_root))
    rows = []
    for rel in sorted(set(old_files) & set(new_files)):
        try:
            old = old_files[rel].read_text(encoding="utf-8", errors="replace")
            new = new_files[rel].read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if old == new:
            continue
        diff = "".join(unified_diff(old.splitlines(True), new.splitlines(True),
                                    fromfile=str(rel), tofile=str(rel)))
        for j, hunk in enumerate(parse_unified_diff(diff)):
            deleted = "\n".join(x[1] for x in hunk["deleted"])
            added = "\n".join(x[1] for x in hunk["added"])
            if not (has_code_unsafe(deleted) and not has_code_unsafe(added)):
                continue
            if not deleted.strip() or not added.strip():
                continue
            if len(deleted) + len(added) > MAX_SNIPPET:
                continue
            rows.append({
                "id": f"ver:{pkg}:{v_old}->{v_new}:{rel}:{hunk['old_start']}:{j}",
                "source": "versions",
                "package": pkg,
                "repo_url": repo,
                "version_before": v_old,
                "version_after": v_new,
                "path": rel.as_posix(),
                "span_start": hunk["old_start"],
                "span_end": hunk["old_end"],
                "old_snippet": deleted,
                "safe_snippet": added,
                "api_old": api_guess(deleted),
                "api_new": api_guess(added),
                "kind": "safe_candidate",
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="0 = every cached package")
    ap.add_argument("--versions", type=int, default=6)
    ap.add_argument("--gap", type=int, default=1,
                    help="diff version i against version i+gap (1 = consecutive)")
    ap.add_argument("--jobs", type=int, default=6, help="parallel crate workers")
    args = ap.parse_args()

    dest = OUT / "version_pairs.jsonl"
    done = set()
    if dest.exists():
        done = {json.loads(x)["package"] for x in dest.open() if x.strip()}
    packages = sorted(p for p in EXT.iterdir() if p.is_dir() and p.name not in done)
    if args.limit:
        packages = packages[: args.limit]

    def process(pkg: Path) -> list[dict]:
        name = pkg.name
        vs = [v for v in versions(name) if not v.get("yanked")][-args.versions:]
        if len(vs) < 2:
            return []
        roots, repo = [], None
        for v in vs:
            root = download(name, v["num"])
            roots.append(root)
            if root is not None:
                repo = repo or repo_of(root)
        out = []
        for idx in range(len(vs) - args.gap):
            a, b = vs[idx], vs[idx + args.gap]
            ra, rb = roots[idx], roots[idx + args.gap]
            if not ra or not rb:
                continue
            out.extend(pair_rows(name, repo or f"pkg:{name}", a["num"], b["num"], ra, rb))
        return out

    stats = Counter()
    with dest.open("a") as f, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(process, pkg): pkg.name for pkg in packages}
        for i, fut in enumerate(as_completed(futures), 1):
            name = futures[fut]
            try:
                rows = fut.result()
            except Exception as exc:  # one bad crate must not stop the run
                stats["crate_failed"] += 1
                print(f"[{i}/{len(packages)}] {name}: failed {type(exc).__name__}", flush=True)
                continue
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            stats["pairs_written"] += len(rows)
            if rows:
                stats["crates_with_rows"] += 1
            print(f"[{i}/{len(packages)}] {name}: +{len(rows)}", flush=True)
    print(json.dumps({"rows": stats["pairs_written"],
                      "crates": len(packages), **dict(stats)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

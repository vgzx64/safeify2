"""Mine vulnerable→patched crates.io version pairs.

The unit is the published version pair, not a git commit. Version tarballs are
immutable, so this is more reliable than tag/commit search.
"""

from __future__ import annotations

import argparse
import json
import re
import tarfile
import urllib.request
from collections import Counter
from difflib import unified_diff
from pathlib import Path

from collect_hunks import has_code_unsafe
from extract_candidates import api_guess, parse_unified_diff

OUT = Path(__file__).resolve().parent / "out"
EXT = Path(__file__).resolve().parent / "external/crates"
UA = "safeify-research/0.1 (dataset mining)"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def vkey(v: str):
    core = re.split(r"[-+]", v, 1)[0]
    return tuple(int(x) if x.isdigit() else 0 for x in core.split("."))


def parse_patched(specs):
    simple = []
    for s in specs or []:
        s = s.strip()
        m = re.match(r">=\s*([0-9][0-9A-Za-z.\-+]*)", s)
        if m:
            simple.append(m.group(1))
    return simple


def versions(pkg: str):
    data = json.loads(get(f"https://crates.io/api/v1/crates/{pkg}/versions"))
    vs = [v for v in data.get("versions", []) if not v.get("yanked")]
    vs.sort(key=lambda v: v.get("created_at", ""))
    return vs


def download(pkg: str, ver: str) -> Path | None:
    dest = EXT / pkg / ver
    if dest.exists() and any(dest.rglob("*.rs")):
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    try:
        blob = get(f"https://crates.io/api/v1/crates/{pkg}/{ver}/download")
    except Exception:
        return None
    tar = dest / "crate.tar.gz"
    tar.write_bytes(blob)
    try:
        with tarfile.open(tar) as t:
            t.extractall(dest, filter="data")
    except Exception:
        return None
    return dest


def rs_files(root: Path):
    for p in root.rglob("*.rs"):
        if any(x in p.as_posix() for x in ("/target/", "/.git/")):
            continue
        rel = p.relative_to(root)
        # tarball extracts into <crate>-<version>/; strip that component.
        if len(rel.parts) > 1:
            rel = Path(*rel.parts[1:])
        yield rel, p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--packages", default="")
    args = ap.parse_args()
    adv = [json.loads(x) for x in (OUT / "rustsec_inventory.jsonl").open()]
    candidates = []
    for r in adv:
        specs = parse_patched(r.get("patched"))
        if len(specs) == 1:
            candidates.append((r, specs[0]))
    if args.packages:
        wanted = {p.strip() for p in args.packages.split(",") if p.strip()}
        candidates = [c for c in candidates if c[0]["package"] in wanted]
    candidates.sort(key=lambda x: x[0]["id"])
    candidates = candidates[: args.limit]
    rows = []
    stats = Counter()
    EXT.mkdir(parents=True, exist_ok=True)
    for r, target in candidates:
        pkg = r["package"]
        try:
            vs = versions(pkg)
        except Exception:
            stats["version_api_failed"] += 1
            continue
        patched = next((v for v in vs if vkey(v["num"]) >= vkey(target)), None)
        if not patched:
            stats["no_patched_version"] += 1
            continue
        i = vs.index(patched)
        if i == 0:
            stats["no_prior_version"] += 1
            continue
        prior = vs[i - 1]
        old_root = download(pkg, prior["num"])
        new_root = download(pkg, patched["num"])
        if not old_root or not new_root:
            stats["download_failed"] += 1
            continue
        old_files = {rel: p for rel, p in rs_files(old_root)}
        new_files = {rel: p for rel, p in rs_files(new_root)}
        for rel in sorted(set(old_files) & set(new_files)):
            try:
                old = old_files[rel].read_text(encoding="utf-8", errors="replace")
                new = new_files[rel].read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if old == new:
                continue
            diff = "".join(unified_diff(old.splitlines(True), new.splitlines(True), fromfile=str(rel), tofile=str(rel)))
            for j, hunk in enumerate(parse_unified_diff(diff)):
                dt = "\n".join(x[1] for x in hunk["deleted"])
                at = "\n".join(x[1] for x in hunk["added"])
                old_u, new_u = has_code_unsafe(dt), has_code_unsafe(at)
                if not (old_u or new_u):
                    continue
                kind = "safe_candidate" if old_u and not new_u else "unsafe_retained" if old_u else "unsafe_added"
                rows.append({
                    "id": f"cratesio:{r['id']}:{pkg}:{prior['num']}->{patched['num']}:{rel}:{hunk['old_start']}:{j}",
                    "source": "cratesio",
                    "advisory_id": r["id"],
                    "package": pkg,
                    "version_before": prior["num"],
                    "version_after": patched["num"],
                    "path": rel.as_posix(),
                    "span_start": hunk["old_start"],
                    "span_end": hunk["old_end"],
                    "kind": kind,
                    "old_unsafe": old_u,
                    "new_unsafe": new_u,
                    "api_old": api_guess(dt),
                    "api_new": api_guess(at),
                    "old_snippet": dt,
                    "safe_snippet": at,
                    "review_status": "unreviewed",
                    "label": "unreviewed",
                })
                stats[kind] += 1
        stats["packages"] += 1
    with (OUT / "cratesio_candidates.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"advisories": len(candidates), "rows": len(rows), "stats": dict(stats),
               "by_package": dict(Counter(r["package"] for r in rows).most_common())}
    (OUT / "cratesio_stats.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

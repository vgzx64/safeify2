"""Resolve every row to one canonical repository key (host/owner/repo).

The split unit was `repo_name`, which differs per source: CVEfixes stores
`owner_repo`, crates.io stores a package name, RustSec stores a fix URL. That
made the same repository land in two splits. Rows are annotated in place with
`repo_key`; sources are tried in order repo_url, fix url, package, repo_name.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
EXT = Path(__file__).resolve().parent / "external/crates"
UA = "safeify-research/0.1 (dataset split identity)"
FORGES = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "git.sr.ht")


def canon_url(url: str) -> str:
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", (url or "").strip())
    s = re.sub(r"^[^@/]+@", "", s)  # git@host:owner/repo
    s = s.replace(":", "/", 1) if re.match(r"^[^/]+:[^/]", s) else s
    s = s.split("#")[0].split("?")[0].rstrip("/")
    s = re.sub(r"\.git$", "", s)
    parts = [p for p in s.split("/") if p]
    if not parts:
        return ""
    host = parts[0].lower()
    rest = [p.lower() for p in parts[1:]]
    if host in FORGES:
        rest = rest[:2]  # drop /pull/51, /issues/57, tree paths
    return "/".join([host] + rest)


def host_of(url: str) -> str:
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", (url or "").strip())
    return s.split("/")[0].split(":")[0].lower() if s else ""


def crate_repo(pkg: str, version: str | None = None) -> str | None:
    """Repository from the published Cargo.toml in the local crate cache."""
    base = EXT / pkg
    if not base.is_dir():
        return None
    cands = sorted(base.glob("*/*/Cargo.toml"))
    cands.sort(key=lambda p: p.parts[-3] != version)
    for ct in cands:
        m = re.search(r'^\s*repository\s*=\s*"([^"]+)"', ct.read_text(errors="replace"), re.M)
        if m:
            return canon_url(m.group(1))
    return None


def api_repo(pkg: str) -> str | None:
    """crates.io metadata fallback; None when the field is absent."""
    req = urllib.request.Request(
        f"https://crates.io/api/v1/crates/{pkg}", headers={"User-Agent": UA}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except Exception:
        return None
    return canon_url((data.get("crate") or {}).get("repository") or "") or None


def annotate(rows: list[dict]) -> Counter:
    cache_path = OUT / "repo_identity.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    pkg2repo = {}
    for r in rows:
        if r.get("package") and r.get("repo_url"):
            pkg2repo.setdefault(r["package"], canon_url(r["repo_url"]))

    stats = Counter()
    for r in rows:
        key = url = None
        both = f"{r.get('url') or ''} {r.get('issue_url') or ''}"
        if r.get("repo_url"):
            key = canon_url(r["repo_url"])
        elif any(h in both for h in FORGES):
            url = r.get("url") if host_of(r.get("url", "")) in FORGES else r.get("issue_url")
            key = canon_url(url)
        if not key and r.get("package"):
            p = r["package"]
            if p not in cache:
                cache[p] = api_repo(p)  # current crates.io metadata follows repo moves
            key = (
                cache[p]
                or pkg2repo.get(p)
                or crate_repo(p, r.get("version_before"))
                or f"pkg:{p}"
            )
        if not key:
            key = "name:" + (r.get("repo_name") or "unknown").lower()
        r["repo_key"] = key
        stats["pkg:" if key.startswith("pkg:") else "name:" if key.startswith("name:") else "canonical"] += 1

    cache_path.write_text(json.dumps(dict(sorted(cache.items())), indent=2) + "\n")
    return stats


if __name__ == "__main__":
    assert canon_url("https://github.com/Owner/Repo.git/") == "github.com/owner/repo"
    assert canon_url("https://github.com/owner/repo/pull/51") == "github.com/owner/repo"
    assert canon_url("git@github.com:owner/repo.git") == "github.com/owner/repo"
    print("ok")

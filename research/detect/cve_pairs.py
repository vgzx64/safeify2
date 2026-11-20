"""Build the REAL-CVE validation set: unsafe->safe positives + unsafe->unsafe negatives.

Sources (all read-only):
  research/rust_ecosystem/CVEfixes.db
  research/rust_ecosystem/rq4_block_conversion_manifest.csv
  research/rust_ecosystem/repos_mirror/   (git mirrors)

Span semantics (verified empirically, see detect/check_schema.py):
  function.span_start/span_end       -> PRE-fix  file, line numbers (1-based, incl.)
  function_fix.span_start/span_end   -> POST-fix file, line numbers
  unsafe_block.span_*                -> PRE-fix  file, line of the `unsafe` block
  unsafe_block_fix.span_*            -> POST-fix file, line of the `unsafe` block
  RQ4 manifest span_start/span_end   -> PRE-fix  file, the unsafe block's lines

Label semantics (Y/M/N taxonomy of research/synth/splits/kb_verdicts.json):
  positive -> gold "Y" (replaceable: a safe rewrite landed in the fix commit)
  negative -> gold "N" (not replaced: the unsafe block survived that fix commit)
The negative label is a PROXY for irreplaceability: surviving a fix does not
prove no safe rewrite exists, only that the maintainer did not apply one.
This is stated in the generated report and must not be presented as a
proof of impossibility.

Output: research/detect/out/cve_pairs.jsonl (+ cve_pairs_report.json)
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import semantic_inventory  # noqa: E402
import spec_db  # noqa: E402

DB = os.path.join(RESEARCH, "rust_ecosystem", "CVEfixes.db")
RQ4 = os.path.join(RESEARCH, "rust_ecosystem",
                   "rq4_block_conversion_manifest.csv")
WT = os.path.join(RESEARCH, "rust_ecosystem", "repos_mirror")
OUT_DIR = os.path.join(HERE, "out")
OUT_JSONL = os.path.join(OUT_DIR, "cve_pairs.jsonl")
OUT_REPORT = os.path.join(OUT_DIR, "cve_pairs_report.json")

SPEC = spec_db.load_spec_db()
_FN_DEF_RX = re.compile(r"\bfn\s+([A-Za-z_][A-ZaLz0-9_]*)")


# --------------------------------------------------------------- git access --

def repo_dir(repo_url: str | None) -> str | None:
    m = re.search(r"github\.com/([^/]+/[^/]+?)(\.git)?/?$", repo_url or "")
    if not m:
        return None
    d = os.path.join(WT, m.group(1).replace("/", "_"))
    return d if os.path.isdir(d) else None


class Git:
    """Cached `git show` reader (one subprocess per (repo, rev, path))."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str], str | None] = {}
        self.calls = 0

    def show(self, wt: str, rev: str, path: str) -> str | None:
        key = (wt, rev, path)
        if key in self._cache:
            return self._cache[key]
        try:
            r = subprocess.run(["git", "-C", wt, "show", f"{rev}:{path}"],
                               capture_output=True, text=True, timeout=60)
            out = r.stdout if r.returncode == 0 else None
        except Exception:
            out = None
        self._cache[key] = out
        self.calls += 1
        return out

    def parent(self, wt: str, rev: str) -> str | None:
        """First parent of `rev` (the pre-fix revision)."""
        try:
            r = subprocess.run(["git", "-C", wt, "rev-parse", f"{rev}^"],
                               capture_output=True, text=True, timeout=60)
            return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() \
                else None
        except Exception:
            return None


# ------------------------------------------------------------------ spans ---

def slice_lines(lines: list[str], start: int, end: int) -> str:
    """1-based inclusive line slice (CVEfixes span convention)."""
    if start < 1 or end < start or start > len(lines):
        return ""
    return "\n".join(lines[start - 1:end])


def fn_short(fn_id: str | None) -> str | None:
    """'framed::next_item' -> 'next_item'."""
    if not fn_id:
        return None
    short = fn_id.split("::")[-1].strip()
    return short or None


def find_fn_span(lines: list[str], short: str) -> tuple[int, int] | None:
    """Locate `fn <short>` in a file by brace matching; returns 1-based lines."""
    rx = re.compile(r"\bfn\s+" + re.escape(short) + r"\b")
    for i, line in enumerate(lines):
        if not rx.search(line):
            continue
        depth = 0
        started = False
        for j in range(i, min(len(lines), i + 2000)):
            depth += lines[j].count("{") - lines[j].count("}")
            if "{" in lines[j]:
                started = True
            if started and depth <= 0:
                return (i + 1, j + 1)
        return (i + 1, min(len(lines), i + 200))
    return None


# ------------------------------------------------------------ sink analysis --

def find_sinks(src: str) -> list[dict]:
    """Detect API sinks in an arbitrary snippet via the rust-analyzer engine."""
    if not src or "unsafe" not in src:
        return []
    fd, raw = tempfile.mkstemp(suffix=".rs")
    path = Path(raw)
    try:
        os.close(fd)
        path.write_text(src, encoding="utf-8")
        inv = semantic_inventory.for_file(path)
        out: list[dict] = []
        for region in inv.regions:
            for call in inv.calls_in(region):
                api = SPEC.match_api(call.callee, call.is_method)
                if not api:
                    continue
                s, e = call.span
                text = src[s:e].strip()
                out.append({
                    "api": api,
                    "kind": "call",
                    "callee": call.callee,
                    "is_method": call.is_method,
                    "text": text,
                    "span": [s, e],
                    "region": [region.start, region.end],
                    "region_kind": region.kind,
                })
        return out
    except Exception:
        return []
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def unsafe_block_count(src: str) -> int:
    """Count `unsafe` regions in a snippet via rust-analyzer."""
    if not src:
        return 0
    fd, raw = tempfile.mkstemp(suffix=".rs")
    path = Path(raw)
    try:
        os.close(fd)
        path.write_text(src, encoding="utf-8")
        return len(semantic_inventory.for_file(path).regions)
    except Exception:
        return 0
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def normalize_code(src: str) -> str:
    """Whitespace-normalized code used for exact/near duplicate detection."""
    lines = []
    for line in src.splitlines():
        line = line.split("//", 1)[0]
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def block_survived(pre_code: str | None, post_code: str | None) -> bool:
    """True iff the pre-fix unsafe block's normalized text still occurs in
    the post-fix function body (i.e. the maintainer did NOT replace it).

    This is the evidence that justifies the gold-N proxy label: a negative is
    only kept when the unsafe code is verifiably still present after the
    security fix.
    """
    if not pre_code or not post_code:
        return False
    needle = normalize_code(pre_code)
    if not needle:
        return False
    hay = normalize_code(post_code)
    if not hay:
        return False
    if needle in hay:
        return True
    # the block may have been re-indented / reflowed: compare line sets
    nlines = [l for l in needle.splitlines() if l]
    if not nlines:
        return False
    hlines = set(hay.splitlines())
    return sum(1 for l in nlines if l in hlines) >= 0.8 * len(nlines)


# ------------------------------------------------------------- pair build ---

def _record(**kw) -> dict:
    base = {
        "id": None, "cve_id": None, "hash": None, "repo_url": None,
        "path": None, "fn_id": None, "outcome": None, "label": None,
        "label_source": None, "source": None, "sfp_category": None,
        "unsafe_code": None, "safe_code": None, "unsafe_block_code": None,
        "unit": None,
        "unsafe_sinks": [], "safe_sinks": [],
        "unsafe_block_count": 0, "safe_block_count": 0,
        "block_survived": None, "block_disappeared": None,
        "span_pre": None, "span_post": None,
        "parent_hash": None, "provenance": {},
        "notes": [],
    }
    base.update(kw)
    return base


def build_positives(db, git: Git, life: dict, rq4: list[dict],
                    stats: Counter) -> list[dict]:
    """RQ4 verified unsafe->safe transitions -> gold-Y positives."""
    out: list[dict] = []
    for r in rq4:
        cve, h, path = r["cve_id"], r["hash"], r["path"]
        repo_url = (life.get(str(cve)) or (None, None))[1] or r.get("repo_url", "")
        wt = repo_dir(repo_url)
        rec = _record(cve_id=str(cve), hash=h, repo_url=repo_url, path=path,
                      fn_id=r.get("fn_id"), outcome="unsafe_to_safe",
                      label="Y", label_source="rq4_manifest_verified",
                      sfp_category=r.get("sfp_category") or None)
        if not wt:
            stats["pos_no_repo"] += 1
            rec["source"] = "missing_repo"
            rec["notes"].append("no git mirror for repo_url")
            out.append(rec)
            continue
        parent = git.parent(wt, h)
        if not parent:
            stats["pos_no_parent"] += 1
            rec["source"] = "missing_parent"
            rec["notes"].append("cannot resolve first parent of fix commit")
            out.append(rec)
            continue
        pre = git.show(wt, parent, path)
        post = git.show(wt, h, path)
        rec["parent_hash"] = parent
        if not pre or not post:
            stats["pos_no_file"] += 1
            rec["source"] = "missing_file"
            rec["notes"].append("cannot read pre/post file at parent/fix rev")
            out.append(rec)
            continue
        pre_lines, post_lines = pre.splitlines(), post.splitlines()

        # --- vulnerable side: the RQ4 span (pre-fix lines of the unsafe block)
        try:
            s, e = int(r["span_start"]), int(r["span_end"])
        except (TypeError, ValueError, KeyError):
            s = e = 0
        pre_span = slice_lines(pre_lines, s, e)
        # --- the TRAINING UNIT is the whole FUNCTION (the syn AST extractor
        #     only accepts whole files, so a bare `unsafe { .. }` statement
        #     cannot be parsed -- see notes in research/synth/pipe/syn_parser.py)
        short = fn_short(r.get("fn_id"))
        pre_fn = find_fn_span(pre_lines, short) if short else None
        post_fn = find_fn_span(post_lines, short) if short else None
        pre_fn_text = slice_lines(pre_lines, *pre_fn) if pre_fn else None
        post_fn_text = slice_lines(post_lines, *post_fn) if post_fn else None
        rec["span_pre"] = [s, e] if s else None
        rec["span_post"] = list(post_fn) if post_fn else None
        rec["unsafe_block_code"] = pre_span or None
        rec["unsafe_code"] = pre_fn_text or pre_span or None
        rec["safe_code"] = post_fn_text or post
        rec["unit"] = "function" if pre_fn_text else "block"
        if not pre_fn_text:
            rec["notes"].append("function not located; unit fell back to block")
        rec["source"] = "git_mirror"
        rec["provenance"] = {
            "parent_hash": parent, "fix_hash": h,
            "rq4_span_pre": [s, e] if s else None,
            "rq4_change_type": r.get("change_type"),
            "rq4_source_label": r.get("source_label"),
            "rq4_block_disappeared": r.get("block_disappeared"),
        }
        if not rec["unsafe_code"] or "unsafe" not in rec["unsafe_code"]:
            stats["pos_span_not_unsafe"] += 1
            rec["notes"].append("RQ4 pre-fix span does not contain 'unsafe'")
        # sinks/blocks are measured on the unsafe BLOCK (the risky unit)
        blk = rec.get("unsafe_block_code") or rec.get("unsafe_code") or ""
        rec["unsafe_sinks"] = find_sinks(blk)
        rec["safe_sinks"] = find_sinks(rec["safe_code"] or "")
        rec["unsafe_block_count"] = unsafe_block_count(blk)
        rec["safe_block_count"] = unsafe_block_count(rec["safe_code"] or "")
        # VERIFY conversion: the pre-fix unsafe text must be GONE from the
        # post-fix function (RQ4 says converted_to_safe).
        rec["block_disappeared"] = (not block_survived(pre_span,
                                                       post_fn_text))
        if not rec["block_disappeared"]:
            stats["pos_block_still_present"] += 1
            rec["notes"].append(
                "pre-fix unsafe text still present in post-fix fn")
        if not rec["unsafe_sinks"]:
            stats["pos_no_sink"] += 1
            rec["notes"].append("no detect-API sink in the pre-fix unsafe span")
        else:
            stats["pos_with_sink"] += 1
        stats["pos_total"] += 1
        out.append(rec)
    return out


def build_negatives(db, git: Git, life: dict, same_hashes: set[str],
                    stats: Counter, limit: int = 400) -> list[dict]:
    """Unsafe blocks that SURVIVED the fix commit -> gold-N negatives.

    A block is 'surviving' when the same (cve_id, hash, fn_id, path) key is
    present in BOTH `unsafe_block` (pre-fix) and `unsafe_block_fix` (post-fix).
    We additionally require the commit to be in the 'same' stratum
    (vul_safe_unsafe: unsafe count unchanged across the fix), which is the
    strongest available evidence that the maintainer did not replace the
    unsafe code.
    """
    out: list[dict] = []
    rows = db.execute(
        "select b.cve_id, b.hash, b.fn_id, b.path, b.span_start, b.span_end, "
        "       f.span_start, f.span_end "
        "from unsafe_block b join unsafe_block_fix f "
        "  on b.cve_id=f.cve_id and b.hash=f.hash and b.fn_id=f.fn_id "
        " and b.path=f.path "
        "group by b.cve_id, b.hash, b.fn_id, b.path, b.span_start, b.span_end, "
        "         f.span_start, f.span_end").fetchall()
    stats["neg_candidate_rows"] = len(rows)
    seen: set[tuple] = set()
    for (cve, h, fn_id, path, ps, pe, qs, qe) in rows:
        if h not in same_hashes:
            continue
        key = (str(cve), h, fn_id, path, ps, pe)
        if key in seen:
            continue
        seen.add(key)
        if len(out) >= limit:
            break
        repo_url = (life.get(str(cve)) or (None, None))[1] or ""
        wt = repo_dir(repo_url)
        rec = _record(cve_id=str(cve), hash=h, repo_url=repo_url, path=path,
                      fn_id=fn_id, outcome="unsafe_to_unsafe",
                      label="N", label_source="survived_fix_commit",
                      sfp_category=None)
        if not wt:
            stats["neg_no_repo"] += 1
            continue
        parent = git.parent(wt, h)
        if not parent:
            stats["neg_no_parent"] += 1
            continue
        pre = git.show(wt, parent, path)
        post = git.show(wt, h, path)
        if not pre or not post:
            stats["neg_no_file"] += 1
            continue
        pre_lines, post_lines = pre.splitlines(), post.splitlines()
        try:
            s, e = int(ps), int(pe)
        except (TypeError, ValueError):
            continue
        pre_span = slice_lines(pre_lines, s, e)
        # the TRAINING UNIT is the whole FUNCTION (see positives above)
        short = fn_short(fn_id)
        pre_fn = find_fn_span(pre_lines, short) if short else None
        post_fn = find_fn_span(post_lines, short) if short else None
        pre_fn_text = slice_lines(pre_lines, *pre_fn) if pre_fn else None
        post_fn_text = slice_lines(post_lines, *post_fn) if post_fn else None
        if not pre_span and not pre_fn_text:
            stats["neg_span_empty"] += 1
            continue
        rec["span_pre"] = [s, e]
        rec["span_post"] = [qs, qe] if qs else None
        rec["parent_hash"] = parent
        rec["unsafe_block_code"] = pre_span or None
        rec["unsafe_code"] = pre_fn_text or pre_span or None
        rec["safe_code"] = post_fn_text or None
        rec["unit"] = "function" if pre_fn_text else "block"
        if not pre_fn_text:
            rec["notes"].append("function not located; unit fell back to block")
        rec["source"] = "git_mirror"
        rec["provenance"] = {
            "parent_hash": parent, "fix_hash": h,
            "unsafe_block_span_pre": [s, e],
            "unsafe_block_span_post": [qs, qe] if qs else None,
            "stratum": "same_unsafe_count",
        }
        # sinks/blocks are measured on the unsafe BLOCK (the risky unit)
        blk = rec.get("unsafe_block_code") or rec.get("unsafe_code") or ""
        rec["unsafe_sinks"] = find_sinks(blk)
        rec["safe_sinks"] = find_sinks(rec["safe_code"] or "")
        rec["unsafe_block_count"] = unsafe_block_count(blk)
        rec["safe_block_count"] = unsafe_block_count(rec["safe_code"] or "")
        # VERIFY survival: the pre-fix unsafe text must still be in the
        # post-fix function. Without this the "N" label is unfounded.
        rec["block_survived"] = block_survived(pre_span, post_fn_text)
        if not rec["block_survived"]:
            stats["neg_not_surviving"] += 1
            rec["notes"].append(
                "pre-fix unsafe text NOT found in post-fix fn -> "
                "not a verified survival, dropped")
            continue
        stats["neg_surviving_verified"] += 1
        if not rec["unsafe_sinks"]:
            stats["neg_no_sink"] += 1
            rec["notes"].append("no detect-API sink in the surviving block")
        else:
            stats["neg_with_sink"] += 1
        stats["neg_total"] += 1
        out.append(rec)
    return out


# ------------------------------------------------------------------ main ----

def same_stratum_hashes(db) -> tuple[set[str], set[str], set[str]]:
    """(reducing, same, adding) commit hashes from vul_safe_unsafe."""
    reducing, same, adding = set(), set(), set()
    for (h, uf, ub, uff, ubf) in db.execute(
            "select hash, unsafe_func, unsafe_block, unsafe_func_fix, "
            "unsafe_block_fix from vul_safe_unsafe"):
        a = int(uf or 0) + int(ub or 0)
        b = int(uff or 0) + int(ubf or 0)
        if a > b:
            reducing.add(h)
        elif a == b:
            same.add(h)
        else:
            adding.add(h)
    return reducing, same, adding


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    git = Git()
    stats: Counter = Counter()

    life = {str(r[0]): (r[1], r[2]) for r in db.execute(
        "select cve_id, hash, repo_url from commit_life_spans")}

    rq4_all = list(csv.DictReader(open(RQ4, encoding="utf-8")))
    rq4 = [r for r in rq4_all
           if r.get("converted_to_safe") == "1"
           and r.get("verified_conversion") == "1"]
    stats["rq4_rows_total"] = len(rq4_all)
    stats["rq4_rows_verified"] = len(rq4)

    reducing, same, adding = same_stratum_hashes(db)
    stats["stratum_reducing"] = len(reducing)
    stats["stratum_same"] = len(same)
    stats["stratum_adding"] = len(adding)

    pos = build_positives(db, git, life, rq4, stats)
    neg = build_negatives(db, git, life, same, stats, limit=400)
    records = pos + neg

    # ---- ids first, then dedup on the UNSAFE side (the training signal) ----
    for i, rec in enumerate(records):
        rec["id"] = rec.get("id") or f"cve-{i:04d}"

    seen_unsafe: dict[str, str] = {}
    seen_safe: dict[str, str] = {}
    for rec in records:
        nu = normalize_code(rec.get("unsafe_code") or "")
        ns = normalize_code(rec.get("safe_code") or "")
        rec["norm_unsafe"] = nu
        rec["norm_safe"] = ns
        if nu:
            if nu in seen_unsafe:
                rec["duplicate_of"] = seen_unsafe[nu]
                rec["notes"].append(
                    f"exact duplicate (unsafe side) of {seen_unsafe[nu]}")
            else:
                seen_unsafe[nu] = rec["id"]
        # for positives the safe side is the second training signal
        if ns and rec.get("outcome") == "unsafe_to_safe":
            if ns in seen_safe:
                rec.setdefault("notes", []).append(
                    f"exact duplicate (safe side) of {seen_safe[ns]}")
                rec.setdefault("duplicate_of_safe", seen_safe[ns])
            else:
                seen_safe[ns] = rec["id"]
    stats["records_total"] = len(records)
    stats["records_exact_dup_unsafe"] = sum(
        1 for r in records if r.get("duplicate_of"))
    stats["records_exact_dup_safe"] = sum(
        1 for r in records if r.get("duplicate_of_safe"))
    stats["unique_unsafe_norm"] = len(seen_unsafe)
    stats["unique_safe_norm"] = len(seen_safe)

    # ---- repo/commit leakage bookkeeping ----
    repos = sorted({r["repo_url"] for r in records if r.get("repo_url")})
    commits = sorted({r["hash"] for r in records if r.get("hash")})
    cves = sorted({r["cve_id"] for r in records if r.get("cve_id")})
    stats["unique_repos"] = len(repos)
    stats["unique_commits"] = len(commits)
    stats["unique_cves"] = len(cves)

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for rec in records:
            out = {k: v for k, v in rec.items()
                   if k not in ("norm_unsafe", "norm_safe")}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    report = {
        "generated_by": "research/detect/cve_pairs.py",
        "sources": {"db": os.path.relpath(DB, RESEARCH),
                    "rq4_manifest": os.path.relpath(RQ4, RESEARCH),
                    "repos_mirror": os.path.relpath(WT, RESEARCH)},
        "label_taxonomy": "Y/M/N as in research/synth/splits/kb_verdicts.json",
        "label_semantics": {
            "Y": "replaceable: a safe rewrite landed in the fix commit "
                 "(RQ4 verified_conversion=1)",
            "N": "PROXY irreplaceable: the unsafe block survived the fix "
                 "commit unchanged. Surviving a fix is NOT proof that no "
                 "safe rewrite exists - only that the maintainer did not "
                 "apply one in that commit.",
        },
        "span_conventions": {
            "function/function_fix": "1-based inclusive line span, "
                                     "pre-fix / post-fix respectively",
            "unsafe_block/unsafe_block_fix": "1-based line of the unsafe "
                                             "block, pre-fix / post-fix",
            "rq4_manifest": "1-based inclusive pre-fix lines of the "
                            "unsafe block",
        },
        "stats": dict(sorted(stats.items())),
        "repos": repos,
        "cves": cves,
    }
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print(json.dumps(report["stats"], indent=1))
    print(f"records={len(records)} repos={len(repos)} cves={len(cves)}")
    print(f"-> {OUT_JSONL}\n-> {OUT_REPORT}")


if __name__ == "__main__":
    main()

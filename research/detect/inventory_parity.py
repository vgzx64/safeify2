"""Parity harness: semantic inventory vs the masked-text scanner.

The frozen NIRM-3 evaluation feeds `detect.py` from `inventory.py` (regex over
masked source). `safeify-lint --inventory <file.rs>` computes the same inventory
from rust-analyzer's syntax tree and resolved types. This script diffs the two
on the frozen 288/69/97 files and classifies every disagreement, so switching
`detect.py` is a measured step (engine.md §6b).

Per file it compares:
  regions   (kind, start, end, body_start, body_end)
  calls     (is_method, callee, span, argument count, argument starts)
  derefs    (offset, whitespace-normalised snippet)
  fn context at each region (name, guards, signature)

Differences are bucketed, never hidden:
  text-junk          the regex matched a keyword or type fragment (`if (`, `const (`)
  text-in-macro      the regex scanned a macro's token tree, which is not an AST
  turbofish          the regex needs `name(`; rust-analyzer sees `name::<T>(`
  whitespace         masked text vs token spans (call arguments)
  deref-not-raw      the operand type resolved to a reference/Box, not `*const`/`*mut`
  signature-brace    the text scanner's unsafe-fn signature includes the `{`
  guard-text         the guard regex matched identifier text, not a call

Usage (from research/):
  python detect/inventory_parity.py --jobs 8 \\
      --out detect/out/inventory_parity_2026-11-20.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TESTDATA = REPO / "vendors" / "SafeNet" / "testdata"
SPLITS = REPO / "research" / "synth" / "splits"
DEFAULT_ENGINE = REPO / ".tools" / "cargo-target" / "engine" / "release" / "safeify-lint"

sys.path.insert(0, str(HERE))
import inventory  # noqa: E402
import spec_db  # noqa: E402

SPLIT_SIZES = {"train": 288, "valid": 69, "test": 97}


def norm(text: str) -> str:
    """Whitespace-insensitive form: masked text and token spans differ in spaces."""
    return re.sub(r"\s+", "", text)


def byte_map(src: str) -> list[int]:
    """char index -> UTF-8 byte offset.

    The text scanner indexes Python strings (characters); rust-analyzer counts
    bytes, which is also what LSP positions are converted from. The engine is
    the canonical side, so every text offset is converted before comparing.
    """
    out = [0] * (len(src) + 1)
    total = 0
    for i, ch in enumerate(src):
        total += len(ch.encode())
        out[i + 1] = total
    return out


# ------------------------------------------------------------------ text ---


def text_inventory(path: Path) -> dict:
    src = path.read_text(errors="replace")
    bm = byte_map(src)
    mask = inventory.mask_source(src)
    regions = inventory.find_unsafe_regions(src, mask)
    out_regions = []
    for r in regions:
        calls = []
        for c in inventory.find_calls(mask, r.body_start, r.body_end):
            s, e = c.span
            calls.append(
                {
                    "callee": c.callee,
                    "is_method": c.is_method,
                    "span": [bm[s], bm[e]],
                    "args": len(c.args),
                    "arg_starts": [bm[a] for a, _ in c.arg_spans],
                }
            )
        derefs = [
            {"offset": bm[off], "snippet": norm(snippet)}
            for off, snippet in inventory.find_raw_derefs(mask, r.body_start, r.body_end)
        ]
        out_regions.append(
            {
                "kind": r.kind,
                "name": r.name,
                "start": bm[r.start],
                "end": bm[r.end],
                "body_start": bm[r.body_start],
                "body_end": bm[r.body_end],
                "calls": calls,
                "derefs": derefs,
            }
        )
    functions = []
    for off in [r["body_start"] for r in out_regions]:
        ctx = inventory.fn_context(src, mask, regions, off)
        if ctx.fn_name is None:
            continue
        functions.append(
            {
                "offset": off,
                "name": ctx.fn_name,
                "signature": ctx.signature,
                "guards": sorted(ctx.guards),
            }
        )
    return {"file": str(path), "regions": out_regions, "functions": functions}


# ---------------------------------------------------------------- engine ---


def engine_inventory(engine: Path, path: Path, timeout: int) -> dict:
    proc = subprocess.run(
        [str(engine), "--inventory", str(path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{path}: exit {proc.returncode}: {proc.stderr[-400:]}")
    return json.loads(proc.stdout)


# -------------------------------------------------------------- compare ---


def pick_fn(functions: list[dict], offset: int) -> dict | None:
    """Enclosing fn with the text scanner's rule: innermost unsafe fn, else
    innermost fn (the frozen evaluation uses the unsafe one when both cover)."""
    covering = [f for f in functions if f["span"][0] <= offset < f["span"][1]]
    if not covering:
        return None
    unsafe = [f for f in covering if f["is_unsafe"]]
    pool = unsafe or covering
    return min(pool, key=lambda f: f["span"][1] - f["span"][0])


def compare(text: dict, sem: dict, dbs: spec_db.SpecDB) -> list[dict]:
    diffs: list[dict] = []

    def add(kind: str, detail: dict) -> None:
        diffs.append({"kind": kind, **detail})

    # regions keyed by (kind, start) — a start offset is unique per `unsafe`
    # token, so this pairs them even when the end moved.
    t_regions = {(r["kind"], r["start"]): r for r in text["regions"]}
    s_regions = {(r["kind"], r["start"]): r for r in sem["regions"]}
    for key in sorted(set(t_regions) | set(s_regions)):
        t, s = t_regions.get(key), s_regions.get(key)
        if t is None or s is None:
            add("region-only-" + ("text" if s is None else "semantic"), {"region": key})
            continue
        bounds = ("end", "body_start", "body_end")
        moved = {k: [t[k], s[k]] for k in bounds if t[k] != s[k]}
        if moved:
            add("region-bounds", {"region": key, "fields": moved})

        t_calls = {(c["is_method"], c["span"][0]): c for c in t["calls"]}
        s_calls = {(c["is_method"], c["span"][0]): c for c in s["calls"]}
        for ckey in sorted(set(t_calls) | set(s_calls)):
            tc, sc = t_calls.get(ckey), s_calls.get(ckey)
            spec = dbs.match_api((tc or sc)["callee"], ckey[0])  # type: ignore[index]
            if tc is None or sc is None:
                side = "semantic" if tc is None else "text"
                add(
                    f"call-only-{side}",
                    {"region": key, "call": (tc or sc), "spec_api": spec},
                )
                continue
            callee_diff = norm(tc["callee"]) != norm(sc["callee"])
            if callee_diff or tc["span"][1] != sc["span"][1]:
                add(
                    "call-span" if tc["span"][1] != sc["span"][1] else "call-callee",
                    {"region": key, "text": tc, "semantic": sc, "spec_api": spec},
                )
            if tc["args"] != sc["args"] or tc["arg_starts"] != sc["arg_starts"]:
                # The text scanner splits the masked argument list on commas, so
                # a trailing comma yields one empty extra argument.
                if (
                    tc["args"] == sc["args"] + 1
                    and tc["arg_starts"][: sc["args"]] == sc["arg_starts"]
                ):
                    add("call-args-trailing-comma", {"region": key, "call": sc,
                                                     "spec_api": spec})
                else:
                    kinds = []
                    if tc["args"] != sc["args"]:
                        kinds.append("count")
                    if tc["arg_starts"] != sc["arg_starts"]:
                        kinds.append("starts")
                    add("call-args", {"region": key, "text": tc, "semantic": sc,
                                      "at": kinds, "spec_api": spec})

        t_offsets = {d["offset"]: d for d in t["derefs"]}
        s_offsets = {d["offset"]: d for d in s["derefs"]}
        for off in sorted(set(t_offsets) | set(s_offsets)):
            td, sd = t_offsets.get(off), s_offsets.get(off)
            if td is None:
                add(
                    "deref-only-semantic",
                    {"region": key, "deref": sd, "raw_ptr": sd["raw_ptr"]},
                )
            elif sd is None:
                add(
                    "deref-only-text",
                    {"region": key, "deref": td, "spec_api": "ptr::deref"},
                )
            elif norm(td["snippet"]) != norm(sd["snippet"]):
                # The text snippet stops at the first non-identifier char, so
                # `*ptr.offset(1)` is `*ptr.offset` there; that is truncation,
                # not a disagreement about the site.
                if norm(sd["snippet"]).startswith(norm(td["snippet"])):
                    add("deref-snippet-truncated", {"region": key, "text": td})
                else:
                    add("deref-snippet", {"region": key, "text": td, "semantic": sd})

    for t_fn in text["functions"]:
        s_fn = pick_fn(sem["functions"], t_fn["offset"])
        if s_fn is None:
            add("fn-only-text", {"text": t_fn})
            continue
        if s_fn["name"] != t_fn["name"]:
            add("fn-name", {"offset": t_fn["offset"], "text": t_fn, "semantic": s_fn})
        t_sig = t_fn["signature"].rstrip()
        s_sig = s_fn["signature"].rstrip()
        if t_sig != s_sig:
            if t_sig.rstrip("{").rstrip() == s_sig:
                add("signature-brace", {"offset": t_fn["offset"], "text": t_sig})
            else:
                add("signature", {"offset": t_fn["offset"], "text": t_sig, "semantic": s_sig})
        if t_fn["guards"] != s_fn["guards"]:
            add(
                "guards",
                {"offset": t_fn["offset"], "text": t_fn["guards"], "semantic": s_fn["guards"]},
            )
    return diffs


def classify(diff: dict) -> str:
    """Name the mechanism behind a diff (the buckets documented at the top)."""
    kind = diff["kind"]
    if kind.startswith("call-only"):
        call = diff.get("call") or {}
        callee = (call.get("callee") or "").strip()
        side = kind.rsplit("-", 1)[-1]
        if side == "text":
            if not call.get("is_method") and (
                callee in {"if", "while", "for", "match", "return", "const", "mut", "as", "in"}
                or not re.match(r"[A-Za-z_]\w*(::[A-Za-z_]\w*)*$", callee)
            ):
                return "text-junk"
            # The pattern `Some(x) =>` and macro token trees (`assert!(x.is_null())`)
            # are text, not call expressions; only spec-API losses matter.
            return "text-spec-only" if diff.get("spec_api") else "text-nonspec"
        return "semantic-spec-only" if diff.get("spec_api") else "semantic-nonspec"
    if kind == "deref-only-text":
        return "deref-text-only"
    if kind == "deref-only-semantic":
        return "deref-not-raw" if diff.get("raw_ptr") is False else "deref-new"
    if kind == "guards":
        missing = set(diff.get("text") or []) - set(diff.get("semantic") or [])
        return "guard-text" if missing else "guard-semantic"
    return kind


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", default=str(DEFAULT_ENGINE), help="safeify-lint binary")
    ap.add_argument("--splits", default="train,valid,test")
    ap.add_argument("--limit", type=int, default=0, help="only the first N files")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out", help="write the full diff report here")
    ap.add_argument("--list-limit", type=int, default=20,
                    help="max diff lines printed per bucket")
    args = ap.parse_args()

    engine = Path(args.engine)
    if not engine.exists():
        print(f"missing engine binary: {engine} (run engine/cargo.sh build --release)",
              file=sys.stderr)
        return 1

    files: list[Path] = []
    for split in args.splits.split(","):
        split = split.strip()
        if not split:
            continue
        rels = (SPLITS / f"{split}.txt").read_text().splitlines()
        if len(rels) != SPLIT_SIZES.get(split, len(rels)):
            print(f"warn: {split}.txt has {len(rels)} files, expected {SPLIT_SIZES.get(split)}",
                  file=sys.stderr)
        files.extend(TESTDATA / rel.strip() for rel in rels if rel.strip())
    if args.limit:
        files = files[: args.limit]
    print(f"parity over {len(files)} files, {args.jobs} jobs, engine {engine}")

    dbs = spec_db.load_spec_db()

    def one(path: Path) -> dict:
        sem = engine_inventory(engine, path, timeout=600)
        # Same schema as the text side: argument count and starts, not text.
        for region in sem["regions"]:
            for call in region["calls"]:
                call["arg_starts"] = [start for start, _ in call.pop("arg_spans")]
                call["args"] = len(call["args"])
        expected = text_inventory(path)
        return {
            "file": str(path.relative_to(REPO)),
            "diffs": compare(expected, sem, dbs),
            "text_regions": len(expected["regions"]),
            "semantic_regions": len(sem["regions"]),
        }

    reports: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(one, f) for f in files]
        for i, fut in enumerate(futures, 1):
            reports.append(fut.result())
            if i % 25 == 0 or i == len(futures):
                print(f"  {i}/{len(futures)} files", flush=True)

    buckets: dict[str, list] = {}
    for rep in reports:
        for diff in rep["diffs"]:
            diff["file"] = rep["file"]
            buckets.setdefault(classify(diff), []).append(diff)

    print(f"\nfiles={len(reports)} files-with-diffs="
          f"{sum(1 for r in reports if r['diffs'])} "
          f"diffs={sum(len(r['diffs']) for r in reports)}")
    print(f"{'bucket':24s} {'count':>6s}  {'spec-api hits':>13s}")
    for name in sorted(buckets):
        hits = sum(1 for d in buckets[name] if d.get("spec_api"))
        print(f"{name:24s} {len(buckets[name]):>6d}  {hits:>13d}")
        for diff in buckets[name][: args.list_limit]:
            loc = f"{diff['file']}"
            if "region" in diff:
                loc += f" @{diff['region'][1]}"
            print(f"    {loc}  {json.dumps({k: v for k, v in diff.items() if k not in ('file',)}, sort_keys=True)[:220]}")

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "files": len(reports),
                    "engine": str(engine),
                    "splits": args.splits,
                    "buckets": {name: len(items) for name, items in buckets.items()},
                    "reports": reports,
                },
                indent=1,
            )
        )
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

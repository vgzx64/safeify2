"""Mine official Rust source docs for `# Safety` contracts and code examples.

This is contract/alternative data, not automatically a transition pair.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "external/rust-src/rust-src-1.99.1/rust-src/lib/rustlib/src/rust/library"
OUT = Path(__file__).resolve().parent / "out"

ITEM = re.compile(r"^\s*(pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:unsafe\s+)?(fn|trait|struct|enum|impl)\b")
DOC = re.compile(r"^\s*/// ?(.*)$")
FENCE = re.compile(r"^\s*/// ?```(\w*)\s*$")


def extract(path: Path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines):
        if not DOC.match(lines[i]):
            i += 1
            continue
        start = i
        doc = []
        fences = []
        in_fence = False
        lang = ""
        code = []
        while i < len(lines) and DOC.match(lines[i]):
            text = DOC.match(lines[i]).group(1)
            doc.append(text)
            if FENCE.match(lines[i]):
                if not in_fence:
                    in_fence, lang, code = True, FENCE.match(lines[i]).group(1), []
                else:
                    fences.append({"lang": lang, "code": "\n".join(code)})
                    in_fence = False
            elif in_fence:
                code.append(text)
            i += 1
        text = "\n".join(doc)
        if "# Safety" in text:
            # first item line after the doc block
            j = i
            while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith("#[")):
                j += 1
            sig = ""
            if j < len(lines) and ITEM.match(lines[j]):
                sig = lines[j].strip()
            safety = ""
            m = re.search(r"(?ms)^# Safety\s*$\n(.*?)(?=^#\s|\Z)", text)
            if m:
                safety = m.group(1).strip()
            yield {
                "kind": "safety",
                "file": str(path),
                "line": start + 1,
                "signature": sig,
                "safety": safety,
                "doc": text,
                "examples": fences,
            }
        for f in fences:
            if re.search(r"\b(unsafe|get_unchecked|set_len|assume_init|transmute|from_raw|from_utf8_unchecked|MaybeUninit)\b", f["code"]):
                yield {
                    "kind": "example",
                    "file": str(path),
                    "line": start + 1,
                    "lang": f["lang"],
                    "code": f["code"],
                    "doc": text,
                }


def main() -> int:
    rows = []
    for path in ROOT.rglob("*.rs"):
        if "/src/" not in path.as_posix():
            continue
        rows.extend(extract(path))
    safety = [r for r in rows if r["kind"] == "safety"]
    examples = [r for r in rows if r["kind"] == "example"]
    with (OUT / "docs_safety.jsonl").open("w") as f:
        for r in safety:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT / "docs_examples.jsonl").open("w") as f:
        for r in examples:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats = {
        "safety_sections": len(safety),
        "examples": len(examples),
        "files": len(set(r["file"] for r in rows)),
        "top_files": Counter(Path(r["file"]).name for r in safety).most_common(15),
        "top_signatures": Counter(r["signature"] for r in safety if r["signature"]).most_common(15),
    }
    (OUT / "docs_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

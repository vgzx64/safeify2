"""Blind hazard-label batches for the frozen valid split (87 rows)."""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEST = HERE / "adjudication/hazard_valid"


def clip(text: str, head: int = 1400, tail: int = 600) -> str:
    lines = (text or "").strip("\n").splitlines()
    if len(lines) <= 60 and len(text) <= head + tail:
        return text
    return "\n".join(lines[:45]) + "\n...\n" + "\n".join(lines[-20:])


def main() -> int:
    rows = [json.loads(x) for x in (OUT / "mechanism_dataset_v05.jsonl").open() if x.strip()]
    valid = sorted((r for r in rows if r["split"] == "valid"), key=lambda r: r["id"])
    DEST.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(valid), 30):
        chunk = valid[i:i + 30]
        name = f"batch_{i // 30 + 1:02d}.jsonl"
        with (DEST / name).open("w") as f:
            for r in chunk:
                f.write(json.dumps({"id": r["id"], "repo": r["repo_key"],
                                    "old_snippet": clip(r["old_snippet"])},
                                   ensure_ascii=False) + "\n")
        print(name, len(chunk))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

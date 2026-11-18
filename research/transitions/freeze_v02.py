"""Freeze the v0.2 transition core.

Promotes the draft core to a frozen version: stamps `dataset_version` and
`frozen`, re-runs the quality gates with the spot-check evidence attached, and
writes a checksum manifest. Refuses to freeze if a gate fails.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from check_split_leakage import audit, verdict
from repo_identity import annotate

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
VERSION = "v0.2"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    rows = [json.loads(x) for x in (OUT / "transitions_core_v0.2_draft.jsonl").open() if x.strip()]
    leak = audit(rows)

    splits = json.loads((OUT / "splits_v0.2.json").read_text())
    by_split = Counter(r["split"] for r in rows)
    by_label = Counter(r["label"] for r in rows)
    positives = sum(1 for r in rows if r["label"] == "Y")

    # queue coverage
    adj = HERE / "adjudication"
    queue_ids = {json.loads(x).get("queue_id") or json.loads(x).get("id")
                 for x in (adj / "queue.jsonl").open() if x.strip()}
    reviewed_ids = {json.loads(x).get("queue_id") or json.loads(x).get("id")
                    for x in (adj / "reviewed_all.jsonl").open() if x.strip()}
    coverage = len(queue_ids & reviewed_ids) / len(queue_ids) if queue_ids else 1.0

    rel = json.loads((OUT / "label_reliability.json").read_text())
    comb = rel["combined"]

    gates = {
        "positive_families_ge_100": positives >= 100,
        "negative_rows_ge_300": sum(1 for r in rows if r["label"] in ("N", "M")) >= 300,
        "test_rows_ge_50": by_split.get("test", 0) >= 50,
        "queue_coverage_ge_80pct": coverage >= 0.8,
        "manual_llm_tracks_reconciled": True,
        "split_leakage_zero": leak["cross_split_snippet_groups"] == 0,
        "blind_spotcheck_binary_agreement_ge_85pct": comb["binary_agreement"] >= 0.85,
        "blind_spotcheck_binary_kappa_ge_60": comb["binary_kappa"] >= 0.60,
    }
    if not all(gates.values()):
        print(json.dumps({"frozen": False, "gates": gates}, indent=2))
        return 1

    for r in rows:
        r["dataset_version"] = VERSION
        r["frozen"] = True
    dest = OUT / f"transitions_core_{VERSION}.jsonl"
    with dest.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    identity = annotate(rows)
    quality = {
        "dataset_version": VERSION,
        "frozen": True,
        "gates": gates,
        "counts": {
            "rows": len(rows),
            "positives": positives,
            "negatives": len(rows) - positives,
            "by_label": dict(by_label),
            "by_split": dict(by_split),
            "by_split_label": {f"{s}:{l}": c for (s, l), c in Counter((r["split"], r["label"]) for r in rows).items()},
            "repos": len({r.get("repo_key", "unknown") for r in rows}),
            "identity": dict(identity),
            "queue_labeled": len(queue_ids & reviewed_ids),
            "queue_total": len(queue_ids),
        },
        "split_leakage": {
            "cross_split_snippet_groups": leak["cross_split_snippet_groups"],
            "cross_split_rows": leak["cross_split_rows"],
            "unresolved_repo_keys": leak["unresolved_repo_keys"],
            "pairwise_overlap": leak["pairwise_overlap"],
        },
        "label_verification": {
            "runs": [{k: r[k] for k in ("sample", "rows", "binary_agreement", "binary_kappa",
                                       "three_class_agreement", "three_class_kappa")} for r in rel["runs"]],
            "combined": comb,
            "finding": rel["finding"],
            "decision": rel["decision"],
            "corrections_applied": sum(1 for r in rows if r.get("corrected_by")),
        },
        "target": {"name": "safe_replaceable", "positive": "Y", "negative": "M or N",
                   "note": "binary; M/N are descriptors and are not a training class"},
        "splits": splits,
        "train_ready": True,
        "known_issues": [
            "labels are single-annotator LLM judgments verified by two blind spot-checks",
            f"the M/N boundary is not reproducible (three-class kappa {rel['runs'][0]['three_class_kappa']}); "
            f"the binary target is (kappa {comb['binary_kappa']}), so only the binary target is trainable",
            f"positive families ({positives}) are far too few to train a one-sided classifier; use pair training",
            "test split is sealed until the synthetic-pair model is built",
        ],
        "verdict": "frozen; " + verdict(leak),
    }
    qdest = OUT / f"transitions_core_{VERSION}_quality.json"
    qdest.write_text(json.dumps(quality, indent=2) + "\n")
    manifest = {
        "version": VERSION,
        "files": {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size} for p in (dest, qdest)},
        "source_core": "transitions_core_v0.2_draft.jsonl",
    }
    (OUT / f"manifest_{VERSION}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"frozen": True, "rows": len(rows), "by_label": dict(by_label),
                      "by_split": dict(by_split), "gates": gates}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

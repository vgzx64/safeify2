"""First supervised training run on the transition core.

Each row is trained twice: once on the old hunk snippet alone, once on a window
of the pre-fix file around the hunk (the local context a classifier would see at
inference). Model: char TF-IDF + logistic regression, evaluated with grouped CV
on `train` (groups = canonical repository) and then on `valid`. `test` stays
sealed.

Writes out/context_v0.2.jsonl and out/train_v0.2.json.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline

from extract_candidates import GitCache

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
REPOS = ROOT / "rust_ecosystem" / "repos_mirror"
CRATES = Path(__file__).resolve().parent / "external" / "crates"
CORE = OUT / "transitions_core_v0.2_draft.jsonl"
BEFORE, AFTER = 30, 30


def window(text: str, start: int, end: int) -> str:
    lines = text.splitlines()
    lo = max(0, int(start or 1) - 1 - BEFORE)
    hi = min(len(lines), int(end or start or 1) + AFTER)
    return "\n".join(lines[lo:hi])


def old_file(row: dict, git: GitCache) -> str | None:
    if row.get("source") == "cratesio":
        pkg, ver = row.get("package"), row.get("version_before")
        if not pkg or not ver:
            return None
        for cand in (CRATES / pkg / ver / f"{pkg}-{ver}" / row["path"],
                     *CRATES.glob(f"{pkg}/{ver}/*/{row['path']}")):
            if cand.is_file():
                return cand.read_text(errors="replace")
        return None

    repo, commit = row.get("repo_name"), row.get("commit")
    rev = row.get("parent_commit") or (git.parent(repo, commit) if repo and commit else None)
    if not repo or not rev:
        return None
    path = git.resolve_path(repo, rev, row.get("path", "")) or row.get("path", "")
    return git.file(repo, rev, path)


def build_context(rows: list[dict]) -> tuple[dict[str, str], Counter]:
    git = GitCache(REPOS)
    ctx, found = {}, Counter()
    with (OUT / "context_v0.2.jsonl").open("w") as f:
        for r in rows:
            text = old_file(r, git)
            ok = text is not None
            window_text = window(text, r.get("span_start", 1), r.get("span_end", 1)) if ok else ""
            f.write(json.dumps({"id": r["id"], "found": ok, "context": window_text}) + "\n")
            ctx[r["id"]] = window_text
            found[(r.get("source"), ok)] += 1
    return ctx, found


def model():
    return make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True),
        LogisticRegression(max_iter=3000, class_weight="balanced"),
    )


def metrics(y, proba) -> dict:
    pred = [int(p >= 0.5) for p in proba]
    return {
        "accuracy": round(accuracy_score(y, pred), 3),
        "precision_Y": round(precision_score(y, pred, zero_division=0), 3),
        "recall_Y": round(recall_score(y, pred, zero_division=0), 3),
        "f1_Y": round(f1_score(y, pred, zero_division=0), 3),
        "roc_auc": round(roc_auc_score(y, proba), 3) if len(set(y)) > 1 else None,
    }


def text_for(name: str, row: dict, ctx: dict[str, str]) -> str:
    return row["old_snippet"] if name == "snippet" else (ctx.get(row["id"]) or row["old_snippet"])


def cv(name: str, rows: list[dict], ctx: dict[str, str]) -> dict:
    texts = [text_for(name, r, ctx) for r in rows]
    y = [1 if r["label"] == "Y" else 0 for r in rows]
    groups = [r["repo_key"] for r in rows]
    oof = [0.0] * len(rows)
    folds = 0
    for tr, te in StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=0).split(texts, y, groups):
        if len(set(y[i] for i in te)) < 2:
            continue
        m = model().fit([texts[i] for i in tr], [y[i] for i in tr])
        proba = m.predict_proba([texts[i] for i in te])[:, 1]
        for i, p in zip(te, proba):
            oof[i] = p
        folds += 1
    return {"cv_folds": folds, "cv_pooled": metrics(y, oof)}


def by_source(rows: list[dict], proba: list[float]) -> dict:
    out = {}
    for src in sorted({r.get("source") for r in rows}):
        idx = [i for i, r in enumerate(rows) if r.get("source") == src]
        y = [1 if rows[i]["label"] == "Y" else 0 for i in idx]
        if len(set(y)) > 1:
            out[src] = {"rows": len(idx), "positives": sum(y),
                        "roc_auc": round(roc_auc_score(y, [proba[i] for i in idx]), 3)}
    return out


def main() -> int:
    rows = [json.loads(x) for x in CORE.open() if x.strip()]
    ctx, found = build_context(rows)
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "valid"]
    y_va = [1 if r["label"] == "Y" else 0 for r in valid]

    results = {}
    for name in ("snippet", "context"):
        res = cv(name, train, ctx)
        m = model().fit([text_for(name, r, ctx) for r in train],
                        [1 if r["label"] == "Y" else 0 for r in train])
        proba = m.predict_proba([text_for(name, r, ctx) for r in valid])[:, 1]
        res["valid"] = metrics(y_va, proba)
        res["valid_by_source"] = by_source(valid, proba)
        results[name] = res

    best_valid = max(results[n]["valid"]["roc_auc"] for n in results)
    report = {
        "dataset": "transitions_core_v0.2_draft",
        "models": results,
        "valid_rows": len(valid),
        "valid_positives": sum(y_va),
        "context_coverage": {f"{src}:{'found' if ok else 'missing'}": n for (src, ok), n in found.items()},
        "test_split_evaluated": False,
        "verdict": (
            f"no model is trustworthy yet: grouped-CV AUC overstates transfer and the "
            f"best held-out valid AUC is {best_valid}; training needs frozen labels, "
            f"more positives, or synthetic pretraining"
        ),
        "caveat": "55 training positives; prototype run, not a model-quality claim",
    }
    (OUT / "train_v0.2.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

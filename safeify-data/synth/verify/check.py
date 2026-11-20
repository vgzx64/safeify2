"""Verification gate for synthetic snippets.

Steps:
  1. rustc --edition 2021 --crate-type=lib --emit=metadata for every snippet
  2. batch .rs -> .ast via the extract_ast tool (syn {:#?})
  3. .ast -> baseline-format preorder JSON via pipe/preprocess.py (+ ast_len, sha)
  4. exact-sequence dedupe within (api, kind)
  5. emit out/pairs_manifest.jsonl (theory-note schema + verification block)

Any file failing (1) or (3) is kept in the manifest with ok=false and is
excluded from pair generation.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gen"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipe"))
from common import OUT_RECORDS_INJ, OUT_RECORDS_TMPL, SYNTH_ROOT  # noqa: E402
import preprocess  # noqa: E402
import syn_parser  # noqa: E402

OUT_SNIPPETS = os.path.join(SYNTH_ROOT, "out", "snippets")
OUT_AST = os.path.join(SYNTH_ROOT, "out", "ast")
OUT_ASTJSON = os.path.join(SYNTH_ROOT, "out", "ast_json")
OUT_MANIFEST = os.path.join(SYNTH_ROOT, "out", "pairs_manifest.jsonl")


def load_records():
    records = []
    for path in (OUT_RECORDS_TMPL, OUT_RECORDS_INJ):
        if not os.path.isfile(path):
            raise SystemExit(f"missing {path} — run gen/template.py and gen/inject.py first")
        with open(path, encoding="utf-8") as f:
            records.extend(json.loads(line) for line in f if line.strip())
    return records


def rustc_check(records):
    """Compile-check every snippet; returns {id: (ok, stderr)}."""
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        for rec in records:
            src = os.path.join(SYNTH_ROOT, "out", rec["rel_path"])
            crate_name = "s_" + hashlib.sha1(rec["id"].encode()).hexdigest()[:16]
            proc = subprocess.run(
                ["rustc", "--edition", "2021", "--crate-type", "lib",
                 "--crate-name", crate_name, "--emit=metadata",
                 "--out-dir", tmp, src],
                capture_output=True, text=True,
            )
            results[rec["id"]] = (proc.returncode == 0, proc.stderr.strip())
            for leftover in os.listdir(tmp):
                if leftover.endswith(".rmeta"):
                    os.remove(os.path.join(tmp, leftover))
    return results


def main():
    records = load_records()
    print(f"manifest input: {len(records)} snippets")

    # -- 1. rustc ------------------------------------------------------------
    compile_res = rustc_check(records)
    n_compile_ok = sum(1 for ok, _ in compile_res.values() if ok)
    print(f"rustc: {n_compile_ok}/{len(records)} compile")

    # -- 2. batch AST extraction --------------------------------------------
    if os.path.isdir(OUT_AST):
        shutil.rmtree(OUT_AST)
    ok, failed = syn_parser.extract_tree(OUT_SNIPPETS, OUT_AST)
    print(f"extract_ast: ok={ok} failed={failed}")

    # -- 3. preprocess -> preorder JSON -------------------------------------
    seen = {}  # (api, kind) -> {sha: id}
    kept = 0
    for rec in records:
        parts = rec["rel_path"].split(os.sep)  # ['snippets', <api>, <file>.rs]
        ast_path = os.path.join(OUT_AST, parts[1], parts[2][:-3] + ".ast")
        json_path = os.path.join(OUT_ASTJSON, parts[1], parts[2][:-3] + ".json")

        compile_ok, compile_err = compile_res[rec["id"]]
        rec["verification"] = {"compile": compile_ok, "miri": None,
                               "tests": None, "clippy": None}
        if compile_err and not compile_ok:
            rec["compile_error"] = compile_err.splitlines()[-1][:300]
        try:
            seq = preprocess.ast_file_to_json(ast_path, json_path)
        except Exception as e:  # pipeline failure => unusable row
            rec["ok"] = False
            rec["pipeline_error"] = str(e)[:300]
            continue
        rec["ast_len"] = len(seq.split())
        rec["seq_sha256"] = hashlib.sha256(seq.encode()).hexdigest()
        rec["ast_json"] = os.path.relpath(json_path, os.path.join(SYNTH_ROOT, "out"))

        # -- 4. exact-sequence dedupe within (api, kind) ---------------------
        # only compile-clean snippets may reserve a sequence slot, so a broken
        # file never shadows its fixed twin
        compile_ok, compile_err = compile_res[rec["id"]]
        key = (rec["api"], rec["kind"])
        sha = rec["seq_sha256"]
        if not compile_ok:
            rec["ok"] = False
            continue
        if sha in seen.get(key, {}):
            rec["ok"] = False
            rec["dropped"] = f"duplicate_of {seen[key][sha]}"
            continue
        seen.setdefault(key, {})[sha] = rec["id"]
        rec["ok"] = True
        kept += 1

    # -- 5. manifest ---------------------------------------------------------
    os.makedirs(os.path.dirname(OUT_MANIFEST), exist_ok=True)
    with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    lens = sorted(r["ast_len"] for r in records if r.get("ast_len"))
    def pct(p):
        return lens[min(len(lens) - 1, int(p * len(lens)))] if lens else -1
    print(f"kept (ok): {kept}/{len(records)}")
    print(f"ast_len p50={pct(0.5)} p90={pct(0.9)} max={lens[-1] if lens else -1} "
          f"(baseline train.csv text1 p50=101)")
    print(f"manifest: {OUT_MANIFEST}")
    if n_compile_ok != len(records):
        bad = [i for i, (ok, _) in compile_res.items() if not ok]
        print(f"COMPILE FAILURES ({len(bad)}): {bad[:10]}")
        sys.exit(1)


if __name__ == "__main__":
    main()

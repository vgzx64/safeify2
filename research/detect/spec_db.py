"""Spec database for replaceable-unsafe detection.

Merges, read-only:
  - research/synth/rules/*.yaml      (42 gold cells: api/pattern_id/replaceability/contract)
  - research/synth/splits/kb_verdicts.json  (gold Y/M/N per (api, pattern_id))

Never mutates the synth assets. Verdicts use the same Y/M/N taxonomy as
kb_verdicts.json (Y=replaceable, M=conditional, N=irreplaceable).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SYNTH_DIR = Path(__file__).resolve().parents[1] / "synth"
RULES_DIR = SYNTH_DIR / "rules"
KB_VERDICTS_PATH = SYNTH_DIR / "splits" / "kb_verdicts.json"

# Standard-library prefixes stripped before matching call paths.
_STD_PREFIXES = ("std::", "core::", "alloc::", "::")


@dataclass(frozen=True)
class Rule:
    api: str
    pattern_id: int
    replaceability: str  # Y / M / N (gold verdict of this cell)
    verdict: str  # replaceable / conditional / irreplaceable / encapsulatable
    difficulty: str
    contract: str
    encapsulatable: bool = False
    has_safe: bool = False
    has_encap: bool = False
    source: str = ""  # rule file name


@dataclass
class SpecDB:
    rules: dict[str, list[Rule]] = field(default_factory=dict)  # api -> rules
    kb_verdicts: dict[str, dict[str, str]] = field(default_factory=dict)  # api -> {pid: Y/M/N}
    # API names that are matched as method calls (`.name(`).
    method_apis: frozenset = frozenset()
    # API names matched as path calls; key = "::"-joined tail segments.
    path_apis: dict[str, str] = field(default_factory=dict)

    def match_api(self, callee: str, is_method: bool) -> str | None:
        """Return the spec API name for a callee text, or None."""
        callee = callee.strip()
        if is_method:
            if callee in self.method_apis:
                return callee
            return None
        path = strip_std(callee)
        segs = [s for s in path.split("::") if s]
        if not segs:
            return None
        # exact-then-tail match against path_apis (longest tail first)
        for n in range(len(segs), 0, -1):
            key = "::".join(segs[-n:])
            if key in self.path_apis:
                return self.path_apis[key]
        return None

    def rules_for(self, api: str) -> list[Rule]:
        return sorted(self.rules.get(api, []), key=lambda r: r.pattern_id)


def strip_std(path: str) -> str:
    p = path.strip()
    changed = True
    while changed:
        changed = False
        for pre in _STD_PREFIXES:
            if p.startswith(pre):
                p = p[len(pre):]
                changed = True
    return p


# Method-call unsafe APIs (registry superset; includes non-KB families).
DEFAULT_METHOD_APIS = frozenset({
    "get_unchecked", "get_unchecked_mut", "unwrap_unchecked",
    "unchecked_add", "unchecked_mul",
    "assume_init", "assume_init_mut", "set_len", "offset_from",
    "as_ref", "as_mut",
})

# Path-call unsafe APIs -> tail key used for matching after std stripping.
DEFAULT_PATH_APIS = {
    "ptr::read": "ptr::read",
    "ptr::write": "ptr::write",
    "ptr::copy": "ptr::copy",
    "ptr::copy_nonoverlapping": "ptr::copy_nonoverlapping",
    "ptr::write_bytes": "ptr::write_bytes",
    "ptr::read_volatile": "ptr::read_volatile",
    "ptr::write_volatile": "ptr::write_volatile",
    "mem::transmute": "mem::transmute",
    "mem::zeroed": "mem::zeroed",
    "mem::transmute_copy": "mem::transmute_copy",
    "Box::from_raw": "Box::from_raw",
    "Rc::from_raw": "Rc::from_raw",
    "Arc::from_raw": "Arc::from_raw",
    "Vec::from_raw_parts": "Vec::from_raw_parts",
    "CString::from_raw": "CString::from_raw",
    "CStr::from_ptr": "CStr::from_ptr",
    "NonNull::dangling": "NonNull::dangling",
}


def load_spec_db(
    rules_dir: Path | None = None,
    kb_verdicts_path: Path | None = None,
    method_apis: frozenset | None = None,
    path_apis: dict[str, str] | None = None,
) -> SpecDB:
    rules_dir = Path(rules_dir or RULES_DIR)
    kb_path = Path(kb_verdicts_path or KB_VERDICTS_PATH)
    db = SpecDB(
        method_apis=method_apis or DEFAULT_METHOD_APIS,
        path_apis=dict(path_apis or DEFAULT_PATH_APIS),
    )
    for f in sorted(rules_dir.glob("*.yaml")):
        import yaml  # local import: only needed at load time

        data = yaml.safe_load(f.read_text())
        if not data or "api" not in data:
            continue
        rule = Rule(
            api=str(data["api"]),
            pattern_id=int(data.get("pattern_id", 0)),
            replaceability=str(data.get("replaceability", "M")),
            verdict=str(data.get("verdict", "")),
            difficulty=str(data.get("difficulty", "")),
            contract=str(data.get("contract", "")),
            encapsulatable=bool(data.get("encapsulatable", False)),
            has_safe="safe" in data,
            has_encap="encap" in data,
            source=f.name,
        )
        db.rules.setdefault(rule.api, []).append(rule)
    if kb_path.exists():
        kb = json.loads(kb_path.read_text())
        db.kb_verdicts = kb.get("apis", {})
    return db


def main() -> None:
    db = load_spec_db()
    n_rules = sum(len(v) for v in db.rules.values())
    print(f"spec_db: {n_rules} rules across {len(db.rules)} APIs; "
          f"kb_verdicts APIs: {len(db.kb_verdicts)}")
    for api in sorted(db.rules):
        golds = ",".join(f"{r.pattern_id}:{r.replaceability}" for r in db.rules_for(api))
        print(f"  {api:24s} {golds}")


if __name__ == "__main__":
    main()

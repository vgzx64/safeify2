"""Rule-based mechanism labeller for an old->new safe transition.

This is the weak labeller for version-history mining: given the vulnerable
snippet and the later safe snippet, name the mechanism that made the unsafe
operation unnecessary. Rules are ordered high-precision first. When no rule
explains the row, `predict` returns None instead of guessing: an unknown label
is dropped from weak supervision rather than polluting it with "safe_wrapper".

`predict` never sees the audit labels; scoring is done by
`score_mechanism_rules.py`.
"""

from __future__ import annotations

import re

UNSAFE = re.compile(
    r"\bunsafe\s*(?:\{|fn\b|impl\b|trait\b)"
    r"|\b(?:pointer|ptr)::(?:read|write|copy|copy_nonoverlapping)\b"
    r"|\b(?:Box|Vec|CString|CStr|Rc|Arc)::from_raw(?:_parts)?\b"
    r"|\bset_len\s*\(|\bassume_init\b|\btransmute(?:_copy)?\b|\bget_unchecked\b"
    r"|\boffset_from\b|\bPin::new_unchecked\b|\bzeroed\s*\("
    r"|\buninitialized\s*\(",
)

RULES = [
    ("interior_mutability", re.compile(
        r"\b(?:Cell|RefCell|Mutex|RwLock|ArcSwap|Atomic[A-Za-z0-9_]*)\b")),
    ("pin_api", re.compile(
        r"\bPin::(?:new|get_mut|as_mut|into_inner)\b|\bBox::pin\s*\(|(?<!\w)pin!\s*\(")),
    ("slice_view", re.compile(
        r"\bchunks_exact\b|\bchunks\s*\(|\bwindows\s*\(|\bsplit_at\b"
        r"|\bto_ne_bytes\b|\bfrom_ne_bytes\b|\bzip\s*\(")),
    ("init_memory", re.compile(
        r"\bvec!\s*\[|\bMaybeUninit\b|\bassume_init\b"
        r"|\bDefault::default\b|\b::default\s*\(\s*\)"
        r"|\b(?:0u8|0_u8)\s*;")),
    ("capacity_ops", re.compile(
        r"\.resize\s*\(|\.resize_with\s*\(|\.truncate\s*\(|\.reserve\s*\(")),
    ("checked_api", re.compile(
        r"\.get\s*\(|\.get_mut\s*\(|\bcopy_from_slice\b|\bfrom_utf8\b"
        r"|\bfrom_bytes_with_nul\b|\btry_into\b|\bchecked_[a-z_]+\b|\bparse\s*\(")),
]

TRANSMUTE = re.compile(r"\btransmute(?:_copy)?\b")
RESTRUCTURE = re.compile(
    r"\benum\s+\w+\s*\{|#\[repr\(|\bimpl\s+From<|\bFrom::from\s*\(|\.into\s*\(\s*\)")


def code_only(text: str) -> str:
    return "\n".join(re.sub(r"//.*$", "", line) for line in (text or "").splitlines())


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", code_only(text)).strip()


def tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[^\sA-Za-z0-9_]", code_only(text))


def skeleton(text: str) -> list[str]:
    """Tokens minus `unsafe` and braces: catches `unsafe { X }` -> `X`."""
    return [t for t in tokens(text) if t not in ("unsafe", "{", "}")]


def predict(old: str, new: str, api: str | None = None) -> str | None:
    """Return a mechanism class, or None when no rule explains the transition."""
    n = code_only(new)
    if UNSAFE.search(n):
        return None  # unsafe still present: not a safe transition
    for mech, rx in RULES:
        if rx.search(n):
            return mech
    if skeleton(old) == skeleton(new) and skeleton(new):
        return "unnecessary"
    if TRANSMUTE.search(code_only(old)) and RESTRUCTURE.search(n):
        return "restructure"
    if TRANSMUTE.search(code_only(old)) and re.search(r"\bas\s+\w+", n):
        return "restructure"
    return None


if __name__ == "__main__":
    assert predict("unsafe { x.get_unchecked(i) }", "x.get(i).unwrap()") == "checked_api"
    assert predict("unsafe { out.set_len(n) }", "let out = vec![0u8; n];") == "init_memory"
    assert predict("unsafe { std::mem::uninitialized() }", "Default::default()") == "init_memory"
    assert predict("unsafe { v.set_len(n) }", "v.resize(n, 0);") == "capacity_ops"
    assert predict("unsafe { p.read() }", "unsafe { p.read() }") is None
    assert predict("unsafe { f() }", "f()") == "unnecessary"
    assert predict("unsafe { std::mem::transmute(x) }", "match x { _ => 0 }") is None
    print("mechanism rules ok:", len(RULES), "rules")

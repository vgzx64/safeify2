"""Lints for OS-interaction counterexamples in *safe* Rust.

Implements four of the five attack patterns of Hassnain & Stanford,
"Counterexamples in Safe Rust" (ASEW '24):

  1. filesystem access      -> safeify::fs_special_path, fs_traversal_literal,
                               fs_tainted_path
  2. command execution      -> safeify::exec_basename, exec_tainted_cmd,
                               exec_shell_tainted
  4. build-time effects     -> safeify::build_outside_out_dir
  5. environment variables  -> safeify::env_set_dangerous, env_read_dangerous

Pattern 3 (compiler unsoundness) is out of scope: it is fixed in the compiler
and cannot be decided from source. See notes/research/counterexamples.md.

These are policy lints over safe code, not the Y/M/N replaceability verdicts
of `verdict.py`, and they share no evaluation with it. Severity follows clippy
conventions: `deny | warn | info`, overridable per rule in Cargo.toml
`[lints.safeify]`, suppressible with `#[allow(safeify::rule)]` above the function or
a `// safeify: allow(rule)` comment on the line before the call.

Conservative by construction: a finding requires either a literal in a
danger-table, or a parameter/tainted value with no recognised guard. Values
classified `unknown` never produce a finding.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:  # package import (python -m), else script import (python detect/...)
    from . import inventory
    from . import provenance
    from .provenance import (
        FnFacts,
        classify,
        fn_at,
        guards_for,
        parse_fns,
        stmt_start,
    )
except ImportError:
    import inventory
    import provenance
    from provenance import (  # type: ignore[no-redef]
        FnFacts,
        classify,
        fn_at,
        guards_for,
        parse_fns,
        stmt_start,
    )

# ------------------------------------------------------------------ rules ---

#: Default severity per rule. `deny` is reserved for cases that are dangerous
#: regardless of context; `warn` is demoted to `info` outside public API and
#: build scripts, where the paper's threat model does not apply.
RULE_LEVEL: dict[str, str] = {
    "fs_special_path": "deny",
    "fs_traversal_literal": "warn",
    "fs_tainted_path": "warn",
    "exec_basename": "warn",
    "exec_tainted_cmd": "warn",
    "exec_shell_tainted": "warn",
    "exec_written_path": "warn",
    "env_set_dangerous": "warn",
    "env_read_dangerous": "info",
    "build_outside_out_dir": "warn",
}
DEMOTABLE = {"fs_tainted_path", "exec_basename", "exec_tainted_cmd"}
LEVEL_ORDER = {"allow": 0, "info": 1, "warn": 2, "deny": 3}

#: Sinks whose argument is a filesystem path: callee tail -> path arg indices.
FS_PATH_ARG: dict[str, tuple[int, ...]] = {
    "fs::read": (0,),
    "fs::read_to_string": (0,),
    "fs::read_dir": (0,),
    "fs::write": (0,),
    "fs::remove_file": (0,),
    "fs::remove_dir": (0,),
    "fs::remove_dir_all": (0,),
    "fs::create_dir": (0,),
    "fs::create_dir_all": (0,),
    "fs::rename": (0, 1),
    "fs::copy": (0, 1),
    "fs::hard_link": (0, 1),
    "fs::set_permissions": (0,),
    "fs::metadata": (0,),
    "fs::symlink_metadata": (0,),
    "File::open": (0,),
    "File::create": (0,),
    "File::create_new": (0,),
}
_WRITE_SINKS = {
    "fs::write",
    "fs::rename",
    "fs::copy",
    "fs::hard_link",
    "fs::remove_file",
    "fs::remove_dir",
    "fs::remove_dir_all",
    "fs::create_dir",
    "fs::create_dir_all",
    "fs::set_permissions",
    "File::create",
    "File::create_new",
}

POSIX_SPECIAL: list[tuple[str, str]] = [
    (r"^/proc/(?:self|\d+)/mem$", "proc_mem"),
    (r"^/proc/(?:self|\d+)/pagemap$", "proc_pagemap"),
    (r"^/proc/(?:self|\d+)/maps$", "proc_maps"),
    (r"^/proc/kcore$", "kernel_mem"),
    (r"^/proc/sysrq-trigger$", "sysrq"),
    (r"^/dev/(?:mem|kmem|port)$", "device_mem"),
    (r"^/etc/ld\.so\.preload$", "preload"),
    (r"^/(?:sys|proc/sys)/", "kernel_config"),
]

REASON_TEXT = {
    "proc_mem": "the process's own address space (writing it bypasses every "
                "bounds and borrow check the compiler emitted)",
    "proc_pagemap": "the process page table",
    "proc_maps": "the process memory map",
    "kernel_mem": "kernel memory",
    "sysrq": "the kernel sysrq trigger",
    "device_mem": "raw device memory",
    "preload": "the dynamic loader preload list read by every new process",
    "windows_device": "a raw Windows device namespace",
    "kernel_config": "kernel configuration",
    "dotdot": "a path containing '..'",
}
REASON_LEVEL = {"kernel_config": "warn", "dotdot": "warn"}

SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "cmd", "cmd.exe", "powershell", "pwsh"}

DANGEROUS_ENV = {
    "PATH",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "LD_AUDIT",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
    "RUSTC",
    "RUSTC_WRAPPER",
    "RUSTC_WORKSPACE_WRAPPER",
    "RUSTFLAGS",
    "CARGO",
    "CARGO_HOME",
    "RUSTUP_TOOLCHAIN",
    "RUSTUP_HOME",
    "HOME",
    "TMPDIR",
    "IFS",
    "BASH_ENV",
    "ENV",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "http_proxy",
    "https_proxy",
    "ALL_PROXY",
    "GIT_SSH",
    "GIT_SSH_COMMAND",
    "NODE_OPTIONS",
    "PYTHONPATH",
    "PERL5LIB",
}


#: Callee tails whose argument role we care about. Used as a fast prefilter so
#: the linter never scans a generated 2 MB file quadratically.
_PATH_SINKS = set(FS_PATH_ARG) | {
    "Command::new",
    "env::set_var",
    "env::remove_var",
    "env::var",
    "env::var_os",
}
_METHOD_SINKS = {"open", "create", "create_new"}


def interesting_calls(mask: str, start: int = 0, end: int | None = None) -> list:
    """Calls whose callee is one of the sinks, without resolving the rest.

    `inventory.find_calls` computes argument spans for every call in the file,
    which is quadratic on generated code. This walks each `(` backwards over a
    short identifier and only matches parentheses for the few sinks we need.
    """
    calls = []
    end = len(mask) if end is None else end
    for m in re.finditer(r"\(", mask[start:end]):
        open_p = start + m.start()
        j = open_p - 1
        while j >= 0 and mask[j] in " \t\r\n":
            j -= 1
        if j < 0:
            continue
        name_end = j
        while j >= 0 and (mask[j].isalnum() or mask[j] == "_"):
            j -= 1
        name = mask[j + 1 : name_end + 1]
        if not name or not name[0].isalpha():
            continue
        k = j
        while k >= 0 and mask[k] in " \t\r\n":
            k -= 1
        if k >= 0 and mask[k] == ".":
            if name not in _METHOD_SINKS:
                continue
            callee, is_method = name, True
        else:
            e = name_end
            while j >= 0 and (mask[j].isalnum() or mask[j] in "_:"):
                j -= 1
            callee = mask[j + 1 : e + 1]
            if not callee or _tail2(callee) not in _PATH_SINKS:
                continue
            is_method = False
        close = inventory.find_matching(mask, open_p, "(", ")")
        if close is None:
            continue
        args, spans = inventory._split_args(mask[open_p + 1 : close], open_p + 1)
        calls.append(inventory.Call(callee, is_method, open_p, close, args, spans))
    return calls


# --------------------------------------------------------------- findings ---

@dataclass
class Finding:
    path: str
    line: int  # 1-based
    col: int  # 1-based
    rule: str
    level: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: {self.level}[safeify::{self.rule}]: {self.message}"

    def as_json(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "col": self.col,
            "rule": self.rule,
            "level": self.level,
            "message": self.message,
        }


@dataclass
class Ctx:
    path: str
    src: str
    mask: str
    is_build: bool
    edition: int | None
    levels: dict[str, str]
    promote: bool = False


# ------------------------------------------------------------------ tables ---

def _tail2(callee: str) -> str:
    """Last two `::` segments, so `std::fs::write` and `fs::write` agree."""
    parts = callee.split("::")
    return "::".join(parts[-2:]) if len(parts) >= 2 else callee


def danger_path(value: str) -> tuple[str, str] | None:
    """(reason, level) for a literal path, or None.

    Level is `deny` unless REASON_LEVEL says otherwise; `dotdot` is only warn.
    """
    if value.startswith("\\\\.\\") or value.startswith("\\\\?\\"):
        return ("windows_device", "deny")
    norm = value.replace("\\", "/")
    for rx, name in POSIX_SPECIAL:
        if re.match(rx, norm):
            return (name, REASON_LEVEL.get(name, "deny"))
    absolute = norm.startswith("/") or re.match(r"^[A-Za-z]:/", norm)
    if absolute and any(seg == ".." for seg in norm.split("/")):
        return ("dotdot", "warn")
    return None


# ------------------------------------------------------------- suppression ---

def _allow_text(text: str, rule: str) -> bool:
    for m in re.finditer(r"(?:allow|expect)\s*\(\s*safeify\s*::\s*([A-Za-z_]\w*)", text):
        if m.group(1) in (rule, "all"):
            return True
    for m in re.finditer(r"safeify:\s*allow\s*\(\s*(?:safeify\s*::\s*)?([A-Za-z_]\w*)", text):
        if m.group(1) in (rule, "all"):
            return True
    return False


def _suppressed(ctx: Ctx, fn: FnFacts, call_off: int, rule: str) -> bool:
    attr = ctx.mask[max(0, fn.start - 400) : fn.start]
    if _allow_text(attr, rule):
        return True
    lines = ctx.src.splitlines()
    line0, _ = inventory.offset_to_line_col(ctx.src, call_off)
    for i in (line0, line0 - 1):
        if 0 <= i < len(lines) and _allow_text(lines[i], rule):
            return True
    return False


def _resolve_level(ctx: Ctx, fn: FnFacts, rule: str, override: str | None) -> str:
    if override is not None:
        level = override
    else:
        level = (
            ctx.levels.get(rule)
            or ctx.levels.get(rule.split("_")[0])
            or RULE_LEVEL[rule]
        )
    if level in ("warn", "info") and rule in DEMOTABLE and not (fn.is_pub or ctx.is_build):
        level = "info"
    if ctx.promote and level != "allow":
        level = "deny"
    return level


def _emit(ctx: Ctx, fn: FnFacts, call_off: int, rule: str, message: str,
          override: str | None = None) -> Finding | None:
    if _suppressed(ctx, fn, call_off, rule):
        return None
    level = _resolve_level(ctx, fn, rule, override)
    if level == "allow":
        return None
    line0, col0 = inventory.offset_to_line_col(ctx.src, call_off)
    return Finding(ctx.path, line0 + 1, col0 + 1, rule, level, message)


# ------------------------------------------------------------------- rules ---

def _arg(ctx: Ctx, call, i: int) -> str:
    if i >= len(call.arg_spans):
        return ""
    a, b = call.arg_spans[i]
    return ctx.src[a:b].strip()


def _lit_arg(ctx: Ctx, call, i: int) -> str | None:
    prov = classify(_arg(ctx, call, i), None)
    return prov.value if prov.is_literal() else None


def _method_is_file_open(ctx: Ctx, call) -> bool:
    if not call.is_method or call.callee not in {"open", "create", "create_new"}:
        return False
    pre = ctx.mask[stmt_start(ctx.mask, call.open_paren) : call.open_paren]
    return "OpenOptions" in pre


def _fs_findings(call, fn: FnFacts, ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    if call.is_method:
        idxs: tuple[int, ...] = (0,) if _method_is_file_open(ctx, call) else ()
    else:
        idxs = FS_PATH_ARG.get(_tail2(call.callee), ())
    if not idxs:
        return out

    for i in idxs:
        expr = _arg(ctx, call, i)
        if not expr:
            continue
        prov = classify(expr, fn)
        off = call.span[0]

        if prov.is_literal() and prov.value is not None:
            hit = danger_path(prov.value)
            if hit is not None and hit[0] == "kernel_config" and not _is_write_sink(ctx, call):
                hit = None
            if hit is not None:
                reason, level = hit
                rule = (
                    "fs_traversal_literal" if reason == "dotdot" else "fs_special_path"
                )
                out.append(
                    _emit(
                        ctx,
                        fn,
                        off,
                        rule,
                        f"path '{prov.value}' is {REASON_TEXT[reason]}; "
                        "safe Rust gives no guarantee against OS-level side effects",
                        override=None if level == "deny" else "warn",
                    )
                )
        elif prov.is_dynamic():
            if not _is_write_sink(ctx, call):
                # Reading a caller-supplied path is the library contract and is
                # not the paper's counterexample; only writes can corrupt the
                # process or the toolchain.
                continue
            guards = guards_for(ctx.mask, expr, fn.body_start, call.open_paren)
            if not guards:
                src_txt = prov.detail or "an input"
                caller_owned = prov.kind == provenance.PARAM
                out.append(
                    _emit(
                        ctx,
                        fn,
                        off,
                        "fs_tainted_path",
                        f"path '{expr}' comes from {src_txt} and is not validated "
                        "against a root directory (canonicalize + starts_with, "
                        "components/ParentDir, or an allowlist)",
                        override="info" if caller_owned else None,
                    )
                )

        if ctx.is_build and _is_write_sink(ctx, call) and not _under_out_dir(ctx, fn, expr):
            out.append(
                _emit(
                    ctx,
                    fn,
                    off,
                    "build_outside_out_dir",
                    f"build script writes '{expr}' outside OUT_DIR; "
                    "build-time writes can modify the crate or the toolchain",
                )
            )
    return [f for f in out if f is not None]


def _is_write_sink(ctx: Ctx, call) -> bool:
    if call.is_method:
        if call.callee not in {"open", "create", "create_new"}:
            return False
        pre = ctx.mask[stmt_start(ctx.mask, call.open_paren) : call.open_paren]
        return "OpenOptions" in pre and any(
            flag in pre for flag in ("write(true)", "create(true)", "append(true)")
        )
    return _tail2(call.callee) in _WRITE_SINKS


def _under_out_dir(ctx: Ctx, fn: FnFacts, expr: str, depth: int = 0,
                   seen: frozenset[str] = frozenset()) -> bool:
    """Does this path expression reach OUT_DIR, directly or through a binding?

    `let out_dir = env::var("OUT_DIR")?; File::create(Path::new(&out_dir)...)`
    is the intended build-script pattern; testing only the argument text made
    it a false positive in 4 of 9 audited sites.
    """
    if "OUT_DIR" in expr or "CARGO_TARGET_DIR" in expr or "target" in expr:
        return True
    if depth >= 3:
        return False
    for ident in set(re.findall(r"[A-Za-z_]\w*", expr)):
        if ident in seen or ident not in fn.bindings:
            continue
        if _under_out_dir(ctx, fn, fn.bindings[ident], depth + 1, seen | {ident}):
            return True
    return False


def _shell_args_dynamic(ctx: Ctx, call, fn: FnFacts) -> bool:
    end = ctx.mask.find(";", call.close_paren)
    end = len(ctx.mask) if end == -1 else end
    for c in inventory.find_calls(ctx.mask, call.close_paren, end):
        if c.callee not in ("arg", "args"):
            continue
        for i in range(len(c.arg_spans)):
            if classify(_arg(ctx, c, i), fn).is_dynamic():
                return True
    return False


_NET = re.compile(
    r"\b(?:reqwest|ureq|hyper|attohttpc|surf|isahc|curl|TcpStream|std\s*::\s*net)\b"
)


def _written_literals(ctx: Ctx, fn: FnFacts, call) -> set[str]:
    """Literal paths this function wrote before `call`.

    The dropper shape: write a payload, then execute the path that was just
    written. `unknown` provenance cannot express that, because the program
    name *is* a literal — it just was not one when the function started.
    """
    out: set[str] = set()
    for c in interesting_calls(ctx.mask, fn.body_start, call.open_paren):
        if not _is_write_sink(ctx, c):
            continue
        for i in range(len(c.arg_spans)):
            prov = classify(_arg(ctx, c, i), fn)
            if prov.is_literal() and prov.value:
                out.add(prov.value)
    return out


def _exec_findings(call, fn: FnFacts, ctx: Ctx) -> list[Finding]:
    if call.is_method or _tail2(call.callee) != "Command::new":
        return []
    expr = _arg(ctx, call, 0)
    if not expr:
        return []
    prov = classify(expr, fn)
    off = call.span[0]

    if prov.is_literal() and prov.value:
        v = prov.value
        if "/" in v or "\\" in v:
            if v in _written_literals(ctx, fn, call):
                downloaded = bool(_NET.search(ctx.mask[fn.body_start : call.open_paren]))
                tail = (
                    "; the same function performs a network request"
                    if downloaded
                    else ""
                )
                return [
                    _emit(
                        ctx,
                        fn,
                        off,
                        "exec_written_path",
                        f"executes '{v}', a path this function wrote earlier{tail} "
                        "— review what controls that file (dropper pattern)",
                    )
                ]
            return []  # explicit path: no PATH/CWD resolution
        if v in SHELLS:
            if _shell_args_dynamic(ctx, call, fn):
                return [
                    _emit(
                        ctx,
                        fn,
                        off,
                        "exec_shell_tainted",
                        f"shell '{v}' is invoked with a caller-controlled argument; "
                        "the argument becomes shell syntax",
                    )
                ]
            return []
        return [
            _emit(
                ctx,
                fn,
                off,
                "exec_basename",
                f"Command::new(\"{v}\") has no path separator, so it is resolved "
                "through PATH and, on Windows, the current directory "
                "(CWE-426, cf. RUSTSEC-2021-0071); use an absolute path",
            )
        ]

    if prov.is_dynamic():
        if guards_for(ctx.mask, expr, fn.body_start, call.open_paren):
            return []
        return [
            _emit(
                ctx,
                fn,
                off,
                "exec_tainted_cmd",
                f"program name '{expr}' comes from {prov.detail or 'an input'} "
                "without an allowlist",
            )
        ]
    return []


def _env_findings(call, fn: FnFacts, ctx: Ctx) -> list[Finding]:
    if call.is_method:
        return []
    tail = _tail2(call.callee)
    if tail in ("env::set_var", "env::remove_var"):
        name = _lit_arg(ctx, call, 0)
        if name in DANGEROUS_ENV:
            note = ""
            if ctx.edition is not None and ctx.edition >= 2024:
                note = (
                    " (edition 2024 makes set_var unsafe, so this pattern is only "
                    "expressible in older editions or inside unsafe)"
                )
            return [
                _emit(
                    ctx,
                    fn,
                    call.span[0],
                    "env_set_dangerous",
                    f"'{name}' is rewritten for this process and every child{note}",
                )
            ]
        return []
    if tail in ("env::var", "env::var_os") and _lit_arg(ctx, call, 0) in DANGEROUS_ENV:
        name = _lit_arg(ctx, call, 0)
        return [
            _emit(
                ctx,
                fn,
                call.span[0],
                "env_read_dangerous",
                f"reading '{name}' trusts process configuration that an attacker "
                "may control (env is inherited by every process)",
            )
        ]
    return []


# -------------------------------------------------------------------- main ---

def lint_source(src: str, path: str = "<memory>", edition: int | None = None,
                levels: dict[str, str] | None = None,
                promote: bool = False) -> list[Finding]:
    mask = inventory.mask_source(src)
    fns = parse_fns(src, mask)
    ctx = Ctx(
        path=path,
        src=src,
        mask=mask,
        is_build=Path(path).name == "build.rs",
        edition=edition,
        levels=dict(levels or {}),
        promote=promote,
    )
    out: list[Finding] = []
    for call in interesting_calls(mask):
        fn = fn_at(fns, call.open_paren)
        if fn is None:
            continue
        out += [f for f in _fs_findings(call, fn, ctx) if f is not None]
        out += [f for f in _exec_findings(call, fn, ctx) if f is not None]
        out += [f for f in _env_findings(call, fn, ctx) if f is not None]
    out.sort(key=lambda f: (f.line, f.col, f.rule))
    return out


def _manifest_for(path: Path) -> dict:
    """Nearest Cargo.toml settings: edition + [lints.safeify]."""
    empty: dict = {}
    for parent in [path.parent, *path.parents][:6]:
        toml = parent / "Cargo.toml"
        if not toml.is_file():
            continue
        try:
            import tomllib

            data = tomllib.loads(toml.read_text())
        except Exception:
            return empty
        levels = {}
        for key, val in (data.get("lints", {}).get("safeify", {}) or {}).items():
            if isinstance(val, str):
                levels[key] = val
            elif isinstance(val, dict) and isinstance(val.get("level"), str):
                levels[key] = val["level"]
        edition = data.get("edition") or data.get("package", {}).get("edition")
        return {"edition": int(edition) if edition else None, "levels": levels}
    return empty


def lint_paths(paths: list[str], edition: int | None = None,
               promote: bool = False, min_level: str = "info",
               use_config: bool = True, max_bytes: int = 0) -> list[Finding]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files += sorted(
                q for q in p.rglob("*.rs") if "target" not in q.parts and ".git" not in q.parts
            )
        elif p.is_file():
            files.append(p)
    findings: list[Finding] = []
    for f in files:
        cfg = _manifest_for(f) if use_config else {}
        try:
            if max_bytes and f.stat().st_size > max_bytes:
                continue
            src = f.read_text(errors="replace")
        except OSError:
            continue
        findings += lint_source(
            src,
            path=str(f),
            edition=edition if edition is not None else cfg.get("edition"),
            levels=cfg.get("levels", {}),
            promote=promote,
        )
    floor = LEVEL_ORDER[min_level]
    return [f for f in findings if LEVEL_ORDER[f.level] >= floor]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="lint_safe",
        description="Lint safe Rust for OS-interaction counterexamples (ASEW'24 patterns)",
    )
    ap.add_argument("paths", nargs="+", help="files or directories")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--edition", type=int, default=None, help="override crate edition")
    ap.add_argument("--deny", action="store_true", help="promote every finding to deny")
    ap.add_argument(
        "--min-level", default="info", choices=["info", "warn", "deny"],
        help="suppress findings below this severity",
    )
    ap.add_argument("--no-config", action="store_true", help="ignore Cargo.toml [lints.safeify]")
    ap.add_argument(
        "--max-bytes", type=int, default=0,
        help="skip files larger than this (generated code), 0 = no limit",
    )
    args = ap.parse_args(argv)

    findings = lint_paths(
        args.paths,
        edition=args.edition,
        promote=args.deny,
        min_level=args.min_level,
        use_config=not args.no_config,
        max_bytes=args.max_bytes,
    )
    if args.json:
        print(json.dumps([f.as_json() for f in findings], indent=2))
    else:
        for f in findings:
            print(f.render())
        n_deny = sum(1 for f in findings if f.level == "deny")
        n_warn = sum(1 for f in findings if f.level == "warn")
        n_info = sum(1 for f in findings if f.level == "info")
        print(
            f"\n{n_deny} deny, {n_warn} warn, {n_info} info "
            f"({len({f.path for f in findings})} file(s) with findings)",
            file=sys.stderr,
        )
    return 1 if any(f.level == "deny" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())

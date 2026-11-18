# Transition label rubric (LLM adjudication, v1)

You are reviewing one fix hunk. Decide whether the old unsafe operation has a
safe replacement in this context, or whether unsafe code is retained.

Do **not** require compilation. Judge the semantic diff. A safe replacement can
be a different API, a checked index, a zero-initialized buffer, a guard, or a
safe wrapper. The `unsafe` keyword may remain in a guard/encapsulation case.

## Labels

| `replaceability` | Meaning |
|---|---|
| `Y` | A concrete safe replacement exists and does the same job. No unsafe operation remains in the replacement. |
| `M` | A safe option exists only with preconditions/restructuring, or the fix adds a guard but unsafe code remains. |
| `N` | No safe replacement in this frame; unsafe must be kept. |
| `U` | The hunk is unrelated, mixed, or too incomplete to decide. |

## Action

| `action` | Meaning |
|---|---|
| `replace` | Use a safe API/expression instead of the unsafe operation. |
| `guard` | Add checks/preconditions and keep a narrower unsafe operation. |
| `encapsulate` | Keep unsafe inside a checked safe wrapper. |
| `keep` | No safe alternative; retain unsafe with justification. |
| `unknown` | Unresolved. |

**M is a descriptor, not a training class.** Two independent annotators
reproduce Y vs not-Y but not M vs N (see
`../out/label_reliability.json`), so the frozen dataset trains the binary
question "is there a safe replacement" and keeps M to record that a guard or
restructuring is what stands in the way.

`encapsulate` is an action, not a fourth `replaceability` class. A block can be
`N` for direct replacement and still have action `encapsulate`.

## Decision rules

1. Quote the unsafe operation from the old snippet.
2. Quote the proposed replacement/guard from the new snippet.
3. If the old unsafe API is still present in the new snippet, this is **not**
   `replace`; use `M`/`guard` or `N`/`keep`.
4. If the new snippet is a different function or unrelated code, use `U`.
5. If the old snippet is only a comment or a signature with no unsafe
   operation, use `U`/`false_positive`.
6. Do not infer a replacement that is not shown in the new snippet.
7. Do not reward a patch that merely moves the same unsafe operation.
8. Clipped snippets may omit the enclosing `unsafe {` line. A call to a known
   unsafe API (`from_raw_parts`, `get_unchecked`, `set_len`, `assume_init`,
   `transmute`, `ptr::read`/`copy`/`write`, ...) still counts as the unsafe
   operation; do not veto only because the `unsafe` keyword is absent.
9. `M` requires something in the new snippet that actually discharges part of
   the operation's safety requirement:
   (a) a check, branch, or validation the old snippet lacked that prevents a
       class of UB (`is_null()`, a length bound, an alignment check,
       `checked_*`, a clamp before `get_unchecked`, ...); or
   (b) a safe replacement that is only correct under a precondition, where the
       hunk shows that precondition.
   Not enough on its own: renaming, threading extra metadata or an alignment
   field into the same unsafe call, turning the wrapper into `unsafe fn`
   (surfacing a precondition without enforcing it), adding SAFETY comments,
   doctests, or tests. Those stay `N`/`keep` unless (a) or (b) also holds.
   For `M`, `evidence_new` must quote the added check or precondition.
10. When torn between `M` and `N`, choose `N` unless you can quote the added
    check. `M` is for "safe path exists but needs a guard", not for "the
    signature changed while the unsafe operation stayed".

## Output JSONL

One object per input row:

```json
{"id":"...","replaceability":"Y","action":"replace","confidence":"high",
 "rationale":"one or two sentences",
 "evidence_old":"quoted unsafe line",
 "evidence_new":"quoted replacement line",
 "veto":false,"veto_reason":""}
```

Use `confidence` `high`, `medium`, or `low`. Set `veto` true when the row is
unrelated/misaligned; give a reason.

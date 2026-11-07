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

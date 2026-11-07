# Official-docs contract rubric (v1)

Input is a public unsafe Rust API and its `# Safety` contract, not a diff pair.
Decide what the contract implies for replaceability/action.

| Label | Meaning |
|---|---|
| `N` | The API is inherently caller/FFI/allocator/volatile controlled; no safe replacement is documented in this frame. |
| `M` | A safe wrapper/guard is feasible, but the unsafe operation remains internally. |
| `Y` | The docs explicitly document a concrete safe alternative doing the same job. |
| `U` | Contract is insufficient or the API is internal/unclear. |

Action: `replace` (Y), `encapsulate` (M), `keep` (N), `unknown` (U).

Rules:
1. Do not infer “no safe alternative” from silence alone; use the contract.
2. If the contract is only a caller obligation that cannot be checked, prefer `N`/keep only when the operation is inherently unsafe (volatile, allocator, raw FFI, provenance).
3. If a safe wrapper can enforce/check the precondition, prefer `M`/encapsulate.
4. Quote the signature and the contract.
5. Do not count a doc example as a transition pair.

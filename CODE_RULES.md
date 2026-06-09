# Code-Writing Rules

**Rules for writing code in this project.**
**Audience:** junior devs / AI agents on local models.
**Goal:** compact code that loses no context — small and readable, yet complete enough to work without guessing.

---

## Principles (DRY / KISS / YAGNI)

Apply all three on every change:

| Principle | Meaning | Practical rule |
|-----------|---------|----------------|
| **DRY** | Don't Repeat Yourself | Same logic in 2+ places → extract one function. But duplicate once is fine; abstract on the *third* use. |
| **KISS** | Keep It Simple | Pick the plainest solution that works. No clever one-liners, no needless layers. |
| **YAGNI** | You Aren't Gonna Need It | Build only what the current task needs. No "future-proof" hooks, flags, or params nobody calls yet. |

**Tension:** DRY pulls toward abstraction, YAGNI pulls away. Resolve with KISS — abstract only when duplication is *real and repeated*, not anticipated.

---

## File Size (max 120 lines)

- **Hard ceiling: 120 lines per file** (excluding blank lines is fine, but keep it honest).
- Over the limit = a responsibility signal, not a formatting problem. Split it:
  - Group by single responsibility → move each into its own module.
  - Extract pure helpers into a `utils`/`helpers` module.
  - Separate I/O from logic so each part stays small and testable.
- Expected result: every file is scannable in one screen.

---

## Comments vs Naming

Prefer **self-explanatory code** over comments:

- Name functions and variables for *intent* — `poll_slow_queries()` beats `do_query()` + a comment.
- A comment that restates the code is noise. Delete it; fix the name instead.
- **Write a comment only for the "why"** the code can't express: a non-obvious constraint, a workaround, a tricky edge case, a reference to an ADR or ticket.
- No commented-out code. Delete it — git remembers.

---

## Unit Tests (as needed)

Pragmatic, not dogmatic:

- **Test when:** there's real logic, branching, edge cases, parsing, or a bug being fixed (write the failing test first).
- **Skip when:** trivial glue, pure config, or a thin pass-through with no logic.
- **Test behavior, not implementation** — assert on inputs/outputs and observable effects, not internal calls.
- Cover the edge cases that matter: empty input, boundaries, error paths.
- A test must be able to fail — no assertion-free "it runs" tests.

---

## Anti-Patterns (reject the code if present)

- ❌ Copy-pasted logic instead of one shared function (DRY).
- ❌ Abstraction for a use case that doesn't exist yet (YAGNI).
- ❌ Clever/dense code where a plain version reads better (KISS).
- ❌ File over 120 lines doing several jobs.
- ❌ Comments that restate the code, or commented-out blocks left behind.
- ❌ Cryptic names propped up by explanatory comments.
- ❌ New logic/edge cases shipped with no test, or tests that can't fail.

---

## Mini Checklist (run before commit)

```text
[ ] DRY  — no duplicated logic (or duplicated only once, deliberately)
[ ] KISS — simplest version that works; no cleverness
[ ] YAGNI— only what this task needs; no speculative code
[ ] ≤120 lines per file; split by responsibility if over
[ ] Names carry intent; comments only explain "why"
[ ] No commented-out code
[ ] Tests added where logic/edge cases exist; each test can fail
```

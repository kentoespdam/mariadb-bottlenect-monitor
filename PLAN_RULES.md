# Plan-Writing Rules

**Rules for writing implementation plans in this project.**
**Audience:** junior devs / AI agents on local models.
**Goal:** compact plans that lose no context — detailed enough to execute without guessing, short enough to read in one pass.

---

## Before You Plan (mandatory)

Complete every box **before** writing a plan or any code:

- [ ] **`gitnexus` first** — understand the code before touching it.
  - `gitnexus_query({query})` to find execution flows (don't grep).
  - `gitnexus_context({name})` for a symbol's callers/callees.
  - `gitnexus_impact({target, direction:"upstream"})` before editing ANY symbol — report blast radius; stop on HIGH/CRITICAL.
  - See `.claude/skills/gitnexus/` and the rules in `CLAUDE.md`.
- [ ] **`context7`** — fetch the latest docs / best practices.
  - Resolve the library, then pull current docs before choosing any API, version, or pattern. Never rely on memory for library usage.
- [ ] **Read domain + decisions** — `CONTEXT.md` for terms, `docs/adr/` for prior decisions that constrain the design.
- [ ] **Read the whole plan and confirm understanding** before writing a single line of code.

---

## Plan Structure (required sections)

Every plan MUST contain these, in order:

| Section | Content |
|---------|---------|
| **Context** | Why this change exists — the problem, the trigger, the intended outcome. |
| **Scope** | What is in scope and explicitly out of scope. |
| **Steps** | Numbered, single-purpose, detailed (see rules below). |
| **Files** | Exact paths to create/modify. |
| **Verification** | How to prove it works end-to-end. |
| **Risks** | Blast radius (from `gitnexus_impact`) + rollback. |

---

## Step-Writing Rules

Each step must be executable by a junior dev / local model with **zero guessing**:

- **No code in the plan.** Describe *what* to do and *why*, not *how to type it*. No code blocks, no snippets, no literal function bodies — the implementer writes the code.
- **High-level language.** Use plain, intent-level wording ("validate the config before startup", "add a retry around the poll call"), not line-by-line instructions.
- **One purpose per step.** Split anything with "and".
- **Name exact file paths** — never "the config" or "the handler".
- **State the expected result** — the behavior/outcome after the step, in words.
- **Reuse, don't reinvent** — point to existing functions/utilities by path instead of new code. Confirm reuse via `gitnexus_context`.
- **No vague verbs** — replace "update the logic" with the concrete intent.

---

## Compact Without Losing Context

- Describe a **repeated pattern once**, then list 2–3 representative paths — do NOT enumerate every file or line number.
- **Link, don't restate** — reference `CONTEXT.md` terms and `docs/adr/` decisions instead of re-explaining them.
- Cut filler. Headers, tables, and checklists over prose paragraphs.
- Keep the whole plan to roughly one screen where possible.

---

## Verification (required in every plan)

- Describe how to test **end-to-end**: run the code, exercise MCP tools, run the test suite.
- Run **`gitnexus_detect_changes()`** before committing to confirm only the expected symbols/flows changed.
- State the pass/fail signal explicitly (expected output, exit code, or test name).

---

## Anti-Patterns (reject the plan if present)

- ❌ Skipping `gitnexus` or `context7` before planning.
- ❌ Vague steps ("update the logic", "fix the handler").
- ❌ Writing actual code / snippets in the plan instead of high-level intent.
- ❌ Enumerating every file/line instead of describing the pattern.
- ❌ Writing new code that duplicates existing utilities.
- ❌ No verification section, or no blast-radius check.

---

## Mini Template (copy-paste)

```markdown
# Plan: <short title>

## Context
<why — problem, trigger, intended outcome>

## Pre-work done
- [ ] gitnexus: query / context / impact run — blast radius: <summary>
- [ ] context7: latest docs pulled for <library>
- [ ] CONTEXT.md + docs/adr/ reviewed
- [ ] Plan read in full and understood

## Scope
- In: <...>
- Out: <...>

## Steps
<!-- High-level intent only — no code, no snippets. -->
1. <what to do, single purpose> — file: `path` — expected: <resulting behavior>
2. ...

## Files
- `path/one`
- `path/two`

## Verification
- <run/command/test> — pass = <signal>
- gitnexus_detect_changes() shows only: <expected symbols>

## Risks
- Blast radius: <from gitnexus_impact> — rollback: <how>
```

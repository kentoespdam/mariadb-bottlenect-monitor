# Domain docs

**Layout:** Single-context

**Location:**
- `CONTEXT.md` at repo root
- `docs/adr/` at repo root

**Description:** One global context for the entire repo. Skills like `improve-codebase-architecture`, `diagnose`, and `tdd` read from these files to learn the project's domain language and architectural decisions.

**Consumer rules:**
- `CONTEXT.md` - Contains the project's domain language, terminology, and high-level description
- `docs/adr/` - Contains architectural decision records (ADRs) documenting past decisions

**Multi-context:** Not applicable - this repo uses a single context.
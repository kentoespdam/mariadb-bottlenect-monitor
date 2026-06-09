## Truth Sources

This project maintains **three canonical sources of truth** — every design and implementation decision must be consistent with all three:

1. **`draft-prd.md`** — Product Requirements Document. High-level product goals, tech stack, architecture, and feature specs.
2. **`CONTEXT.md`** — Domain glossary. Every domain term (Bottleneck, Poll, Blocker, Auto-Heal, Hysteresis, etc.) is defined here with precise behavioral invariants. When a term appears in code or discussion, its meaning is whatever CONTEXT.md says it is.
3. **`docs/adr/`** — Architecture Decision Records. Records of specific design decisions with rationale, rejected alternatives, and consequences. ADR 0001 (fail-fast startup config) is the first. Every ADR's decision is binding unless superseded by a later ADR.

**Rules:**
- When `draft-prd.md` and `CONTEXT.md` conflict on a domain definition, `CONTEXT.md` wins (it is more detailed and was refined after the PRD).
- When `CONTEXT.md` or `draft-prd.md` reference a design decision documented in an ADR, the ADR's reasoning and constraints are authoritative.
- New code must not violate any invariant stated in these three sources. If an implementation requires a change to an invariant, the PR must first update the relevant source.
- README.md and other docs are derived from these three — treat them as helpful summaries but not authoritative.

## Truth Sources (Programming Rules)

1. **`PLAN_RULES.md`** — Plan-writing rules. Wajib dibaca dan diikuti saat membuat plan / plan mode. Setiap plan harus sesuai struktur, step-writing rules, dan verification yang ditetapkan.
2. **`CODE_RULES.md`** — Code-writing rules. Wajib diikuti saat menulis kode: DRY, KISS, YAGNI, ≤120 baris per file, komentar hanya "why", unit test untuk logic.

## Agent Skills

- **Issue tracker:** local markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.
- **Triage labels:** default five-role system. See `docs/agents/triage-labels.md`.
- **Domain docs:** single-context with CONTEXT.md and docs/adr/ at repo root. See `docs/agents/domain.md`.

## Non-Interactive Shell

**ALWAYS use non-interactive flags** with file operations — `cp`/`mv`/`rm` may be aliased to `-i`, which hangs the agent on a y/n prompt.

```bash
cp -f / mv -f / rm -f       # force, no prompt
rm -rf / cp -rf             # recursive
```

Others: `scp`/`ssh` → `-o BatchMode=yes`; `apt-get` → `-y`; `brew` → `HOMEBREW_NO_AUTO_UPDATE=1`.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **mariadb-bottlenect-monitor** (415 symbols, 751 relationships, 14 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/mariadb-bottlenect-monitor/context` | Codebase overview, check index freshness |
| `gitnexus://repo/mariadb-bottlenect-monitor/clusters` | All functional areas |
| `gitnexus://repo/mariadb-bottlenect-monitor/processes` | All execution flows |
| `gitnexus://repo/mariadb-bottlenect-monitor/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

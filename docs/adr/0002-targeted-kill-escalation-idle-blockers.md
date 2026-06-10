# ADR 0002 — Targeted KILL escalation for idle-in-transaction blockers

- **Status:** Accepted
- **Date:** 2026-06-10
- **Context term:** [Auto-Heal](../../CONTEXT.md#auto-heal)
- **Supersedes:** the V1 "`KILL QUERY` only" invariant previously stated in the Auto-Heal
  glossary entry.

## Context

V1 defined Auto-Heal as `KILL QUERY` only — abort the statement, keep the connection — and
explicitly *accepted* the idle-in-transaction blind spot: a transaction holding a lock with
no running statement has no query to cancel, so `KILL QUERY` is a no-op against it. The
stated bet was that the dominant scenario is one heavy *running* query holding the lock.

The 2026-06-10 stress test (`docs/stress-test-report-2026-06-10.md`) falsified that bet for
the case that matters. The blocker held its lock via an **idle** connection
(`COMMAND='Sleep'`, empty statement text). The monitor fired `KILL QUERY` **9 consecutive
times with zero causal effect**; the bottleneck cleared only when the workload's own 60s
timer committed. The monitor's heal was inert — it did not resolve the bottleneck, which is
its one job.

The product requirement is explicit: the monitor must *find the bottleneck source and kill
it* — except accounts on the Kill-Exclusion allowlist, which are backup processes that must
never be killed.

## Decision

Auto-Heal escalates **per blocker, by liveness**, decided from a single fresh PROCESSLIST
snapshot taken immediately before the kill:

- **Active blocker** (a running statement) → `KILL QUERY` (cancel the statement, keep the
  connection). Unchanged from V1.
- **Idle-in-transaction blocker** (`COMMAND='Sleep'` **AND** empty statement text) → `KILL`
  (sever the connection), which rolls back its transaction and releases the lock.

The two-signal idle test and the fresh snapshot are the same read that resolves the
blocker's identity, so escalation costs no extra round-trip and keys off the thread's state
at kill time, not a stale attribution.

This is gated by the **fail-safe identity resolution** that already guards every kill: the
exclusion allowlist and the monitor self-kill guard are matched against the *normalised*
host from that fresh snapshot, and an identity that cannot be resolved is treated as
**excluded — never killed**. Severing a connection is more forceful than cancelling a
statement, so this guard is load-bearing: a backup account must survive escalation.

## Why escalate only on idle, not always

The documented attribution→kill **race window** — the gap between naming a blocker and the
`KILL` reaching the server — still matters for *active* queries: the statement the monitor
saw may have finished and a new, innocent one begun on that connection. `KILL QUERY` bounds
the damage to "cancel whatever statement is running now". A blanket `KILL CONNECTION` for
every blocker would discard that bound for no benefit on the common case. An **idle**
connection has no statement for that race to apply to — the only thing it holds is the lock
we want released — so escalation there is both safe and necessary.

## Consequences

- Auto-Heal now resolves the idle-in-transaction case that V1 left open; the blind spot
  documented in the Auto-Heal glossary entry is closed, not accepted.
- `KILL` (connection) is harder to reverse than `KILL QUERY`. The exclusion / self-kill /
  unresolved-identity fail-safe is therefore a hard precondition of the escalation, not an
  optional check.
- The kill audit/outcome now distinguishes `killed_query` from `killed_connection`, so the
  durable log records which level of force was applied.

## Alternatives rejected

- **Keep `KILL QUERY` only (the V1 invariant).** Rejected: proven causally inert against the
  idle blocker in the stress test; the monitor would keep "healing" without resolving.
- **Blanket `KILL CONNECTION` for all blockers.** Rejected: discards the race-window bound
  that protects an active connection whose statement may have changed between attribution
  and kill. Force is escalated only where it is needed.

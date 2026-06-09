# ADR 0001 — Fail-fast startup configuration validation

- **Status:** Accepted
- **Date:** 2026-06-08
- **Context term:** [Startup Config Contract](../../CONTEXT.md#startup-config-contract)

## Context

The monitor reads its tunables from the environment once, at startup, before the first
poll. Two distinct classes of tunable exist:

- **Detection thresholds** — the Hysteresis entry/exit `Threads_running` values that
  *define* what "in trouble" means for this specific server. They depend entirely on the
  server's `max_connections` and workload; no universal value is safe.
- **Patience knobs** — N (Sustained Bottleneck), M (Heal Cooldown), K (Monitor Blindness),
  J (Attribution Blindness). These only answer "how many polls to wait"; a sane universal
  default exists for each and mis-tuning is at worst slightly slow or slightly chatty.

A configuration value can also be present-but-malformed: a non-integer, a negative count,
or an exit threshold that is not below the entry threshold.

The question this ADR settles: **when configuration is missing or incoherent, should the
monitor degrade gracefully (substitute a default and keep running) or fail fast (refuse
to start)?**

The default instinct in monitoring tools is the former — *always stay up*. A monitor that
crashes feels like it has failed at its one job. This ADR deliberately reverses that
instinct for the cases where a silent default would be dangerous.

## Decision

Sort every configuration outcome into three tiers; the tier decides the boot behavior:

1. **Patience knob absent → default and start.** A documented safe default is used. Floors
   are enforced (N, M ≥ 1 because they are safety rails; K, J ≥ 0).
2. **Detection threshold absent → refuse to start.** There is no safe default for "how many
   threads is too many *here*". Deploying without it is deploying blind.
3. **Any value malformed or incoherent → refuse to start.** The admin *said something* and
   it is not sane. Do not clamp, swap, or otherwise "fix" it.

Refusal is a clean crash with a clear message. Because the container runs `Restart=always`,
a refusal surfaces as a visible crash-loop rather than a quietly degraded "healthy" monitor.

## Why fail-fast over degrade-gracefully

- **A wrong detection threshold can cause a wrong-kill.** With Auto-Heal ON, an entry
  threshold silently defaulted too low would make the monitor see a Bottleneck under normal
  load and `KILL` an innocent query — the exact failure the whole design exists to avoid.
  The blast radius of guessing here is irreversible damage to a third party's query, so the
  monitor must not guess.
- **Silently "fixing" a malformed value is guessing the admin's intent.** Clamping a
  negative count or swapping a reversed threshold pair substitutes the monitor's judgment for
  the operator's stated (if mistaken) one. This violates the project's load-bearing
  principle: **the system reports, it never guesses.** A clear crash hands the decision back
  to the human who owns it.
- **A safety rail must not be disarmable through a config back door.** N=0 would heal on the
  first over-threshold poll; M=0 would permit a kill on the next poll. Allowing these would
  silently disable a safety guard without the admin ever explicitly saying "turn this off".
  Hence the floor of 1 on N and M is itself part of the coherence check — an out-of-range
  value is treated as incoherent and refused.
- **`Restart=always` makes refusal loud, not fatal.** Fail-fast does not mean "the monitor is
  gone". It means the failure is *visible* (a crash-loop an operator will notice) instead of
  *invisible* (a monitor that booted on a wrong default and is now mis-killing or blind).

## Consequences

- **A misconfigured deployment will not start.** This is the intended cost: a loud failure at
  deploy time is strictly safer than a silent mis-configuration discovered during an incident.
- **The split between tiers 1 and 2 is "blast radius of a wrong value".** A wrong patience
  knob is recoverable and mild, so it gets a default; a wrong detection threshold can drive a
  wrong-kill, so it stays mandatory. This boundary is a design invariant — new tunables must
  be classified by the same test before they are given a default.
- **An admin who wants "heal instantly, no waiting" cannot get it via N=0.** Disarming the
  sustained guard is deliberately *not* as easy as setting one env var to zero. This is an
  accepted ergonomic cost in exchange for the safety floor.
- **Validation lives only at the startup boundary.** Once past it, every tunable is trusted
  for the life of the process and never re-checked per poll.

## Alternatives rejected

- **Degrade gracefully (default everything).** Rejected: a defaulted detection threshold can
  cause a wrong-kill, and a defaulted-over malformed value buries operator error until an
  incident exposes it.
- **Clamp / auto-correct incoherent values.** Rejected: this is the monitor guessing the
  admin's intent, which the "report, never guess" principle forbids.
- **Warn-and-continue (log the problem but start anyway).** Rejected: a warning in a log no
  one is watching at deploy time is indistinguishable from silent degradation by the time it
  matters.

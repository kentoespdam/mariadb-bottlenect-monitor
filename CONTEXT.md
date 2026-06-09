# Context — MariaDB Auto-Heal & Bottleneck Monitor

A glossary of the domain language for this project. No implementation details.

## Glossary

### Bottleneck
A state in which the database is under thread/connection pressure — specifically
when `Threads_running` exceeds a configured threshold. A bottleneck is a *state*,
not an event: the system tracks whether it is currently in a bottleneck or not.

### Poll
One observation cycle: a single round of querying the database for its current state.
The poll is the system's fundamental unit of time — every duration the system reasons
about is counted in *polls*, never in wall-clock seconds. N (Sustained Bottleneck), M
(Heal Cooldown), K (Monitor Blindness), and J (Attribution Blindness) are all poll
*counts*. The wall-clock
interval between polls (~1 second) is operator-configurable, but the system's logic is
deliberately phrased in polls so that its semantics stay correct even if that interval
changes — "wait 5 polls" remains the right guard whether a poll is one second apart or
two.

A poll has **two sequential phases**, not one combined query, and the second runs only
on demand. Phase one is *detection*: a cheap `SHOW GLOBAL STATUS` read of
`Threads_running` that every poll always performs. Phase two is *attribution*: querying
the lock-wait chain (`sys.innodb_lock_waits`) to find the Blocker — and this runs **only
when phase one finds `Threads_running` above the entry threshold**. When the database is
healthy the poll stops after phase one. The reason is load: the lock-wait query is far
heavier than the status read and its result is almost always empty under normal load, so
running it every second would add needless pressure to the very database the monitor
exists to protect. Attribution becomes relevant only once detection proves there is
pressure to attribute.

Polls are scheduled by **fixed-delay, not fixed-rate**: the configured interval (~1s) is
the *gap the monitor waits **after** one poll fully completes* before starting the next,
not a clock that fires every T seconds regardless of how long a poll takes. This follows
directly from the **one persistent connection** invariant: polls run strictly **serially**
on that single connection — poll N+1 never begins until poll N has returned — so polls can
**never overlap and never queue up to catch up**. The case that forces the choice is a
*slow poll*: phase two (the heavy `innodb_lock_waits` attribution query) tends to slow down
precisely when the server is overloaded — exactly when the monitor is most needed. If
phase two takes 2.5s against a 1s target, the next poll simply starts 1s after this one
ends (at t=3.5, not racing to "catch up" the missed t=1, t=2 ticks). A fixed-rate scheduler
would instead pile up the missed polls — forcing either overlapping polls (which would
demand a second connection, breaking the one-connection invariant) or a burst of queued
queries slammed at an already-struggling database — making the very crisis it is observing
worse. The accepted consequence of fixed-delay is that the **effective poll interval widens
under load** (polls grow *less* frequent exactly during a crisis). This is correct, not a
defect: a slow attribution query is itself a *signal* of a pressured server, and the
slowdown applies natural **backpressure** — the monitor declines to add load when the
database can least afford it. None of this corrupts the counters, because they are counted
in *polls, never seconds*: "N=5" means five poll events whatever each one's wall-clock
duration, so a widening interval stretches the real-time response but leaves every guard's
semantics exactly intact. The ~1s interval is thus a target *inter-poll delay*, never a
guaranteed frequency.

Within a single poll the evaluation follows a **canonical order**, and the order is not an
implementation detail — it is what makes every locked invariant mechanically consistent
with the others. **Phase one is the gate.** The sequence is:

1. **Attempt phase one (detection)** — the `SHOW GLOBAL STATUS` read of `Threads_running`.
2. **If phase one fails → [[monitor-blindness]]:** `K++`, N freezes, the [[state-toggle]]
   booleans freeze, the temporal counter **M still ticks** (it tracks elapsed polls, not
   observation), and the poll **ends here** — no phase two, no kill. A blind poll cannot
   attribute and so cannot target, so there is nothing further to do but record the
   blindness and let time pass.
3. **If phase one succeeds → update the observational state** via [[hysteresis]]: move the
   Bottleneck [[state-toggle]] and the N counter against the entry/exit thresholds.
4. **If `Threads_running` is at or below entry**, the poll ends after detection (the lazy
   two-phase rule — phase two never runs on a healthy server).
5. **If above entry → run phase two (attribution)**, the lock-wait-chain query.
6. **If attribution fails → [[attribution-blindness]]:** `J++`, no target, no kill.
7. **If attribution succeeds and** N is satisfied **and** M has elapsed **and** a
   non-[[kill-exclusion|excluded]] root exists → **issue the single `KILL QUERY`** (then
   start M). At most one kill is *sent* per poll.
8. **Write the audit/alert** dictated by any state transition this poll.

The load-bearing point is step 2 versus the rest: the **temporal** counter M is ticked by
the *passage of the poll itself*, never gated on phase one succeeding — which is exactly
what makes [[heal-cooldown|"M keeps running while blind"]] true mechanically rather than by
fiat. The **observational** counters (N, the State Toggle booleans, J) move *only* on a
poll that actually observed their axis — N and the toggle need a successful phase one, J
needs to have reached phase two. Phase one's failure ends the poll early (no phase two, no
kill) but does not stop the clock that M tracks. This single ordering reconciles the
lazy two-phase rule, the blindness-freeze invariant, the temporal-vs-observational counter
split, and one-kill-per-poll into one consistent pass.

### Startup Config Contract
The rule governing how the monitor validates its configuration *once, at startup,
before the first poll* — the single boundary at which all tunables are checked. It
sorts every configuration outcome into three tiers, and the tier decides whether the
monitor starts, starts with a default, or refuses to start:

1. **Patience knobs absent → default.** N (Sustained Bottleneck), M (Heal Cooldown),
   K (Monitor Blindness), and J (Attribution Blindness) are *patience* tunables — they
   only answer "how many polls to wait". A sane universal value exists for each, and
   mis-tuning at worst makes the system slightly slow or slightly chatty, never unsafe.
   So if one is unset, the monitor uses a documented safe default and starts. The V1
   defaults are **N=5, M=10, K=3, J=5** (in polls; at the ~1s poll interval, roughly
   5s / 10s / 3s / 5s). Their ordering — **K(3) < N(5) = J(5) < M(10)** — follows one
   rule: the larger the blast radius of *delay*, the smaller the count. Total blindness
   (K) is reported fastest because a blind monitor is the most dangerous state; a kill
   (N) demands sustained certainty before acting; attribution blindness (J) is as patient
   as N because, like it, it is no silent emergency and its phase-two errors tend to
   self-correct; cooldown (M) is longest because it must wait for the system to truly
   settle (a large rollback plus queue unwind outlasts mere detection). These are only
   *defaults*, never claims of universal optimality — every server still overrides per its
   own `max_connections` and workload.
2. **Detection thresholds absent → refuse to start.** The Hysteresis entry/exit
   `Threads_running` thresholds are *not* patience knobs — they are the very definition
   of what "in trouble" means for *this* server, which depends entirely on its
   `max_connections` and workload. No universal default is safe: an entry threshold set
   too low while Auto-Heal is ON would make the monitor see a Bottleneck in normal load
   and `KILL` an innocent query — the exact wrong-kill the whole design avoids. Deploying
   the monitor without telling it "how many threads is too many here" is deploying it
   blind, so these stay mandatory and explicit, with no default.
3. **Any value malformed or incoherent → refuse to start.** Distinct from *absent*: here
   the admin *said something* and it is not sane — a non-integer, a negative count, or an
   exit threshold not *strictly* below the entry threshold. The coherence rule for the
   Hysteresis pair is `exit < entry` with a real gap: `exit > entry` is reversed, and
   `exit == entry` is just as incoherent because it collapses the hysteresis zone to zero
   width — the system would flip-flop in and out of Bottleneck at a single value, the exact
   chatter hysteresis exists to prevent. The monitor does *not* opine on how wide the zone
   should be beyond requiring a non-zero gap; that width is the admin's call per workload.
   Silently "fixing" it (clamping, swapping
   a reversed pair) would be *guessing the admin's intent*, which violates the project's
   "report, never guess" principle. A clean crash with a clear message is the honest
   response. Because the container runs `Restart=always`, this surfaces as a visible
   crash-loop rather than a quietly degraded "healthy" monitor.

The legal *lower bound* of a patience knob is itself part of this coherence check, and it
splits by whether the knob guards safety or only alert sensitivity. **N (Sustained
Bottleneck) and M (Heal Cooldown) have a floor of 1**: they *are* safety rails — N=0 would
heal on the very first over-threshold poll, disarming the sustained guard so a 1-poll
transient spike triggers a `KILL`; M=0 would permit a kill on the immediately following
poll, opening the kill-storm the cooldown exists to prevent. Allowing 0 would silently
disable a safety mechanism through a config back door without the admin ever explicitly
saying "turn this guard off", so a floor of 1 keeps the guard's minimum teeth. **K (Monitor
Blindness) and J (Attribution Blindness) permit 0**: they disarm no safety rail — at worst
K=0/J=0 floods alerts (declare blindness on the first failed poll), which is a legitimate
"alert me instantly" choice. The consequence accepted here: an admin who genuinely wants
"heal instantly, no waiting" cannot get it via N=0 — disarming the sustained guard should
*not* be as easy as setting one env var to zero.

The dividing line between tiers 1 and 2 is *blast radius of a wrong value*: a wrong
patience knob is recoverable and mild; a wrong detection threshold can drive a wrong-kill.
Validation lives only here, at the startup boundary — once past it, every tunable is
trusted for the life of the process and never re-checked per poll.

Because validation is a startup-only boundary, **every configuration value is immutable
for the life of the process** — there is no runtime-mutation path for *any* knob, and the
Auto-Heal ON/OFF switch is no exception. Changing any setting, including flipping Auto-Heal
between alert-only and active healing, means restarting the container (edit `.env`, then
`docker restart`), not a signal handler, file watcher, or control endpoint. This keeps the
"validate once, trust for life" invariant whole: a mutable switch would demand a re-validation
path that must stay atomic against the poll loop and coherent with the same three-tier rules,
introducing a new surface to secure and keep consistent — for a knob that `Restart=always`
already makes cheap and visible to change. An operator who wants an "emergency brake" to stop
killing mid-incident is served by the fast, explicit restart, not by a new runtime-config
channel; the brief monitor outage is itself observable rather than a silent in-place mode flip.

Startup also has *preconditions* beyond config coherence — the Durable Log path must be
writable, and a MariaDB connection via the `extra_port` (3307) must succeed — and these
are checked in a fixed order: **detection-threshold coherence → Durable Log writable →
MariaDB connection.** The ordering rule is *most-local-and-instant first, most-externally-
dependent last*. Config coherence is a pure in-memory check; log writability is a local
filesystem check; the DB connection is the only one that depends on a remote process and
can block on a network timeout. Checking the local, deterministic preconditions first means
an operator who has *both* a config typo and an unmounted log volume sees the config error
immediately rather than after a network timeout, and resolves every local problem in a
single boot instead of fixing them one crash-loop at a time. This ordering serves the same
"fail as fast and as clearly as possible" goal as the three-tier validation above.

The initial MariaDB connection is **not** [[monitor-blindness]]. Monitor Blindness is the
loss of a connection that was already standing — its K counter measures polls lost from a
*running* baseline, and its freeze protects state that already exists. At boot there is no
baseline, no poll, no state to freeze, so K does not apply. Instead, the initial connect
splits by failure kind. A **transient** failure (connection refused / timeout — the DB
merely not ready yet, common when the monitor and MariaDB containers co-start) gets a
**bounded retry with short backoff** before giving up; this absorbs the benign race without
masking a real problem. An **auth or misconfiguration** failure (credentials rejected, wrong
port answering) is *not* "not ready yet" — it is incoherent config, so it refuses immediately
with no retry, exactly like a malformed tunable. Either way, exhausting the bounded retry or
hitting an immediate refusal means **exit non-zero** and let `Restart=always` surface it as a
visible crash-loop — the monitor never enters its poll loop on a dead connection, because
doing so would disguise a startup misconfiguration as runtime blindness.

### Blocker
The single thread holding a lock that other threads are waiting on. The Blocker is
the root cause the system tries to identify — it is *not* simply the longest-running
or most recent query. Identified via the lock-wait chain (`sys.innodb_lock_waits`,
or `information_schema` as a fallback).

When the lock-wait chain reveals more than one waiting relationship, the Blocker the
system targets is the **deepest root** — the thread that holds a lock *and is not
itself waiting on anyone else*. An intermediate node (a thread that blocks others but
is itself stuck waiting on a deeper thread) is never the target: killing it is futile
because it holds no lock the deeper root hasn't already frozen. When several
independent roots exist (separate lock branches, each with its own non-waiting head),
the system targets the root blocking the **most waiters** — counted **transitively**,
the full subtree of threads that would be freed if this root died (in a chain
`Root → A → {B, C}`, killing Root frees A, which releases its own lock so B and C run,
so Root's waiter count is 3, not the 1 direct waiter). Counting transitively is faithful
to *why* "most waiters" is the rule: the value of a kill is the total lock pressure it
relieves downstream, not merely its immediate neighbours. This maximizes locks released
per single kill; ties are broken by **oldest transaction** (`innodb_trx.trx_started`,
the root whose transaction began earliest) — a deterministic rule with operational
meaning, not a mere artifact of connection order: the longest-held lock is the one
least likely to clear on its own and most likely to be genuinely stuck. Note this names
*which* thread is chosen — *how many* are killed per poll is the one-kill-per-poll
discipline of [[auto-heal]].

### Auto-Heal
The act of cancelling the Blocker's running query to relieve a Bottleneck —
specifically `KILL QUERY` (abort the statement, keep the connection alive), not a
full `KILL CONNECTION`. Cancelling the statement rolls back its transaction and
releases the lock, which is what frees the Bottleneck. Auto-Heal is opt-in and
defaults to OFF; by default the system is alert-only. Known blind spot: an *idle*
transaction holding a lock with no active statement has no query to cancel, so
`KILL QUERY` cannot release it — this case is accepted for V1 because the dominant
scenario is one heavy running query holding the lock, not an idle-in-transaction
session. When attribution does name an idle root, it gets **no special handling**: the
`KILL QUERY` is sent, the server accepts it syntactically, and — exactly as with any
kill — the poll loop, never the return code, decides whether it worked. An impotent
kill against an idle transaction is indistinguishable at the return-code layer from a
kill whose effect is merely slow to drain; both surface only as "the Bottleneck is
still here next poll." It therefore falls through the existing path: [[heal-cooldown]]
withholds the next attempt, and if the Bottleneck outlasts the cooldown it is already
in the "beyond healing capability, left for the operator" state that is locked
elsewhere. The idle-transaction blind spot is thus not a new signal or state — it is one
*instance* of "a kill may have no effect, and the poll loop is the verifier."

Auto-Heal issues **exactly one kill per poll** — it cancels the single chosen
[[blocker]] (the deepest root, tie-broken by waiter count), then *stops and lets the
next poll re-measure*. It never fans out to kill every blocker it can see in one
cycle, even when the lock-wait chain exposes several independent roots. This keeps the
blast-radius of any one cycle bounded to a single statement and stays faithful to the
lazy, observe-first loop: if that one kill relieved the Bottleneck, the next poll sees
`Threads_running` fall and no second kill ever fires; if it did not, [[heal-cooldown]]
withholds the next attempt for M polls, giving the system time to absorb the effect
before acting again. Killing many at once would be a guess that all of them are
genuinely stuck — but releasing the root often frees waiters that would have completed
on their own, so the system kills one and *watches*, consistent with "report, never
guess."

The lock-wait structure is in general a **graph, not a single linear chain**: one holder
can block many waiters, a waiter can wait on more than one holder, and the graph can split
into several **disconnected components**, each with its own deepest root that waits on
no one. When several independent roots exist (say R1 blocking 8 waiters and R2 blocking 3,
in separate components), the one-kill-per-poll rule still forces a *single* choice. The
existing tie-break is **not extended with a new rule for this case** — it is simply
understood to operate over the **global set of all deepest roots across all components**,
not within one chain: gather every component's deepest root into one candidate set, then
pick the single global winner by the already-locked order — **largest transitive waiter
count first, oldest transaction as the tie-of-tie**. R1 (8 waiters) wins because the one
kill the system is permitted this poll should free the most stuck threads and hand the
fastest recovery signal to the next poll. R2 is **not forgotten**: if the Bottleneck
persists — likely, with R2's 3 waiters still stuck — R2 becomes the remaining deepest root
with the most waiters and is killed on a later poll, spaced by [[heal-cooldown]] M. This
adds no fifth tunable and changes no rule; it only pins that "deepest root, tie-broken by
waiter count" reads across the whole graph, with the poll+cooldown rhythm draining the
remaining roots one at a time.

"One kill per poll" precisely means **at most one `KILL QUERY` *sent to the server* per
poll — not one *successful* kill per poll.** The dividing line is whether a `KILL` was
actually dispatched. Skipping a [[kill-exclusion]] root is *before* any action: no `KILL`
leaves the monitor, so falling through to the next eligible root within the same poll is
still zero kills sent and does not consume the poll's one action. But once a `KILL QUERY`
has actually landed on the server, the poll's single action is spent regardless of the
return code. In particular, an `Unknown thread id` reply — the target finished and released
its own lock between attribution and execution — **ends the poll with zero *effective* kills
but one *sent* kill**, and the monitor does **not** chain to the next root in the same cycle.
It waits for the next poll to re-measure from a fresh `SHOW GLOBAL STATUS` and a fresh
attribution pass. The reason is faithfulness to observe-first: the vanished thread means the
lock-wait chain has very likely shifted, so chaining a second kill onto the now-stale
in-poll snapshot would be guessing the new state rather than measuring it. Re-measuring next
poll is the honest move — one server action, then look again.

The ON/OFF switch governs **only the execution of `KILL`, never the reporting path**.
In OFF mode the monitor still detects the Bottleneck, still resolves the [[blocker]],
and still fires the [[state-toggle]] alert on the transition to Bottleneck — identical
in every way to ON mode — but simply does not issue the `KILL QUERY`. There is **no
separate "would-have-killed" alert** at the point where a kill would otherwise fire:
the operator already knows there is a Bottleneck, already has the identified Blocker in
the same alert, and already knows Auto-Heal is OFF because they set it. A distinct
"sustained, target identified, kill withheld because OFF" notification would carry no
new information and would duplicate state already reported. OFF means "take no execution
action", not "add a new reporting layer" — it introduces no new State and no new alert
class. The *only* observable difference between ON and OFF is the presence or absence
of the `KILL QUERY` itself.

The system trusts the `KILL`'s **return code only for *syntactic* classification** —
the immediate fact of whether the command was accepted, refused on privilege (→ [[heal-capability-failure]]),
or found its target already gone (benign, recorded, move on). It does **not** confirm
the *effect* synchronously. `KILL QUERY` returns success the moment the command is
accepted, not when the lock is actually released — a large transaction can take time to
roll back. Confirming the effect inline would block the poll loop precisely while the
monitor must keep watching everything else (including its own [[monitor-blindness]]).
So effect-verification is delegated to the natural poll loop: if the lock truly releases,
`Threads_running` falls below the exit threshold and a [[recovery-alert]] fires; if it
does not, the Bottleneck simply persists and [[heal-cooldown]] withholds the next kill.
The loop *is* the verifier. A consequence accepted here: the [[kill-audit-record]] records
the *action* ("I sent KILL on thread X"), never a promise of *outcome* — whether the lock
ultimately drained is told separately by the Recovery Alert.

### Kill-Exclusion (Allowlist)
A list of trusted database accounts that the system must NEVER kill — even when one
is the identified Blocker and even when Auto-Heal is ON. Each entry is an account
identity in `user@host` form (matching MariaDB's own account model), matched as
AND (both user and host must match). `host` may use the `%` wildcard. The monitor's
own account is always excluded. A consequence: if an excluded account ever becomes
the genuine stuck Blocker, the system alerts but cannot heal — a human must decide.

The allowlist is a **target-eligibility filter, not a heal kill-switch for the whole
poll.** When several independent [[blocker]] roots exist and the largest-waiter root
happens to be excluded, the excluded root is *skipped — never killed* — and Auto-Heal
falls through to the next eligible (non-excluded) root in waiter-count order, killing
that one instead. The one-kill-per-poll discipline is preserved: the excluded root is
passed over, not killed alongside another. The skipped excluded root is still surfaced
to the operator (the "excluded account is the genuine Blocker" alert above), so the
human learns it is stuck and protected even as pressure is relieved elsewhere. Only
when *every* root in the chain is excluded does the poll end with zero kills — alert,
no heal — because there is no eligible target left and the allowlist invariant is
absolute: an excluded account is never killed under any circumstance.

### Blocker Identity Resolution
The process of turning the Blocker thread into a canonical `user@host` account
identity — the identity used both to test against the Kill-Exclusion allowlist
*before* killing and to write into the Kill Audit Record. The raw source is
`information_schema.PROCESSLIST` (directly, or via `innodb_trx` joined to it), whose
`HOST` column includes the ephemeral connection port (e.g. `10.0.0.5:54221`),
whereas MariaDB's account model and every allowlist entry use host *without* a port
(e.g. `10.0.0.5` or `%`). The port must therefore be stripped — take the part before
the final `:` — so `10.0.0.5:54221` normalizes to `10.0.0.5` before matching.
Matching is **fail-safe**: if the host cannot be parsed or normalized for any reason,
the thread is treated as *excluded* (as if it matched the allowlist) and is never
killed — a wrong-not-kill is always safer than a wrong-kill. The same normalized
identity is what gets recorded in the audit trail, so the allowlist decision and the
audit record always describe the same account.

There is an irreducible **temporal gap** between the moment attribution names a thread
(phase two reads `innodb_lock_waits`/`innodb_trx` and resolves root thread X running the
holding query Q1) and the moment `KILL QUERY X` actually reaches the server a few
milliseconds later. Because `KILL QUERY` cancels the *current statement* but leaves the
*connection* alive, X may in that gap have finished Q1 on its own and moved on to an
innocent query Q2 on the same connection — so the kill lands on Q2, the wrong query on the
right connection. This window **cannot be closed** without a transaction-level lock that
this architecture deliberately refuses; a compare-and-kill would still race and merely add
the *illusion* of atomicity. The system therefore does not chase perfect targeting. It
relies on the three principles it already holds: (1) **bounded damage** — `KILL QUERY`
cancels at most one statement, and X's connection and transaction survive, so a misfire is
a single cancelled query on an already-busy connection, never a severed session; (2) **the
[[poll|poll loop]] is the verifier** — if Q1 had in fact already cleared, the next poll
sees `Threads_running` back below exit and issues no second kill, while if the Bottleneck
persists a later attributed poll simply targets it afresh; and (3) **record the intent, not
a guess** — the [[kill-audit-record|intent line]] pins the *trx_id* of the targeted
transaction, so if the kill ever lands on a different statement, forensics can reconstruct
that the thread had moved on ("we targeted trx T1; the connection was on T2 by send time").
The race is accepted **explicitly and recorded**, not hidden — the same "report, never
guess, bound the blast radius" discipline that governs every destructive action here.

### Sustained Bottleneck
A Bottleneck that has persisted across N consecutive polls rather than appearing in
a single sample. Auto-Heal acts only on a *sustained* Bottleneck, never on the first
poll that crosses the threshold. This distinguishes a transient spike (a momentary
`Threads_running` surge that resolves on its own) from a genuine stuck condition. The
detection threshold and the *execution* guard are separate concerns: detection still
flips the Bottleneck state immediately (and may alert), but killing waits for the
sustained condition.

The N counter is governed by **Hysteresis**, not by the entry threshold alone. It
accumulates as long as `Threads_running` stays **above the exit threshold**, and resets
*only* when the value drops below exit — the same boundary at which the Bottleneck state
itself toggles back to Normal. It does **not** reset on a poll that merely dips below
*entry* while remaining above exit: that zone (between exit and entry) is by definition
"still in trouble, not yet recovered", so a brief dip into it is part of the same
sustained episode, not a fresh start. Resetting N on every minor oscillation around entry
would defeat Hysteresis for the most common pressured-server case — a workload flapping
right at the entry line would never accumulate N and the first kill would never fire,
even though the server is plainly stuck. Entry triggers *entering* the Bottleneck state;
exit triggers *both* leaving it and resetting N. This keeps N coherent with the
edge-triggered State Toggle: the count lives exactly as long as the Bottleneck state does.

N lives entirely on the **detection axis** and is **never touched by attribution failure**.
A poll can succeed at detection (`Threads_running` above exit, so N accumulates) yet fail at
attribution — the lock-wait chain comes back empty or errors, an [[unattributed-bottleneck]]
with no [[blocker]] to target. When this happens *at or past N*, the accumulated N stays
**fully intact**: the kill is withheld only because there is no target this poll, not because
the Bottleneck's maturity was rolled back. The instant a later poll is attributed again with
`Threads_running` still above exit, a *single* attributed poll authorizes the kill — the
system does not re-wait N. Resetting N on attribution failure would conflate two orthogonal
guards: N measures *how long this Bottleneck has proven real* (a pure function of
detection/threshold), while attribution measures *whether a valid target exists right now*.
Punishing a genuinely persistent Bottleneck because the lock-wait chain was momentarily
unreadable would needlessly delay the heal. The two axes keep their own counters and never
reset each other: if attribution keeps failing for J consecutive polls it raises its own
[[attribution-blindness]] alert independently, while N goes on counting on the detection
axis untouched.

A third axis must also leave N alone: **[[monitor-blindness]]**. When a poll is blind —
`SHOW GLOBAL STATUS` itself fails, so there is *no* `Threads_running` reading at all — N is
**frozen at its last observed value**: it neither advances nor resets while blind. N counts
*observed* over-exit polls, and a blind poll observed nothing, so it grants no licence to move
N in either direction. Advancing N during blindness would be guessing the condition is still
bad; resetting N would be guessing it has recovered — both forbidden by "report, never guess",
and both dangerous because blindness often correlates with the server being at its *worst*
(connection exhaustion and Bottleneck arrive together). So N simply holds the last fact it
genuinely saw. The instant vision returns, the *first* sighted poll decides N's direction by
the normal Hysteresis rule: still above exit → resume accumulating from the frozen value;
below exit → reset to zero as usual. During the blind stretch the [[monitor-blindness]]
counter K is the axis doing the work — it advances each blind poll and raises its own alert at
K — while N waits, untouched. Yet a third orthogonal pair of clocks: K measures blindness, N
freezes pending the eyes' return.

### Monitor Blindness
The condition in which the monitor cannot observe the database at all — its poll
(`SHOW GLOBAL STATUS`) fails because the connection is refused, dropped, or timing
out. This is treated as a *reported* status, never silent: a monitor that has gone
blind without anyone knowing is more dangerous than the Bottleneck it was meant to
catch, and blindness tends to strike precisely when the database is worst off
(connection exhaustion and Bottleneck are correlated). After K consecutive failed
polls the system raises an alert so an admin checks the real state immediately. To
resist exactly this failure mode, the monitor connects through MariaDB's emergency
`extra_port` (3307) as its *primary* path — that port still accepts connections when
`max_connections` is full, which is the very moment the monitor must stay alive and
able to `KILL`.

Monitor Blindness is **cause-agnostic**: it does not distinguish *failing to connect
in the first place* (refused/timeout when opening) from *a live connection dropping
mid-flight* (server restart, network drop, the `extra_port` suddenly refusing). From
the only question that matters — "can I see the database right now?" — the two are
identical, so both feed the *same* K counter rather than spawning a separate class.
This is why the monitor holds **one persistent connection across polls** rather than
opening a fresh one each poll: a per-poll connect would pile connect/auth load onto
the very database it is protecting, and doing so every second is at its most fragile
exactly when `max_connections` is full. When a poll fails because that persistent
connection died, the monitor attempts to **reconnect on the next poll** (for V1: every
poll, no backoff — the ~1s poll interval is its natural rate limit), and each failed
reconnect attempt simply counts as one more failed poll accumulating toward K.

Cause-agnostic at the **state** level does not mean cause-blind at the **forensic**
level. The two operationally distinct realities behind a blind poll — *server alive,
connection lost* (a TCP drop, a `wait_timeout` cull, a fast MariaDB restart; the cure is
simply to reconnect) versus *server unreachable* (crashed, OOM-killed, shut down;
`extra_port` answers with connection-refused or a hard timeout and reconnect keeps
failing) — are **recorded with their specific failure kind in the [[durable-log]]**
(refused / timeout / mid-flight drop) so an operator can later tell which one happened.
But that classification is **forensic only; it never branches the state machine**. The
reason is that at the granularity of a single poll the signals are genuinely ambiguous —
a `connection refused` during a two-second restart looks identical to a permanently dead
server — and choosing a branch on an ambiguous signal would be guessing. The K counter is
*already* the mechanism that resolves the ambiguity honestly: it waits across several
polls before raising the alert, so a brief restart self-heals (reconnect succeeds, K
resets) while a real outage accumulates to K and alerts. The alert fires at K **whatever
the cause**; the operator reads the logged failure kind to interpret "dead server vs
flaky network". No new State, no new alert class, no fifth tunable — only a richer audit
trail behind the one blindness signal that already exists.

### Attribution Blindness
The condition in which detection succeeded but *attribution* failed: phase one of a
poll confirmed a Bottleneck (`Threads_running` over threshold), yet phase two — the
lock-wait chain query that would name the Blocker — itself *errored* (timed out, was
refused, or could not be parsed) rather than returning a result. The crucial distinction
is from an [[unattributed-bottleneck]]: there, the chain query *succeeded* and was
genuinely empty, so the system truthfully knows there is no lock-holder; here, the query
never delivered an answer, so the system knows *nothing* about whether a Blocker exists.
Reporting this as "no Blocker found" would be a lie — the honest report is "I can see
the pressure but I am blind to its cause." It is therefore its own reported class, kin
in spirit to [[monitor-blindness]] (total blindness, phase one) but partial (phase two
only): detection works, attribution does not. Consequences: Attribution Blindness can
*never* trigger Auto-Heal — there is no identified target to `KILL` — and it is alerted
as a distinct blindness condition, never folded into the Unattributed Bottleneck count.
Like every other reported state, it is not raised on a single stumble: it fires only
after **J consecutive polls** whose phase two errors, where J is its own tunable —
sibling to N (Sustained Bottleneck), M (Heal Cooldown), and K (Monitor Blindness), and
deliberately *separate from K*. The reasoning for separating J from K is that the two
blindnesses fail for different reasons and at different costs: K guards total blindness
(the cheap `SHOW GLOBAL STATUS` read itself failing, which means the monitor is wholly
disconnected), while J guards partial blindness (the heavier lock-wait query failing
under load, which is more likely to be transient and self-correcting). Folding them into
one threshold would force a single number to serve two failure modes with different
tolerances, so J is configured independently.

As a lingering, J-gated state, Attribution Blindness owns a [[recovery-alert]] like every
other reported state — but it clears by **two distinct exit paths**, and the alert must
name which one closed it. Path one, *attribution recovered*: phase two succeeds again
(whether it now finds a Blocker or comes back genuinely empty), so the monitor can see the
cause once more — the crisis may still be live, but visibility is back. Path two,
*bottleneck gone*: `Threads_running` falls below the exit threshold, so phase two is never
run again (it only runs above the entry threshold) — the blindness vanishes not because
attribution healed but because there is no longer anything to attribute. The two mean very
different things to an operator ("I can see the cause again" vs. "the pressure passed before
I ever could"), so the Recovery Alert states which path closed it rather than emitting a
bare all-clear.

Neither exit path can be reached *through* [[monitor-blindness]]. If the monitor is already
Attribution-Blind (`true`) and then falls into the deeper failure where phase one itself stops
answering — `SHOW GLOBAL STATUS` fails, total blindness — the Attribution Blindness boolean is
**frozen at `true`**, exactly as N and every other [[state-toggle]] boolean freeze across a
blind stretch. It is *not* cleared by path one, because path one means phase two *succeeded
again*, and while phase one is blind phase two is never even run — it has not recovered, it is
simply unobserved, and firing "attribution recovered" here would claim a sighting that never
happened. Nor is it cleared by path two, since `Threads_running` is unreadable, so the monitor
cannot know the Bottleneck is gone either. The deeper [[monitor-blindness]] condition takes over
as the louder reported state (K advances, its own up-edge fires), while Attribution Blindness
waits frozen underneath. Only when phase one answers again does the first sighted poll decide the
exit by the normal rule: phase two now runs and succeeds → path one; or `Threads_running` is below
exit → path two. Blindness at the deeper axis suspends the shallower blindness's bookkeeping; it
never resolves it.

### Heal Capability Failure
The condition in which Auto-Heal is ON and the system correctly identifies an
attributed Blocker, but the `KILL QUERY` is *rejected by the database itself* —
typically because the monitor's account lacks the required privilege (e.g.
`CONNECTION ADMIN` / `PROCESS` to kill another account's thread). This is the most
dangerous *silent* failure mode of healing: the operator believes the system is
protecting the database, while every kill is in fact being refused. It is therefore
treated like Monitor Blindness — a hard, reported alert in its own right ("the
monitor can see but cannot heal"), not a quiet log line. It is distinct from the
*benign* kill error where the target thread has already vanished (the query finished
or the connection dropped just before the kill): that case needs no special handling
because the problem has already resolved itself — it is recorded and the system moves
on. Only the capability/privilege rejection escalates.

Heal Capability Failure is reserved strictly for **deterministic, permanent** rejection
— privilege denial, where retrying cannot change the outcome because the privilege will
not spontaneously appear. A third, distinct kill outcome is **transient kill failure**:
the kill attempt itself fails to land — a timeout sending the `KILL`, or the monitor's
connection dropping at the very moment of the kill — which is neither "I lack the right"
(privilege) nor "there was nothing to kill" (target gone). A transient failure is **not**
treated as Heal Capability Failure, because labelling a momentary hiccup as "the monitor
permanently cannot heal" would be a false hard alert that erodes trust in the alert's
specific meaning. Instead it is left to the natural poll loop, exactly as kill-*effect*
verification is (see [[auto-heal]]): if the dropped connection is the cause, the next poll
cannot read status either, so it falls into the existing [[monitor-blindness]] (K) path;
if only the kill timed out while the connection lives, the Bottleneck stays lit, the
[[sustained-bottleneck]] guard (N) is still satisfied, and the next poll simply **retries
the kill naturally** — no [[heal-cooldown]] withholds it, because Cooldown is triggered
only by a *successful* kill. A consequence accepted here: a database that consistently
times out every kill never escalates to Heal Capability Failure — it persists instead as
an un-clearing Bottleneck whose entry alert is never closed by a [[recovery-alert]], which
is itself the honest signal ("Bottleneck won't clear despite Auto-Heal ON"). No crisis
goes silent.

Heal Capability Failure fires on the **first** privilege rejection — its effective threshold
is **one**, and it deliberately gets **no poll-count tunable of its own**. The four tunables
N (Sustained Bottleneck), M (Heal Cooldown), K (Monitor Blindness), and J (Attribution
Blindness) are the **complete and final** set; this condition adds no fifth. The reason is a
fundamental difference in what it is sieving. N, K, and J all exist to ride out **transients** —
a momentary load spike, a single lock-wait query that times out, one dropped `SHOW GLOBAL
STATUS` — each of which can self-heal on the very next poll, so "wait a few polls before
alerting" suppresses chatter without hiding anything real. A privilege rejection is the
opposite: it is **deterministic and structural**. If `monitor_user` lacks `CONNECTION ADMIN`,
it will not spontaneously acquire it next poll — only an admin `GRANT` changes the outcome.
Waiting J polls for a result guaranteed to repeat identically would merely *delay the alert on
the most dangerous silent failure mode* while filtering nothing. The kill error code already
draws the line cleanly — an "access denied" / privilege error is structural (alert at once),
whereas `Unknown thread id` is the target vanishing (a benign, syntactically-accepted outcome
that arms nothing) and a send timeout is the transient class routed to the poll loop above. So
syntactic classification of the error code does all the separating a tunable would, without one.
Its [[recovery-alert]] has a single unambiguous exit: a `KILL` **succeeds again** after a prior
rejection — i.e. the admin has granted the privilege — closing the loop the first rejection
opened.

### Alert Payload
The deliberately minimal content of a real-time notification — sized to let an
operator *decide urgency at a glance* (e.g. on a phone at 3am), not to fully document
the incident. The dividing principle: the **alert is for deciding, the Kill Audit
Record is for forensics**. An alert therefore carries only what answers "how bad, and
what did the system do?" — for a Bottleneck: `Threads_running` at trigger, the Blocker's
**identity and metrics only** — thread id, `user@host`, transaction age, and waiter count —
plus whether Auto-Heal acted; it carries **no query text at all, not even a truncated
snippet**, because the raw query is exactly where literal PII hides (`WHERE email='…'`,
`INSERT … VALUES('…')`) and Telegram is an *external* channel that may cache or index a
message beyond the operator's control. The alert thus stays on the safe side of the trust
boundary: it carries enough *identity* to correlate the incident to the durable log and to
decide urgency at a glance, while the durable log — inside the trust boundary, host-volume
backed — is the *only* place the full raw query text lives. For an
Unattributed Bottleneck: `Threads_running` plus a "no Blocker — needs human eyes"
marker; for Attribution Blindness: `Threads_running` at trigger, the J-count reached
together with the last phase-two error kind (timeout/refused/parse-fail), and a marker
that deliberately reads *differently* from the Unattributed one — "pressure present, cause
unseeable — needs human eyes" — so the operator never confuses "I looked and there is no
Blocker" (Unattributed) with "I could not look at all" (Attribution Blindness); it carries
no lock-wait chain or Blocker query because those are precisely what could not be obtained;
for Monitor Blindness: the consecutive-failure count and the last failure kind
(refused/timeout/dropped); for Heal Capability Failure: the Blocker `user@host` and the
database's rejection message; for a Recovery Alert: which condition cleared and how long
it lasted. The full lock-wait chain, the raw query text in full, and complete kill detail
deliberately live *only* in the durable log (the Kill Audit Record) — duplicating them
into the alert would make it unreadable on a phone, add nothing the audit trail does
not already hold, and — in the query's case — leak PII across the trust boundary.

### Alert Delivery Contract
The rule that fixes what an alert *is* as a promise: a [[alert-payload|notification]] is
**best-effort**, never the system's source of truth — the durable local log (the same
rotated file that holds the [[kill-audit-record]]) is. Every alert is *attempted* over its
external channel — **V1 fixes that channel to a single concrete one: Telegram** (one
best-effort HTTP POST to the Bot API, no approval/template/per-message-cost friction, so it
maps cleanly onto the "one HTTP call" this contract promises). A heavier channel such as
WhatsApp Business — which would require a Meta Business account, a verified number, and
approved system-initiated templates — is deliberately *not* in V1. The channel runs over an
outbound network that
can fail precisely when it is most needed — a struggling server often means a struggling
network, so the moment an operator most needs the alert is the moment delivery is most
likely to drop. To keep that from becoming a brand-new *silent* blindness — the system
"believing" it notified when the message never landed — the **outcome of each send attempt
(delivered / failed-to-send, with the failure kind) is itself written to the durable log**.
A failed delivery is therefore never thrown into the void; it becomes one more greppable
line, so an operator can always reconstruct the full truth from the log even with the
notification channel entirely down. This is the same separation that governs
[[alert-payload]] — *alert is for deciding, the durable record is for truth* — extended one
level: an external channel is structurally unfit to be a source of truth because it is at
its most fragile during a crisis. A consequence accepted here: an operator who watches only
the chat channel and never reads the log can still miss an alert that failed to send — but
that is **not** silent blindness *from the system's side*, which recorded the attempt
honestly; reading the durable log is the operator's responsibility, consistent with "the
system reports, it does not guess". Retry or a second escalation channel (try WhatsApp when
Telegram fails) is a legitimate enhancement on top of this — and is **explicitly deferred
beyond V1**, not built now — but it is never a *replacement* for the contract: the end of
any delivery chain can still fail, so the durable log remains the floor. Pinning a single
V1 channel rather than building the escalation chain up front follows the same discipline as
the rest of the design — choose the simplest path that honors the contract, and do not build
for a hypothetical future need before it is real. One more guarantee makes "best-effort"
precise in *time*, not just in outcome: the send is bounded by a **hard timeout and may
never block the poll loop**. A [[poll]] is the system's fundamental unit of time — every
[[sustained-bottleneck]], [[heal-cooldown]], and blindness window is counted in polls — so
anything that can stall the loop threatens the whole detection model. The danger is concrete:
an alert fires *because* the server is in trouble, the outbound network is often sick at
exactly that moment, and an un-bounded HTTP POST to the channel could hang for tens of
seconds. If that send ran inline and unbounded, the next poll would be delayed and the
monitor would go blind in the middle of the very crisis it is watching — the same
"monitor must never become the cause of the crisis it monitors" principle that bounds the
[[durable-log]]. So the send is capped by a short, explicit timeout; on expiry it is recorded
as `failed-to-send (timeout)` — one more greppable failure kind on the durable log — and the
poll loop proceeds without waiting. Delivery is best-effort and low-value next to keeping the
detection heartbeat steady; it is therefore never granted the power to hold a poll hostage.

### State Toggle
The **edge-triggered** mechanism that makes every lingering state notify only on its
*transitions* — once when the condition begins (up-edge) and once when it ends (down-edge,
i.e. a [[recovery-alert]]) — never repeatedly, poll after poll, while the condition merely
persists. The technical core: each such condition holds a **boolean status** ("am I
currently in this condition?"), and an alert fires only when that boolean *changes value*,
not whenever it *is* true. This is what prevents an alert flood — a Bottleneck that lasts
500 polls sends **one** entry alert and **one** Recovery Alert, not 500 identical ones.
The same mechanism binds the four sustained conditions — [[bottleneck]],
[[monitor-blindness]], [[attribution-blindness]], and [[heal-capability-failure]] — under
one shared behaviour, which is why other entries can simply call them "State-Toggled"
rather than re-explaining edge-triggering each time. It also explains why a successful
[[auto-heal]] execution has *no* Recovery Alert: a single kill is a discrete *event*, not
a lingering *state*, so it never enters the State Toggle machinery at all — there is no
boolean to flip back, nothing to recover from.

The State Toggle's guarantee is strictly **intra-condition**: it stops one *single*
condition from flooding, but deliberately does **no** *inter-condition* correlation.
When several conditions light up inside the same crisis window — say a [[bottleneck]]
up-edge, an [[attribution-blindness]] up-edge, and a [[heal-capability-failure]]
up-edge all within seconds — V1 emits them as **independent** alerts and does not bundle
them into one "incident". This is intentional, not an oversight: each condition carries a
*different* operational meaning that demands a *different* operator response (Bottleneck =
"there is pressure", Attribution Blindness = "I cannot see the cause", Heal Capability
Failure = "I cannot heal"), so collapsing them into a single notification would risk
hiding the very dimension that decides the operator's next move — the opposite of "no
silent crisis". Because each condition is already capped at one up-edge plus one
[[recovery-alert]], the volume stays bounded (a handful of honest alerts per crisis, never
a flood). Cross-condition bundling or suppression is a legitimate UX enhancement for a
later version, but it introduces an "incident" state machine that is complex and
hard-to-reverse, so it is explicitly out of V1 scope.

At startup every State-Toggled boolean begins at **false (`Normal`)**, regardless of what
the first poll reads — even if that poll already lands above the entry threshold or inside
the [[hysteresis]] zone. An edge fires only on a transition the monitor *witnesses itself*:
the first move into Bottleneck requires the monitor to observe `Threads_running` cross
*above* the entry threshold while running. It never infers a starting state it did not see
the transition into. The consequence is deliberate and conservative about killing — if the
monitor boots in the middle of a live incident (e.g. restarted while `Threads_running` is
already 30 in a `40/20` band), detection waits until the value genuinely crosses the entry
threshold under its own observation, and only then does the Sustained Bottleneck count begin.
No [[auto-heal]] is ever triggered off an assumed state whose up-edge was never witnessed —
the monitor acts only on edges it actually saw, consistent with "report, never guess".

This "begin at false every boot" rule is **deliberately not persisted across restarts**:
no State-Toggled boolean is written to disk and re-loaded at boot. The accepted consequence
is a **re-alert** when the process restarts mid-Bottleneck (a crash under `Restart=always`,
or an operator restart to flip [[auto-heal]] per the [[startup-config-contract]]): the old
process had its Bottleneck boolean at true and had already alerted, but the fresh process
starts at false, its first poll observes `Threads_running` above entry, fires a false→true
up-edge, and sends the Bottleneck alert again — for a condition that never actually recovered.
This is correct, not a bug to suppress: the new process genuinely observed the Bottleneck for
the first time, and the duplicate alert is itself useful signal — it tells the operator "the
monitor just restarted while there was an active problem". Suppressing it would require
disk-backed state plus a staleness judgement ("is the saved state still true after the monitor
was down two hours, during which the server may already have recovered?"), which trades a few
honest extra alerts for a persistence path that can desynchronise from reality. Every boot
measures from the real state at that moment and starts clean; a handful of duplicate alerts
is far cheaper than a persistent, possibly-stale state machine.

A State-Toggled boolean is **frozen across a blind stretch**, exactly as its companion
[[sustained-bottleneck]] count N is. While the monitor is in [[monitor-blindness]] — no
`Threads_running` reading at all — the boolean is **not flipped**: a `true` Bottleneck stays
`true`, because flipping it either way would be guessing an unobserved transition, the same
licence that "report, never guess" denies N. The edge is **level-triggered on the last
*observed* state**, never on wall-clock time, so it does not matter that the real recovery may
have happened *during* the blindness. Concretely: Bottleneck is `true` and alerted, the monitor
goes blind for several polls (K advances, Monitor Blindness raises its own up-edge alert), and
the first poll that sees again reads `Threads_running` already **below exit** — the server
recovered unobserved. That first sighted poll is the first *witnessed* `true→false` edge, so the
[[recovery-alert]] **fires there, normally** — delayed, not lost. The monitor never claimed its
alerts were real-time, only that they are honest about what was seen; the Recovery Alert's
timestamp says "recovery seen at poll X", and the operator already has the preceding Monitor
Blindness alerts for context, so the sequence reads cleanly: Bottleneck up-edge → blindness
(K alert + its own recovery when sight returns) → Bottleneck recovery. Withholding the Recovery
Alert because "the moment passed while blind" would be the opposite error — suppressing a fact
the monitor genuinely observed, leaving the operator hanging on the last-known Bottleneck status.
So the rule is symmetric with N: blindness freezes the boolean, and the first sighted poll fires
whatever edge it actually witnesses.

### Recovery Alert
The paired "all-clear" notification emitted when a sustained, State-Toggled condition
*ends* — the down-edge that closes the loop opened by its up-edge alert. Every
condition the system reports as a lingering *state* (rather than a discrete event)
owns both edges: it alerts once when the condition begins and once, as a Recovery
Alert, when it clears. This applies to the four sustained conditions — a Bottleneck
clearing (`Threads_running` falling below the exit threshold via Hysteresis), Monitor
Blindness ending (a poll succeeds after K failures), Heal Capability Failure
lifting (a `KILL` succeeds again after privilege rejection), and Attribution Blindness
clearing (see that entry — it has *two* distinct exit paths the alert must name). Its purpose is to spare
the operator from uncertainty: without an explicit all-clear, a silent *absence* of
further alerts is indistinguishable from the monitor itself having died. A discrete
event that is already complete the moment it happens — a single successful Auto-Heal
execution — has no Recovery Alert, because there is no lingering state to clear.

### Durable Log
The local, persistent file that is the system's **single source of truth** — the floor
beneath every other record. Both the [[kill-audit-record]] and each alert's delivery
outcome (see [[alert-delivery-contract]]) live here, and the contract that makes "durable"
real is twofold. First, **persistence outlives the container**: the monitor runs in Docker
under `Restart=always`, so a log written to the container's own ephemeral filesystem would
*vanish on every restart* — precisely the worst moment, because a restart often happens
*because* of the crisis the log was meant to record. The Durable Log must therefore be
written to a path backed by a host volume (bind mount or named volume), outside the
container's lifecycle, so its history survives crash, OOM, and redeploy. Second, **its
writability is a startup precondition**: if the log path is missing or not writable, the
monitor *refuses to start* rather than running with a silent hole where its source of truth
should be — the same fail-fast posture the [[startup-config-contract]] applies to detection
thresholds, on the same principle that a monitor unable to perform a core duty must crash
visibly (a `Restart=always` crash-loop) rather than degrade quietly. The reasoning mirrors
the [[alert-delivery-contract]] one level deeper: an *external* channel is structurally
unfit to be the source of truth because it is most fragile during a crisis; by the same
logic, an *ephemeral* store is unfit because it is most likely to be wiped during a crisis.
The truth must rest on something both local *and* persistent. Writing additionally to
stdout (for `docker logs`) is a permitted convenience, but it is never the source of truth —
only the durable host-backed file is.

Durability does not mean *unbounded*: the Durable Log is **rotated with a guaranteed disk
ceiling**, because a source of truth that grows without limit is itself a liability — on a
frequently-bottlenecked server the audit trail could swell until it fills the host disk, and
a full host disk can topple MariaDB itself, making the forensic log the *cause* of the very
crisis it exists to watch. So a monitor must never become the source of the crisis it
monitors: bounding the log wins over keeping it forever. This creates a deliberate tension
with the [[kill-audit-record]]'s promise to answer "why was my query killed weeks later" —
aggressive rotation can discard the answer before it is asked. V1 resolves the tension by
*scope*, not by a magic number: the **contract** is that the log is bounded and the disk
ceiling is guaranteed; the **mechanism and the numbers** (size vs. time, how many segments,
how many days) are operator policy, tuned per workload and host-disk size exactly as
detection thresholds are — no universal default is claimed. An operator who sets a short
retention accepts the consequence that the "weeks later" audit window shrinks to match; that
is an honest, explicit trade the operator makes, not a silent loss the system hides.

Writability is not only a *startup* precondition but a **standing precondition for every
destructive action**. If a log write fails *mid-run* — the host volume fills (`ENOSPC`) or
turns read-only at poll 500, long after a clean start — the system must not act blindly.
Specifically, **failure to write the intent line blocks the `KILL`**: the
[[kill-audit-record]]'s rule that "no kill is ever unexplained" makes the audit a
*prerequisite* of the action, not a footnote after it — if the system cannot record *that
it is about to kill a query*, it has no right to kill it. A failed log write therefore
**degrades that poll to alert-only** (the destructive action is withheld; detection's
read-only phase one keeps running and keeps alerting), and the un-writable-log condition is
itself **escalated loudly** as its own crisis — symmetric with [[heal-capability-failure]]:
the system is *forensically blind* and says so. This is the same fail-fast posture the
startup precondition takes, applied to writability *lost at runtime*: when the single source
of truth cannot be written, the system chooses "do not kill without a trace" over "kill
blind", exactly as [[auto-heal]] defaults to alert-only rather than acting on thin evidence.
A real Bottleneck may then go un-healed on a full disk — but the operator is still told, and
the trade ("report, never guess") is honored over the trade of acting unrecorded.

That gate is only meaningful if **"written" means durably on disk, not merely handed to the
OS buffer**. The log is therefore **line-oriented, append-only, one self-contained record
per line** (e.g. JSON Lines), and an [[kill-audit-record|intent line]] counts as written
only after a full `write()` **and an `fsync` to disk both succeed — *before* the `KILL` is
sent**. A buffered write that "succeeds" into the OS page cache and is then lost to an OOM
or power-cut a moment before the kill would re-open exactly the un-recorded-kill hole the
runtime precondition above exists to close — so without the `fsync`, that precondition is
mere theatre. The cost is affordable precisely because a kill is **not** the hot path:
detection's read-only phase one never `fsync`s, and a kill happens only on a real Bottleneck,
at most one per [[poll]] and further spaced by [[heal-cooldown]] — so the flush latency lands
only on the rare, consequential action that deserves to wait for the disk, never on the
steady detection cadence. Append-only with one record per line also makes a **torn write**
(a half-line left behind when `ENOSPC` strikes mid-record) self-evident: a partial or
unparseable line is treated as a failed write when it happens (triggering the same block-and-
escalate path) and is **ignored as noise when the log is later read** — never trusted
half-way. The log is a sequence of whole, fsynced records or it is nothing.

### Kill Audit Record
The permanent, recorded fact of one Auto-Heal execution — the source of truth for
"what the system killed and why". A *successful* kill emits no standalone real-time
alert of its own: the operator already learns that something happened from the
Bottleneck's own entry alert and its Recovery Alert, and this durable record carries
the full detail — so a per-kill notification would only be noise. (A *failed* kill is
the opposite: it escalates loudly as a Heal Capability Failure.) The audit record
exists for long-term accountability: when someone asks weeks later why their query was
terminated, this record must answer it. Every `KILL QUERY` must
produce one, and it must be detailed enough to fully justify the action. Required
contents: timestamp; the killed thread/connection id; the offending account in
`user@host` form; the text of the cancelled query; a summary of the lock-wait chain
that identified it as the Blocker; and the `Threads_running` value at the moment of
the kill. The audit trail is durable and greppable (a rotated log file, never only
the alert channel), so that no kill is ever unexplained.

One kill is recorded as **two write-ahead lines, not one**, sharing a single
**incident id** for correlation. The **intent line is written *before* the `KILL QUERY`
is sent** — it records the decision: the chosen Blocker's full identity, the raw query
text, the lock-wait chain that named it, and the `Threads_running` at the moment of
decision. The **outcome line is written *after* the return code arrives** — it records
the result: the syntactic classification only (succeeded / `Unknown thread id` /
privilege-rejected / transient-timeout), never an *effect* claim, since the
[[poll|poll loop]] alone verifies effect. This ordering is not tidiness but forensic
honesty: a `KILL` that reaches the server while our own process dies *before* the return
arrives is precisely the most dangerous case for an audit — the effect may have landed
on the server with no result line on our side. Writing intent first guarantees no action
is ever unrecorded, and an intent line with its outcome line *missing* is itself a
forensic signal ("we decided and sent, then died mid-flight — inspect the server"). It
is the same "report, never guess" discipline that makes the poll loop, not the return
code, the verifier: the log records what we *did*, never what we *assume happened*.

### Hysteresis
The deliberate gap between the threshold that *enters* a Bottleneck state and the
lower threshold that *exits* it: the system flips into Bottleneck when
`Threads_running` rises above the entry threshold, but only flips back to normal
when it falls below a distinctly lower exit threshold — not the same number. This
gap prevents state flapping: if entry and exit were the same value, a
`Threads_running` hovering right at the line would toggle the Bottleneck state (and
its alerts) on and off rapidly. Both thresholds are operator-configured per server.
The coherence requirement is `exit < entry` strict — a non-zero gap — enforced at the
[Startup Config Contract](#startup-config-contract) boundary; `exit == entry` collapses
the zone to zero width and is refused. The monitor does *not* opine on how wide the gap
should be beyond requiring it to exist: a wider band is calmer but slower to react, a
narrower band is twitchier but more responsive, and that trade-off is the admin's to make
per workload.

### Heal Cooldown
A quiet period after an Auto-Heal execution during which no further `KILL QUERY` is
allowed, even if the Bottleneck persists and a Blocker is still identified. Its
purpose is to let the just-released lock drain and the backed-up queue unwind before
judging whether a *new* genuine Blocker exists — without it, the system could walk
down a legitimate queue killing one waiter after another (a "kill storm"). The
withholding is **blanket and identity-blind**: during cooldown the system suppresses
*every* further kill, even when the lock-wait chain now points to a clearly
*different* Blocker — because a legitimate queue draining one waiter at a time would
otherwise present as a stream of "new Blockers" and be massacred one by one, which is
exactly the storm the cooldown exists to stop. During cooldown the system keeps
polling and still alerts; it simply withholds execution. If the Bottleneck genuinely
persists through the cooldown, that is left for a human operator to inspect — the
system reports, it does not guess.
The cooldown length (M polls) is a *separate* tunable from the Sustained Bottleneck
guard (N polls): N gates the *first* kill, M gates the *gap between* kills, and the
right values differ per server, so they are configured independently. N is **not
re-armed per kill**: once the first kill has fired, the Bottleneck has already proven
itself sustained, so the *only* gate on every subsequent kill is M. When the cooldown
expires with the Bottleneck still over threshold and a Blocker still identified, a
*single* over-threshold poll is enough to authorize the next kill — the system does not
wait another N polls. Re-requiring N would double-count the same "is this real?" guard
and stack the gaps to N+M per kill, needlessly slowing the response to a genuinely
persistent Bottleneck.

M is counted in **wall-clock polls, not successful observations**: a poll that fails
because the monitor has gone blind ([[monitor-blindness]] — connection refused, dropped,
or timing out) still spends one tick of the cooldown. The cooldown does **not** freeze
while blind and resume when sight returns. The reason is that M and K measure orthogonal
things: M is a *delay for the previous kill's effect to drain on the database side*, and
that delay elapses whether or not the monitor can watch it; K is the *continuity of
observation*, a separate counter that raises its own blindness alert. Freezing M during
blindness would conflate the two and could hold off the next kill far longer than the
operator intended — and a blindness event mid-cooldown (e.g. a server restart) usually
means the old lock condition is already gone, so there is even less reason to extend the
hold. When sight returns the cooldown may have partly or wholly elapsed, and the system
simply re-evaluates from the real state at that moment.

This draws the precise line that the **blindness-freeze invariant** actually obeys: the
freeze binds **observational** counters — those that measure an *observed fact* (N counts
over-exit polls *seen*; the [[state-toggle]] booleans and the [[attribution-blindness]]
boolean each record a *condition witnessed*) — and it does **not** bind **temporal**
counters, of which M is the sole example, measuring *wall-clock elapsed since the last
destructive action*. The distinction is exact and not cosmetic: a blind poll observed
nothing, so it may not move anything that represents observation ("report, never guess"
forbids advancing N as a guess that things are still bad, or resetting it as a guess that
they recovered) — but time passes whether or not the monitor is watching, and M tracks
time, not sight. The freeze was never the rule "stop every counter while blind"; it is a
*consequence* of "report, never guess", which only ever constrained counters that stand
for an observation. M, standing for elapsed time, is outside that constraint by
construction. And because a kill is **impossible while blind** anyway — blindness means no
phase-two attribution and so no target to `KILL` — an M that fully elapses mid-blindness
can never trigger a premature kill: nothing fires until sight returns *and* the Bottleneck
is re-validated under fresh observation. Letting M keep running therefore only prevents the
cooldown from being *artificially extended* by an outage unrelated to the cooldown's
purpose.

The cooldown is **not persisted across restarts**: M lives only in process memory, the
same as every [[state-toggle]] boolean ([[state-toggle]] — begin at false every boot).
If the monitor fires a kill, enters cooldown, and then the process restarts mid-cooldown
(a crash under `Restart=always`, or an operator restart to flip [[auto-heal]]), the fresh
process starts with **no active cooldown** — it has no memory that any kill was ever sent,
so there is no M to resume. This is the deliberate, consistent extension of "begin clean
every boot": no in-memory state is written to disk and reloaded, and M is no exception.
The accepted risk — that a kill sent by the old process may still be rolling back on the
database side while the new process is already free to kill again — is covered not by a
persisted cooldown but by the [[sustained-bottleneck]] guard itself: per [[state-toggle]],
the fresh process can issue *no* kill until it has watched a false→true up-edge and
accumulated N over-threshold polls *under its own observation*, starting from zero. That
fresh N accumulation is itself a natural delay — at least N polls of breathing room before
any kill — during which the old kill's rollback drains. So losing M across restart opens no
kill-storm: N stands in for it, and re-deriving the real state from scratch is cheaper than
a disk-backed counter carrying the same staleness question already rejected for State Toggle.

The cooldown begins **only on a `KILL QUERY` that was accepted syntactically** — i.e. an
action that could plausibly have had an effect to drain. A kill that fails *syntactically*
does **not** start the cooldown, because M exists purely to let a kill's *effect* settle,
and a syntactically-rejected kill released nothing. Two cases fall here: the target thread
vanished on its own between attribution and execution (`Unknown thread id` — it finished and
released its own lock without the monitor's help), and the chosen root turned out to be a
[[kill-exclusion]] account so no `KILL` was ever sent at all. In both, the monitor took no
effective action, so there is nothing to drain and no reason to arm the rem — pinning a
fresh M here would needlessly withhold the *next*, legitimate kill against a possibly-real
and different Blocker for M polls with zero drain benefit. This is the same
syntax-vs-effect distinction already load-bearing for the heal path: a syntactically-accepted
kill means "an action with potential effect occurred → open the drain window"; a
syntactically-rejected or never-sent kill means "no action occurred → do not pin the brake".
The return code is still trusted *only* for this syntactic classification, never as proof the
target actually died — the poll loop remains the verifier of effect.

M is **purely temporal — M polls since the last kill — and is deliberately *not* tied to the
Bottleneck episode's lifecycle.** This is an intentional **asymmetry with N**: N resets at the
exit threshold because it measures *how long the condition has proven real*, so it must die
exactly when the condition does ([[sustained-bottleneck]]); M measures *how long the previous
kill's physical effect needs to drain on the database side* — a rollback unwinding, a queue
clearing — and that drain runs in real server time, blind to whether `Threads_running` happened
to dip below exit and climb back. So a recovery *mid-cooldown* does **not** reset or cancel M.
Concretely: kill at poll 100 (M=10), full recovery at poll 102 (state toggles to Normal,
[[recovery-alert]] fires, 2 ticks elapsed), then a *new* Bottleneck episode crosses entry at
poll 106 — the remaining cooldown still applies, because a large transaction killed at poll 100
may *still* be rolling back at poll 106 despite the brief dip between. Resetting M at recovery
would let a fresh kill stack on top of the old kill's not-yet-settled effect — exactly the
kill-storm the cooldown exists to prevent. This asymmetry is not an inconsistency: N and M
measure two different things (condition-maturity vs. physical-effect-drain), so they correctly
key off two different clocks. And it opens no gap, because the new episode must still
accumulate N from zero (N *does* reset at exit), and that fresh N is itself a delay — the
leftover M has very likely expired before N matures.

### Attributed Bottleneck
A Bottleneck for which a Blocker *was* identified — there is a clear lock-wait chain
pointing to a single thread holding the lock. Only an Attributed Bottleneck is
eligible for Auto-Heal, because only here is there a specific thread to `KILL`.

### Unattributed Bottleneck
A Bottleneck where `Threads_running` is over threshold but no Blocker can be found
because the lock-wait chain query *succeeded and came back empty* — the system has
genuinely looked and there is no lock-holder. This is strictly the empty-but-successful
case; if the chain query instead *errored* and gave no answer, that is
[[attribution-blindness]], a separate class, not an Unattributed Bottleneck. Typically
caused by general load (mass full-table scans, CPU/disk saturation, connection
thundering herd) rather than one stuck query.
The system NEVER guesses a victim here (e.g. it will not kill the longest-running
query) — that would violate the principle that killing is driven by lock-holding,
not duration. An Unattributed Bottleneck is alert-only and always requires human
judgement, regardless of whether Auto-Heal is ON.

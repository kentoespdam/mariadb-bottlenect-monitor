# MariaDB Bottleneck Monitor

Auto-heal monitor for MariaDB — detects lock contention via `Threads_running` hysteresis, attributes blocker through `innodb_lock_waits`, issues `KILL QUERY` when sustained bottleneck confirmed.

Connects through MariaDB `extra_port` (3307) — stays connected when `max_connections` fills up.

## Required MariaDB User Privileges

Monitor needs these grants:

| Privilege | Used for |
|-----------|----------|
| `PROCESS` | Read `information_schema` lock-wait views, `PROCESSLIST`, `SHOW GLOBAL STATUS` |
| `SUPER` | `KILL QUERY` on blocker threads (or `CONNECTION ADMIN` on MariaDB ≥10.11) |

Without `PROCESS`, monitor starts but phase-two attribution fails. Without `SUPER`/`CONNECTION ADMIN`, auto-heal fails. Start-up privilege check logs a warning but does not block startup — so operator can deploy monitor in alert-only mode first.

### Create User Example

```sql
CREATE USER IF NOT EXISTS 'monitor'@'%' IDENTIFIED BY 'your_strong_password';
GRANT PROCESS ON *.* TO 'monitor'@'%';
GRANT SUPER ON *.* TO 'monitor'@'%';
FLUSH PRIVILEGES;
```

For MariaDB ≥10.11, `SUPER` can be replaced with the finer-grained `CONNECTION ADMIN`:

```sql
GRANT CONNECTION ADMIN ON *.* TO 'monitor'@'%';
```

Monitor uses `extra_port` (default 3307) — ensure `extra_port` is configured in `/etc/mysql/mariadb.cnf`:

```ini
[mariadb]
extra_port = 3307
extra_max_connections = 30
```

`extra_port` bypasses `max_connections` limit so monitor stays connected under load.

## Architecture

```
main.py          → Entry point, config loading, component wiring
scheduler.py     → Fixed-delay poll loop (never overlaps, never catches up)
poll.py          → Phase one (Threads_running), phase two (lock-wait chain)
counters.py      → N (sustained), K (blindness), J (attribution blindness), M (cooldown)
auto_heal.py     → Blocker identity resolution, KILL QUERY with safety checks
state.py         → Edge-triggered state toggle (fires callback only on transitions)
db.py            → Single persistent MariaDB connection via pymysql
telegram_alert.py   → Best-effort Telegram alert with per-type rate limiting (60s)
durable_log.py   → JSON Lines audit log (fsync on kill records)
config.py        → Three-tier startup validation (ADR-0001)
_env.py          → Environment variable helpers
```

## Two-Phase Poll

Each poll runs in fixed-delay (~1s gap between polls):

1. **Phase one (every poll)** — `SHOW GLOBAL STATUS LIKE 'Threads_running'`
2. **Phase two (only when over entry threshold)** — Lock-wait chain via `information_schema.innodb_lock_waits` + `innodb_trx`

Phase two is lazy — never runs on a healthy server. Under load, phase-two slowdown applies natural backpressure (wider poll gap is correct, not a bug).

## Hysteresis

Two thresholds prevent state flapping:
- **Entry**: crossing above → Bottleneck state ON
- **Exit**: crossing at/below → Bottleneck state OFF

Gap zone (between exit and entry) holds current state — no toggling.

## Counters (polls, not seconds)

| Counter | What it tracks | Type | Default |
|---------|---------------|------|---------|
| N | Sustained bottleneck (over exit) | Freezes during blindness | 5 |
| K | Monitor blindness (failed polls) | Always advances | 3 |
| J | Attribution blindness (failed phase two) | Freezes during blindness | 5 |
| M | Heal cooldown (polls since last kill) | Always ticks, even when blind | 10 |

K < N = J < M ordering: total blindness alerts fastest, kill waits for certainty, cooldown longest.

## Auto-Heal

Default OFF (alert-only). When ON: one `KILL QUERY` per poll, selected by deepest root → most waiters → oldest transaction.

Safety checks before every kill:
- Thread still exists with same identity
- N age threshold satisfied
- Not in kill-exclusion allowlist (`user@host`, `%` host wildcard)
- Not monitor's own connection
- Privilege verified at startup

M cooldown fires only on syntactically-accepted kill. If M active → no kill that poll.

## Kill Exclusion (Allowlist)

`KILL_EXCLUSION=user1@host1,user2@%` — never kill these accounts. Monitor's own user excluded by default. Falls through to next eligible root when excluded root is deepest.

## Telegram Alerts

Best-effort, 60s per-type rate limit, bounded timeout (configurable, default 5s). Never blocks poll loop. Failure logged to durable log.

Alert payload: `Threads_running`, blocker identity (user@host, no query text — PII boundary), action taken. Full details only in durable log.

## Durable Log

JSON Lines, host-volume backed (survives container restart). Startup precondition — monitor refuses to start if path not writable. `fsync` on kill-intent lines before KILL QUERY sent. Two-line audit: intent (before) + outcome (after), correlated by incident ID.

## Startup Config Contract (ADR-0001)

Three tiers:
1. **Patience knobs (N, M, K, J) absent** → documented defaults
2. **Detection thresholds absent** (THREADS_ENTRY, THREADS_EXIT) → refuse to start
3. **Malformed/incoherent values** → refuse to start with clear message

Validation order: config → durable log writable → database connection.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `THREADS_ENTRY` | **required** | Bottleneck entry threshold |
| `THREADS_EXIT` | **required** | Bottleneck exit threshold (must be < entry) |
| `N` | 5 | Sustained bottleneck guard (floor: 1) |
| `M` | 10 | Heal cooldown polls (floor: 1) |
| `K` | 3 | Monitor blindness alerts (floor: 0) |
| `J` | 5 | Attribution blindness alerts (floor: 0) |
| `DB_HOST` | 127.0.0.1 | MariaDB host |
| `DB_PORT` | 3307 | MariaDB extra_port |
| `DB_USER` | monitor | Monitor user |
| `DB_PASSWORD` | (empty) | Monitor password |
| `POLL_INTERVAL_SEC` | 1.0 | Gap between polls |
| `AUTO_HEAL` | false | Enable KILL QUERY execution |
| `KILL_EXCLUSION` | (empty) | Comma-separated `user@host` allowlist |
| `TELEGRAM_BOT_TOKEN` | (empty) | Telegram Bot API token |
| `TELEGRAM_CHAT_ID` | (empty) | Target chat ID |
| `DURABLE_LOG_PATH` | /var/log/monitor/monitor.jsonl | Audit log path |
| `MONITOR_USER` | monitor | Monitor's own MariaDB user |
| `MONITOR_HOST` | 127.0.0.1 | Monitor's own MariaDB host |

## Development

```bash
uv run python -m pytest    # 95 tests
uv run ruff check          # Lint
uv run ruff format --check # Format
```

All files ≤ 120 lines per CODE_RULES.md. Python 3.13+, pymysql + httpx dependencies.

## License

MIT

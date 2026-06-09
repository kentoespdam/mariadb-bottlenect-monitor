"""Poll scheduler — fixed-delay loop, never returns under normal operation."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .config import Config
from .counters import KCounter, NCounter
from .db import DatabaseConnection, DatabaseError
from .durable_log import DurableLog
from .poll import PollResult, run_poll
from .state import StateToggle

log = logging.getLogger(__name__)


def schedule_polls(
    cfg: Config,
    db: DatabaseConnection,
    n_counter: NCounter,
    k_counter: KCounter,
    bottleneck_state: StateToggle,
    durable: DurableLog,
    on_result: Callable[[PollResult], None] | None = None,
) -> None:
    """Fixed-delay poll scheduler loop with auto-reconnect. Never returns under normal operation."""
    log.info("Poll scheduler started (interval=%.1fs)", cfg.poll_interval_sec)
    max_reconnects = 10
    reconnect_count = 0

    while True:
        t0 = time.monotonic()
        try:
            result = run_poll(db, cfg, n_counter, k_counter, bottleneck_state)
            reconnect_count = 0  # Reset on success
            if on_result:
                on_result(result)
            
            # Log poll result
            durable.append({
                "event": "poll_result",
                "threads_running": result.threads_running,
                "n_counter": n_counter.value,
                "k_counter": k_counter.value,
                "bottleneck_state": bottleneck_state.value,
                "blockers": result.blockers if hasattr(result, "blockers") else None
            })
        except DatabaseError as exc:
            log.error("DB error in poll cycle: %s", exc)
            result = PollResult(threads_running=None, error=f"db: {exc}")
            durable.append({
                "event": "db_error",
                "error": str(exc),
                "reconnect_count": reconnect_count
            })
            if reconnect_count < max_reconnects:
                reconnect_count += 1
                log.info("Attempting reconnect (%d/%d)...", reconnect_count, max_reconnects)
                durable.append({
                    "event": "reconnect_attempt",
                    "attempt": reconnect_count,
                    "max_attempts": max_reconnects
                })
                if db.reconnect():
                    log.info("Reconnected successfully")
                    durable.append({
                        "event": "reconnect_success",
                        "attempt": reconnect_count
                    })
                else:
                    log.error("Reconnect failed — will retry next cycle")
                    durable.append({
                        "event": "reconnect_failed",
                        "attempt": reconnect_count
                    })
            else:
                log.error("Max reconnects (%d) reached — monitor may be blind", max_reconnects)
                durable.append({
                    "event": "max_reconnects_reached",
                    "max_reconnects": max_reconnects
                })
        except Exception as exc:
            log.exception("Unhandled error in poll cycle")
            result = PollResult(threads_running=None, error="poll crash")
            durable.append({
                "event": "unhandled_error",
                "error": str(exc)
            })

        elapsed = time.monotonic() - t0
        sleep_time = cfg.poll_interval_sec - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

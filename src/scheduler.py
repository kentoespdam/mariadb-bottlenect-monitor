"""Poll scheduler — fixed-delay loop, never returns under normal operation."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .config import Config
from .counters import KCounter, NCounter
from .db import DatabaseConnection, DatabaseError
from .poll import PollResult, run_poll
from .state import StateToggle

log = logging.getLogger(__name__)


def schedule_polls(
    cfg: Config,
    db: DatabaseConnection,
    n_counter: NCounter,
    k_counter: KCounter,
    bottleneck_state: StateToggle,
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
        except DatabaseError as exc:
            log.error("DB error in poll cycle: %s", exc)
            result = PollResult(threads_running=None, error=f"db: {exc}")
            if reconnect_count < max_reconnects:
                reconnect_count += 1
                log.info("Attempting reconnect (%d/%d)...", reconnect_count, max_reconnects)
                if db.reconnect():
                    log.info("Reconnected successfully")
                else:
                    log.error("Reconnect failed — will retry next cycle")
            else:
                log.error("Max reconnects (%d) reached — monitor may be blind", max_reconnects)
        except Exception:
            log.exception("Unhandled error in poll cycle")
            result = PollResult(threads_running=None, error="poll crash")

        elapsed = time.monotonic() - t0
        sleep_time = cfg.poll_interval_sec - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

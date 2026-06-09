"""Poll engine — phase one detection, phase two attribution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .config import Config
from .counters import KCounter, NCounter, evaluate_hysteresis
from .db import DatabaseConnection
from .state import StateToggle

log = logging.getLogger(__name__)


@dataclass
class PollResult:
    """Result of one complete poll cycle."""

    threads_running: int | None
    blocker: dict[str, Any] | None = None
    phase_one_ok: bool = False
    phase_two_ok: bool | None = None
    error: str | None = None


def phase_one(db: DatabaseConnection) -> int | None:
    try:
        row = db.query_one("SHOW GLOBAL STATUS LIKE 'Threads_running'")
        if row is None:
            log.error("SHOW GLOBAL STATUS returned no row for Threads_running")
            return None
        return int(row[1])
    except Exception as exc:
        log.error("Phase one failed: %s", exc)
        return None


def phase_two(db: DatabaseConnection) -> dict[str, Any] | None:
    try:
        rows = db.query("""
            SELECT
                r.trx_mysql_thread_id AS thread_id,
                p.USER AS user,
                p.HOST AS host,
                r.trx_started,
                r.trx_query AS query_text,
                COUNT(w.requesting_trx_id) AS waiter_count
            FROM information_schema.innodb_lock_waits w
            JOIN information_schema.innodb_trx r
                ON w.blocking_trx_id = r.trx_id
            LEFT JOIN information_schema.processlist p
                ON r.trx_mysql_thread_id = p.ID
            GROUP BY r.trx_mysql_thread_id, p.USER, p.HOST, r.trx_started, r.trx_query
            ORDER BY waiter_count DESC, r.trx_started ASC
            LIMIT 1
        """)
        if not rows:
            return None
        row = rows[0]
        return {
            "thread_id": int(row[0]),
            "user": str(row[1] or ""),
            "host": str(row[2] or ""),
            "trx_started": str(row[3] or ""),
            "query_text": str(row[4] or ""),
            "waiter_count": int(row[5]),
        }
    except Exception as exc:
        log.error("Phase two (attribution) failed: %s", exc)
        return None


def run_poll(
    db: DatabaseConnection,
    cfg: Config,
    n_counter: NCounter,
    k_counter: KCounter,
    bottleneck_state: StateToggle,
) -> PollResult:
    tr = phase_one(db)
    if tr is None:
        k_counter.increment()
        n_counter.freeze()
        bottleneck_state.freeze()
        return PollResult(threads_running=None, phase_one_ok=False)

    k_counter.reset()
    n_counter.unfreeze()
    bottleneck_state.unfreeze()

    hyst = evaluate_hysteresis(tr, cfg.threads_entry, cfg.threads_exit)

    if hyst is True:
        n_counter.increment()
        bottleneck_state.set(True)
    elif hyst is False:
        n_counter.reset()
        bottleneck_state.set(False)

    result = PollResult(threads_running=tr, phase_one_ok=True)

    if hyst is True:
        blocker = phase_two(db)
        if blocker is not None:
            result.blocker = blocker
            result.phase_two_ok = True
        else:
            result.phase_two_ok = False

    return result

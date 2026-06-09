"""Poll engine — phase one detection, phase two attribution."""

from __future__ import annotations

import logging
import re
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


def _parse_lock_waits_from_status(status_text: str) -> dict[str, Any] | None:
    """Parse SHOW ENGINE INNODB STATUS for lock wait information.

    Looks for '--- LOCK WAIT ---' sections, extracts the WAITING thread info
    and identifies the blocker via trx_id references.
    """
    # Find all LOCK WAIT sections
    lock_wait_pattern = re.compile(
        r'---\s*LOCK\s*WAIT\s*---\s*\n'
        r'(.*?)(?=---\s*LOCK\s*WAIT\s*---|---\s*TRANSACTIONS\s*---|\Z)',
        re.DOTALL
    )

    matches = list(lock_wait_pattern.finditer(status_text))
    if not matches:
        return None

    # Parse the first lock wait section
    section = matches[0].group(1)

    # Extract waiting thread info
    thread_match = re.search(r'MariaDB thread id (\d+)', section)
    query_match = re.search(r'query id \d+\s+\S+\s+(\S+)\s+(\S+)', section)

    if not thread_match:
        return None

    thread_id = int(thread_match.group(1))
    user = query_match.group(1) if query_match else "unknown"
    host = query_match.group(2) if query_match else "unknown"

    # Count total lock waits
    waiter_count = len(matches)

    return {
        "thread_id": thread_id,
        "user": user,
        "host": host,
        "trx_started": "",  # Not available from INNODB STATUS
        "query_text": "",  # Not available from INNODB STATUS
        "waiter_count": waiter_count,
    }


def phase_two(db: DatabaseConnection) -> dict[str, Any] | None:
    """Detect lock-blocking transaction.

    MariaDB 11.x: ``INNODB_LOCK_WAITS`` is often empty.  Fallback to parsing
    ``SHOW ENGINE INNODB STATUS`` for ``--- LOCK WAIT ---`` sections.
    """
    # --- attempt 1: standard INNODB_LOCK_WAITS query ---
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
        if rows:
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
        log.warning("Phase two INNODB_LOCK_WAITS query failed: %s", exc)

    # --- attempt 2: parse SHOW ENGINE INNODB STATUS ---
    try:
        rows = db.query("SHOW ENGINE INNODB STATUS")
        if not rows:
            return None
        # Status is the third column (index 2)
        status_text = str(rows[0][2]) if rows and len(rows[0]) > 2 else ""
        return _parse_lock_waits_from_status(status_text)
    except Exception as exc:
        log.error("Phase two (INNODB STATUS parse) failed: %s", exc)
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

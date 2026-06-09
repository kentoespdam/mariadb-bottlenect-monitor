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

    MariaDB 11.x: INNODB_LOCK_WAITS is often empty. Fallback to parsing
    SHOW ENGINE INNODB STATUS. Lock waits appear in LATEST DETECTED DEADLOCK
    or in the TRANSACTIONS section as 'LOCK WAIT' inline keyword.

    Each LOCK WAIT block format:
        TRANSACTION 123, ACTIVE 1 sec ...
        LOCK WAIT 5 lock struct(s)...
        MariaDB thread id 10426, OS thread handle ..., query id ... host user Updating
        UPDATE sbtest1 SET ... WHERE id=...
        *** WAITING FOR THIS LOCK TO BE GRANTED: ...
        *** CONFLICTING WITH:
        RECORD LOCKS ... trx id 456 ...

    The BLOCKER is identified by the CONFLICTING trx_id. We return the
    BLOCKER's thread_id (the one to KILL), not the waiter.
    """
    # Find all LOCK WAIT blocks (anywhere in status text)
    lock_wait_pattern = re.compile(
        r'(?:^|\n)LOCK WAIT \d+ lock struct.*?\n'
        r'MariaDB thread id (\d+),.*?query id \d+\s+(\S+)\s+(\S+)\s+\S+\n'
        r'(.+?)(?=\n\*\*\* WAITING|\nTRANSACTION |\n---|\Z)',
        re.DOTALL
    )

    matches = list(lock_wait_pattern.finditer(status_text))
    if not matches:
        return None

    # Find the BLOCKER: look for CONFLICTING WITH sections
    conflicting_pattern = re.compile(
        r'\*\*\* CONFLICTING WITH:\s*\n'
        r'RECORD LOCKS.*?trx id (\d+)',
        re.DOTALL
    )
    conflicts = list(conflicting_pattern.finditer(status_text))

    # Extract waiter info from first match
    # Format: "query id <num> <host> <user> <state>"
    first = matches[0]
    waiter_thread = int(first.group(1))
    waiter_host = first.group(2)
    waiter_user = first.group(3)
    waiter_query = first.group(4).strip()

    # Try to find the blocker by CONFLICTING trx_id
    blocker_thread = None
    blocker_user = waiter_user  # fallback
    blocker_host = waiter_host
    if conflicts:
        blocker_trx_id = int(conflicts[0].group(1))
        # Find this trx_id in the full status to get thread info
        trx_pattern = re.compile(
            rf'TRANSACTION {blocker_trx_id},.*?\n'
            r'(?:.*?\n)*?'
            r'MariaDB thread id (\d+),.*?query id \d+\s+(\S+)\s+(\S+)\s+\S+\n'
            r'(.+?)(?=\n\*\*\*|\nTRANSACTION |\Z)',
            re.DOTALL
        )
        trx_match = trx_pattern.search(status_text)
        if trx_match:
            blocker_thread = int(trx_match.group(1))
            blocker_host = trx_match.group(2)
            blocker_user = trx_match.group(3)

    waiter_count = len(matches)

    # Return blocker info (the one to kill), falling back to waiter info
    target_thread = blocker_thread or waiter_thread
    target_user = blocker_user
    target_host = blocker_host

    log.info(
        "INNODB STATUS: %d lock wait(s), waiter thread=%d, blocker thread=%s",
        waiter_count, waiter_thread, blocker_thread,
    )

    return {
        "thread_id": target_thread,
        "user": target_user,
        "host": target_host,
        "trx_started": "",
        "query_text": waiter_query,
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

    # --- attempt 2: query INNODB_TRX directly for blocker ---
    try:
        rows = db.query("""
            SELECT
                t.trx_mysql_thread_id AS thread_id,
                p.USER AS user,
                p.HOST AS host,
                t.trx_started,
                t.trx_query AS query_text,
                t.trx_rows_locked,
                (SELECT COUNT(*) FROM information_schema.INNODB_TRX wt
                 WHERE wt.trx_wait_started IS NOT NULL) AS waiter_count
            FROM information_schema.INNODB_TRX t
            LEFT JOIN information_schema.PROCESSLIST p
                ON t.trx_mysql_thread_id = p.ID
            WHERE t.trx_rows_locked > 0
            ORDER BY t.trx_started ASC
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
                "waiter_count": int(row[6]),
            }
    except Exception as exc:
        log.warning("Phase two INNODB_TRX query failed: %s", exc)

    # --- attempt 3: parse SHOW ENGINE INNODB STATUS ---
    try:
        rows = db.query("SHOW ENGINE INNODB STATUS")
        if not rows:
            return None
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

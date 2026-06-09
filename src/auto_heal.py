"""Auto-Heal — KILL QUERY execution against blocker SPID."""

from __future__ import annotations

import logging
import re
from typing import Any

from .config import Config
from .db import DatabaseConnection

log = logging.getLogger(__name__)

_HOST_CLEAN_RE = re.compile(r":\d+$")


def _normalise_host(raw: str) -> str:
    """Strip ephemeral port from PROCESSLIST HOST (host:port -> host)."""
    return _HOST_CLEAN_RE.sub("", raw)


def _matches_exclusion(user: str, host: str, exclusion: tuple[str, ...]) -> bool:
    """Check if user@host matches any exclusion pattern."""
    for entry in exclusion:
        if "@" not in entry:
            continue
        e_user, e_host = entry.split("@", 1)
        if e_user == user and (e_host == host or e_host == "%"):
            return True
    return False


def _check_privilege(db: DatabaseConnection) -> bool:
    """Check monitor user has SUPER (or equivalent) for KILL privilege."""
    try:
        row = db.query_one("SELECT CURRENT_USER()")
        if not row:
            return False
        grants = db.query("SHOW GRANTS")
        for row in grants:
            line = str(row[0] or "").upper()
            if "SUPER" in line or "ALL PRIVILEGES" in line:
                return True
    except Exception:
        log.exception("Privilege check failed")
        return False
    return False


def resolve_blocker_identity(db: DatabaseConnection, thread_id: int) -> dict[str, Any] | None:
    """Resolve blocker user/host/db from SHOW PROCESSLIST."""
    try:
        rows = db.query("SELECT ID, USER, HOST, DB FROM information_schema.PROCESSLIST WHERE ID = %s", (thread_id,))
        if not rows:
            return None
        row = rows[0]
        return {
            "thread_id": int(row[0]),
            "user": str(row[1] or ""),
            "host": _normalise_host(str(row[2] or "")),
            "db": str(row[3] or ""),
        }
    except Exception:
        log.exception("Identity resolution failed for thread %d", thread_id)
        return None


def kill_blocker(
    db: DatabaseConnection,
    identity: dict[str, Any],
    blocker: dict[str, Any],
    cfg: Config,
    poll_state: dict[str, Any],
) -> tuple[bool, str]:
    """Execute KILL QUERY with safety checks.

    Returns (success, outcome_msg).
    """
    # Check age >= threshold (N polls elapsed since phase two)
    if poll_state.get("n_elapsed", 0) < poll_state.get("age_threshold", 0):
        return False, "age_below_threshold"

    # Check allowlist using identity from phase_two
    if _matches_exclusion(identity["user"], identity["host"], cfg.kill_exclusion):
        return False, "excluded"

    # Check monitor identity
    if identity["user"] == cfg.monitor_user and identity["host"] == cfg.monitor_host:
        return False, "is_monitor_self"

    try:
        db.query("KILL QUERY %s", (identity["thread_id"],))
        log.info("KILL QUERY sent to thread %d (%s@%s)", identity["thread_id"], identity["user"], identity["host"])
        return True, "kill_sent"
    except Exception as exc:
        log.error("KILL QUERY failed for thread %d: %s", identity["thread_id"], exc)
        return False, f"kill_failed: {exc}"

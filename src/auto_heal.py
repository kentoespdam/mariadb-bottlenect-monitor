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
    """Resolve blocker identity + liveness from a fresh PROCESSLIST snapshot.

    COMMAND and INFO are read here (not reused from phase-two) so the kill-mode
    decision keys off the thread's state at kill time, not a stale attribution.
    """
    try:
        rows = db.query(
            "SELECT ID, USER, HOST, DB, COMMAND, INFO "
            "FROM information_schema.PROCESSLIST WHERE ID = %s",
            (thread_id,),
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "thread_id": int(row[0]),
            "user": str(row[1] or ""),
            "host": _normalise_host(str(row[2] or "")),
            "db": str(row[3] or ""),
            "command": str(row[4] or ""),
            "info": str(row[5] or ""),
        }
    except Exception:
        log.exception("Identity resolution failed for thread %d", thread_id)
        return None


def _is_idle(identity: dict[str, Any]) -> bool:
    """Idle-in-transaction: holds locks with no active statement.

    Two-signal test (COMMAND='Sleep' AND empty INFO) so KILL QUERY — which only
    cancels a running statement — is escalated to KILL. See docs/adr/0002.
    """
    return identity["command"] == "Sleep" and not identity["info"]


def kill_blocker(
    db: DatabaseConnection,
    blocker: dict[str, Any],
    cfg: Config,
) -> tuple[bool, str]:
    """Resolve a fresh identity then kill the blocker with safety checks.

    Returns (success, outcome). Idle-in-trx blockers escalate from KILL QUERY to
    KILL (connection); active blockers keep KILL QUERY (see docs/adr/0002).
    """
    identity = resolve_blocker_identity(db, blocker["thread_id"])
    # Unresolvable identity is fail-safe excluded: never kill what we cannot vet.
    if identity is None:
        return False, "excluded_unresolved"

    if _matches_exclusion(identity["user"], identity["host"], cfg.kill_exclusion):
        return False, "excluded"

    if identity["user"] == cfg.monitor_user and identity["host"] == cfg.monitor_host:
        return False, "is_monitor_self"

    tid = identity["thread_id"]
    sql, outcome = ("KILL %s", "killed_connection") if _is_idle(identity) else ("KILL QUERY %s", "killed_query")
    try:
        db.query(sql, (tid,))
        log.info("%s -> thread %d (%s@%s)", outcome, tid, identity["user"], identity["host"])
        return True, outcome
    except Exception as exc:
        log.error("kill failed for thread %d: %s", tid, exc)
        return False, f"kill_failed: {exc}"

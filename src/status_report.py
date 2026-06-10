"""Periodic status report — fetch MariaDB health metrics and format."""

from __future__ import annotations

from .db import DatabaseConnection

_VARS = (
    "Threads_running", "Threads_connected", "Uptime",
    "Questions", "Slow_queries",
    "Innodb_buffer_pool_read_requests", "Innodb_buffer_pool_reads",
)


def fetch_status(db: DatabaseConnection) -> dict[str, int]:
    """Query MariaDB GLOBAL STATUS for health metrics."""
    data: dict[str, int] = {}
    for var in _VARS:
        row = db.query_one(f"SHOW GLOBAL STATUS LIKE '{var}'")
        if row is not None:
            data[var] = int(row[1])
    return data


def _fmt_uptime(seconds: int) -> str:
    """Format seconds as 'Xd Xh Xm'."""
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts: list[str] = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)


def format_status_report(data: dict[str, int]) -> str:
    """Format status dict into plain-text Telegram report."""
    uptime = data.get("Uptime", 0)
    running = data.get("Threads_running", 0)
    connected = data.get("Threads_connected", 0)
    questions = data.get("Questions", 0)
    slow = data.get("Slow_queries", 0)
    bp_req = data.get("Innodb_buffer_pool_read_requests", 0)
    bp_reads = data.get("Innodb_buffer_pool_reads", 0)

    qps = questions / uptime if uptime > 0 else 0.0
    bp_hit = (1 - bp_reads / bp_req) * 100 if bp_req > 0 else 100.0

    lines = [
        "STATUS LAPORAN",
        "",
        f"Uptime: {_fmt_uptime(uptime)}",
        f"Threads: {running} running / {connected} connected",
        f"Questions: {questions:,} (QPS: ~{qps:.1f})",
        f"Slow queries: {slow}",
        f"Buffer pool: {bp_hit:.1f}% hit rate",
    ]
    return "\n".join(lines)

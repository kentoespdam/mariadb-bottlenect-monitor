"""Telegram bot command handlers — pure functions, no I/O."""

from __future__ import annotations

from .config import Config
from .db import DatabaseConnection
from .status_report import fetch_status, format_status_report


def cmd_status(db: DatabaseConnection) -> str:
    data = fetch_status(db)
    return format_status_report(data)


def cmd_threads(db: DatabaseConnection) -> str:
    rows = db.query("SHOW GLOBAL STATUS LIKE 'Threads_%%'")
    lines = ["THREAD STATUS", ""]
    for row in rows:
        lines.append(f"{row[0]}: {row[1]}")
    return "\n".join(lines)


def cmd_processlist(db: DatabaseConnection) -> str:
    sql = (
        "SELECT ID, USER, HOST, DB, TIME, INFO "
        "FROM information_schema.PROCESSLIST "
        "WHERE COMMAND != 'Sleep' "
        "AND USER != 'monitor_test' "
        "ORDER BY TIME DESC LIMIT 10"
    )
    rows = db.query(sql)
    if not rows:
        return "No active queries"
    lines = ["ACTIVE QUERIES (top 10)", ""]
    for r in rows:
        q = (r[5] or "")[:80]
        lines.append(f"ID:{r[0]} {r[1]}@{r[2]} db={r[3] or '-'} {r[4]}s")
        if q:
            lines.append(f"  {q}")
    return "\n".join(lines)


def cmd_config(cfg: Config) -> str:
    return (
        "MONITOR CONFIG\n"
        "\n"
        f"entry={cfg.threads_entry} exit={cfg.threads_exit}\n"
        f"N={cfg.N} M={cfg.M} K={cfg.K} J={cfg.J}\n"
        f"auto_heal={cfg.auto_heal}\n"
        f"poll_interval={cfg.poll_interval_sec}s\n"
        f"kill_exclusion={','.join(cfg.kill_exclusion) or 'none'}"
    )


def cmd_help() -> str:
    return (
        "AVAILABLE COMMANDS\n\n"
        "/status - Server health report\n"
        "/threads - Thread status counters\n"
        "/processlist - Active queries (top 10)\n"
        "/config - Monitor configuration\n"
        "/help - This message"
    )

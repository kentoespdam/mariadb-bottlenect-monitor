"""Telegram bot — polls getUpdates and dispatches /commands."""

from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from .config import Config
from .db import DatabaseConnection
from .status_report import fetch_status, format_status_report
from .telegram_alert import _API_BASE

log = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, cfg: Config, db: DatabaseConnection) -> None:
        self._token = cfg.telegram_bot_token
        self._cfg = cfg
        self._db = db
        self._poll_interval = cfg.bot_poll_interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Telegram bot started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        offset = 0
        url_base = f"{_API_BASE}{self._token}"
        while not self._stop.is_set():
            try:
                offset = self._poll_once(url_base, offset)
            except Exception:
                log.debug("Bot poll error", exc_info=True)
            self._stop.wait(self._poll_interval)

    def _poll_once(self, url_base: str, offset: int) -> int:
        params: dict[str, Any] = {"timeout": 5}
        if offset:
            params["offset"] = offset
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{url_base}/getUpdates", params=params)
            resp.raise_for_status()
            data = resp.json()
        new_offset = offset
        for upd in data.get("result", []):
            new_offset = max(new_offset, upd["update_id"] + 1)
            msg = upd.get("message", {})
            text = msg.get("text", "")
            chat_id = msg.get("chat", {}).get("id")
            if text.startswith("/") and chat_id:
                self._dispatch(text.split()[0].lower(), str(chat_id))
        return new_offset

    def _dispatch(self, command: str, chat_id: str) -> None:
        handlers = {
            "/status": self._cmd_status,
            "/threads": self._cmd_threads,
            "/processlist": self._cmd_processlist,
            "/config": self._cmd_config,
            "/help": self._cmd_help,
        }
        handler = handlers.get(command)
        if handler:
            try:
                handler(chat_id)
            except Exception:
                log.debug("Command %s failed", command, exc_info=True)
                self._send_reply(chat_id, "Error processing command")

    def _cmd_status(self, chat_id: str) -> None:
        data = fetch_status(self._db)
        self._send_reply(chat_id, format_status_report(data))

    def _cmd_threads(self, chat_id: str) -> None:
        rows = self._db.query("SHOW GLOBAL STATUS LIKE 'Threads_%'")
        lines = ["THREAD STATUS", ""]
        for row in rows:
            lines.append(f"{row[0]}: {row[1]}")
        self._send_reply(chat_id, "\n".join(lines))

    def _cmd_processlist(self, chat_id: str) -> None:
        sql = ("SELECT ID, USER, HOST, DB, TIME, INFO "
               "FROM information_schema.PROCESSLIST "
               "WHERE COMMAND != 'Sleep' ORDER BY TIME DESC LIMIT 10")
        rows = self._db.query(sql)
        if not rows:
            self._send_reply(chat_id, "No active queries")
            return
        lines = ["ACTIVE QUERIES (top 10)", ""]
        for r in rows:
            q = (r[5] or "")[:80]
            lines.append(f"ID:{r[0]} {r[1]}@{r[2]} db={r[3]} {r[4]}s")
            if q:
                lines.append(f"  {q}")
        self._send_reply(chat_id, "\n".join(lines))

    def _cmd_config(self, chat_id: str) -> None:
        c = self._cfg
        text = (
            "MONITOR CONFIG\n"
            "\n"
            f"entry={c.threads_entry} exit={c.threads_exit}\n"
            f"N={c.N} M={c.M} K={c.K} J={c.J}\n"
            f"auto_heal={c.auto_heal}\n"
            f"poll_interval={c.poll_interval_sec}s\n"
            f"kill_exclusion={','.join(c.kill_exclusion) or 'none'}"
        )
        self._send_reply(chat_id, text)

    def _cmd_help(self, chat_id: str) -> None:
        self._send_reply(chat_id, "AVAILABLE COMMANDS\n\n"
                         "/status - Server health report\n"
                         "/threads - Thread status counters\n"
                         "/processlist - Active queries (top 10)\n"
                         "/config - Monitor configuration\n"
                         "/help - This message")

    def _send_reply(self, chat_id: str, text: str) -> None:
        url = f"{_API_BASE}{self._token}/sendMessage"
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json={"chat_id": chat_id, "text": text})
                if resp.status_code != 200:
                    log.warning("Bot reply failed: %d", resp.status_code)
        except Exception:
            log.debug("Bot reply error", exc_info=True)

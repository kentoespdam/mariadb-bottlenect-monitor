"""Telegram bot — polls getUpdates and dispatches /commands."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

import httpx
from . import bot_commands as cmd
from .config import Config
from .db import DatabaseConnection
from .telegram_alert import _API_BASE

log = logging.getLogger(__name__)

COMMANDS = [
    {"command": "status", "description": "Laporan kesehatan server"},
    {"command": "threads", "description": "Status threads MariaDB"},
    {"command": "processlist", "description": "Query aktif (top 10)"},
    {"command": "config", "description": "Konfigurasi monitor"},
    {"command": "help", "description": "Bantuan commands"}]

class TelegramBot:
    def __init__(self, cfg: Config, db: DatabaseConnection) -> None:
        self._token = cfg.telegram_bot_token
        self._cfg = cfg
        self._db = db
        self._poll_interval = cfg.bot_poll_interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._register_commands()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Telegram bot started")

    def _register_commands(self) -> None:
        try:
            with httpx.Client(timeout=10) as c:
                c.post(f"{_API_BASE}{self._token}/setMyCommands",
                       json={"commands": COMMANDS})
        except Exception:
            log.debug("setMyCommands error", exc_info=True)

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

    def _send_menu_keyboard(self, chat_id: str) -> None:
        kb = [["/status", "/threads"], ["/processlist", "/config"], ["/help"]]
        rm = json.dumps({"keyboard": kb, "resize_keyboard": True, "one_time_keyboard": False})
        try:
            with httpx.Client(timeout=10) as c:
                c.post(f"{_API_BASE}{self._token}/sendMessage",
                       json={"chat_id": chat_id, "text": "Pilih command:", "reply_markup": rm})
        except Exception:
            log.debug("Menu keyboard error", exc_info=True)

    def _dispatch(self, command: str, chat_id: str) -> None:
        if command == "/start":
            self._send_reply(chat_id, "🤖 MariaDB Monitor\nKetik /help untuk bantuan")
            self._send_menu_keyboard(chat_id)
            return
        handlers = {
            "/status": lambda: cmd.cmd_status(self._db),
            "/threads": lambda: cmd.cmd_threads(self._db),
            "/processlist": lambda: cmd.cmd_processlist(self._db),
            "/config": lambda: cmd.cmd_config(self._cfg),
            "/help": lambda: cmd.cmd_help(),
        }
        handler = handlers.get(command)
        if not handler:
            return
        try:
            self._send_reply(chat_id, handler())
        except Exception:
            log.debug("Command %s failed", command, exc_info=True)
            self._send_reply(chat_id, "Error processing command")
        self._send_menu_keyboard(chat_id)

    def _send_reply(self, chat_id: str, text: str) -> None:
        url = f"{_API_BASE}{self._token}/sendMessage"
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json={"chat_id": chat_id, "text": text})
                if resp.status_code != 200:
                    log.warning("Bot reply failed: %d", resp.status_code)
        except Exception:
            log.debug("Bot reply error", exc_info=True)

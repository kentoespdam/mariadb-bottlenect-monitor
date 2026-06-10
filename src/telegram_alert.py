"""Async HTTP POST to Telegram Bot API — best-effort alert delivery."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .config import Config

log = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot"
_RATE_LIMIT_SEC = 60.0


class TelegramAlert:
    """Best-effort Telegram alert sender with per-type rate limiting."""

    def __init__(self, cfg: Config) -> None:
        self._token = cfg.telegram_bot_token
        self._chat_id = cfg.telegram_chat_id
        self._timeout = cfg.alert_send_timeout_sec
        self._enabled = bool(self._token and self._chat_id)
        self._last_sent: dict[str, float] = {}

    def _rate_limited(self, alert_type: str, now: float) -> bool:
        last = self._last_sent.get(alert_type, 0.0)
        return (now - last) < _RATE_LIMIT_SEC

    def _format_message(self, alert_type: str, data: dict[str, Any]) -> str:
        label = alert_type.upper().replace("_", " ")
        if "text" in data:
            return str(data["text"])
        parts = [f"🔔 {label}"]
        if "threads_running" in data:
            parts.append(f"📊 Threads: {data['threads_running']}")
        if "blocker" in data and data["blocker"]:
            b = data["blocker"]
            parts.append(f"🚨 Blocker: {b.get('user', '?')}@{b.get('host', '?')} (ID {b.get('thread_id', '?')})")
            if b.get("query_text"):
                parts.append(f"📝 Query: {b['query_text'][:100]}")
        elif "user" in data and "host" in data:
            parts.append(f"🚨 Thread: {data.get('user', '?')}@{data.get('host', '?')} (ID {data.get('thread_id', '?')})")
        if "action" in data:
            parts.append(f"⚡ {data['action']}")
        if "error" in data:
            parts.append(f"❌ {data['error']}")
        return "\n".join(parts)

    async def send(self, alert_type: str, data: dict[str, Any]) -> None:
        """Send (or drop if rate-limited). Never raises."""
        if not self._enabled:
            return

        now = time.time()
        if self._rate_limited(alert_type, now):
            return

        self._last_sent[alert_type] = now
        text = self._format_message(alert_type, data)
        url = f"{_API_BASE}{self._token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": text}

        try:
            async with asyncio.timeout(self._timeout):
                import httpx

                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code != 200:
                        log.warning("Telegram send failed: %d %s", resp.status_code, resp.text[:200])
        except asyncio.TimeoutError:
            log.warning("Telegram send timed out after %ds", self._timeout)
        except Exception:
            log.warning("Telegram send error", exc_info=True)

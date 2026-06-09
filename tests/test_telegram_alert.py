"""Test telegram_alert: rate limiting, formatting, timeout handling."""

from src.config import Config
from src.telegram_alert import _RATE_LIMIT_SEC, TelegramAlert


def _make_cfg(**kwargs: object) -> Config:
    overrides = {
        "telegram_bot_token": "test:token",
        "telegram_chat_id": "12345",
        "alert_send_timeout_sec": 1,
    }
    overrides.update(kwargs)
    return Config(threads_entry=40, threads_exit=20, **overrides)


class TestTelegramAlert:
    def test_rate_limit_first_call_allowed(self) -> None:
        cfg = _make_cfg()
        alert = TelegramAlert(cfg)
        assert not alert._rate_limited("bottleneck", 999.0)

    def test_rate_limit_second_call_blocked(self) -> None:
        cfg = _make_cfg()
        alert = TelegramAlert(cfg)
        alert._last_sent["bottleneck"] = 100.0
        assert alert._rate_limited("bottleneck", 100.0 + _RATE_LIMIT_SEC - 1)

    def test_rate_limit_expired(self) -> None:
        cfg = _make_cfg()
        alert = TelegramAlert(cfg)
        alert._last_sent["bottleneck"] = 100.0
        assert not alert._rate_limited("bottleneck", 100.0 + _RATE_LIMIT_SEC + 1)

    def test_rate_limit_different_types_independent(self) -> None:
        cfg = _make_cfg()
        alert = TelegramAlert(cfg)
        alert._last_sent["bottleneck"] = 100.0
        assert not alert._rate_limited("heal", 100.0)

    def test_send_no_token(self) -> None:
        import asyncio

        cfg = _make_cfg(telegram_bot_token="")
        alert = TelegramAlert(cfg)
        result = asyncio.run(alert.send("test", {}))
        assert result is None

    def test_send_http_error(self) -> None:
        import asyncio

        alert = TelegramAlert(_make_cfg())
        result = asyncio.run(alert.send("test", {"action": "heal"}))
        assert result is None

    def test_format_message_bottleneck(self) -> None:
        alert = TelegramAlert(_make_cfg())
        msg = alert._format_message(
            "bottleneck_detected", {"threads_running": 50, "blocker": {"user": "u1", "host": "h1", "thread_id": 123, "query_text": "SELECT 1"}}
        )
        assert "BOTTLENECK DETECTED" in msg
        assert "50" in msg
        assert "u1@h1" in msg
        assert "123" in msg

    def test_format_message_heal(self) -> None:
        alert = TelegramAlert(_make_cfg())
        msg = alert._format_message("auto_heal_killed", {"action": "kill sent", "thread_id": 456, "user": "dev", "host": "h1"})
        assert "AUTO HEAL KILLED" in msg
        assert "kill sent" in msg
        assert "dev@h1" in msg

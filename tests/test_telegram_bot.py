"""Test telegram_bot: command dispatch, message parsing, reply sending."""

from unittest.mock import MagicMock, patch

from src.config import Config
from src.telegram_bot import TelegramBot


def _make_bot(**overrides: object) -> tuple[TelegramBot, Config, MagicMock]:
    defaults = {
        "telegram_bot_token": "test:token",
        "bot_poll_interval_sec": 1.0,
    }
    defaults.update(overrides)
    cfg = Config(threads_entry=40, threads_exit=20, **defaults)
    db = MagicMock()
    return TelegramBot(cfg, db), cfg, db


class TestTelegramBotInit:
    def test_stopped_by_default(self) -> None:
        bot, _, _ = _make_bot()
        assert not bot._stop.is_set()
        assert bot._thread is None

    def test_start_creates_daemon_thread(self) -> None:
        bot, _, _ = _make_bot()
        with patch.object(bot, "_loop"):
            bot.start()
            assert bot._thread is not None
            assert bot._thread.daemon is True
            bot.stop()


class TestPollOnce:
    def test_empty_updates_returns_same_offset(self) -> None:
        bot, _, _ = _make_bot()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": []}
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(
                return_value=MagicMock(get=MagicMock(return_value=mock_resp))
            )
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            offset = bot._poll_once("http://base", 0)
        assert offset == 0

    def test_update_advances_offset(self) -> None:
        bot, _, _ = _make_bot()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": [{"update_id": 42}]}
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(
                return_value=MagicMock(get=MagicMock(return_value=mock_resp))
            )
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            offset = bot._poll_once("http://base", 0)
        assert offset == 43

    def test_command_triggers_dispatch(self) -> None:
        bot, _, _ = _make_bot()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": [{
                "update_id": 1,
                "message": {"text": "/help", "chat": {"id": 999}},
            }]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(
                return_value=MagicMock(get=MagicMock(return_value=mock_resp))
            )
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            with patch.object(bot, "_dispatch") as mock_dispatch:
                bot._poll_once("http://base", 0)
                mock_dispatch.assert_called_once_with("/help", "999")


class TestDispatch:
    def test_unknown_command_ignored(self) -> None:
        bot, _, _ = _make_bot()
        # Should not raise
        bot._dispatch("/unknown", "123")

    def test_help_sends_reply(self) -> None:
        bot, _, _ = _make_bot()
        with patch.object(bot, "_send_reply") as mock_reply:
            bot._dispatch("/help", "123")
            mock_reply.assert_called_once()
            assert "AVAILABLE COMMANDS" in mock_reply.call_args[0][1]

    def test_status_calls_fetch(self) -> None:
        bot, _, db = _make_bot()
        db.query_one.return_value = ("Threads_running", "5")
        with patch("src.bot_commands.fetch_status", return_value={"Threads_running": 5, "Uptime": 100, "Questions": 100, "Slow_queries": 0, "Innodb_buffer_pool_read_requests": 1000, "Innodb_buffer_pool_reads": 10, "Threads_connected": 10}):
            with patch.object(bot, "_send_reply") as mock_reply:
                bot._dispatch("/status", "123")
                mock_reply.assert_called_once()
                assert "STATUS LAPORAN" in mock_reply.call_args[0][1]

    def test_config_sends_config_info(self) -> None:
        bot, _, _ = _make_bot()
        with patch.object(bot, "_send_reply") as mock_reply:
            bot._dispatch("/config", "123")
            text = mock_reply.call_args[0][1]
            assert "MONITOR CONFIG" in text
            assert "entry=40" in text
            assert "auto_heal=False" in text

    def test_threads_queries_db(self) -> None:
        bot, _, db = _make_bot()
        db.query.return_value = [("Threads_running", "5"), ("Threads_connected", "10")]
        with patch.object(bot, "_send_reply") as mock_reply:
            bot._dispatch("/threads", "123")
            text = mock_reply.call_args[0][1]
            assert "THREAD STATUS" in text
            assert "Threads_running: 5" in text

    def test_processlist_empty(self) -> None:
        bot, _, db = _make_bot()
        db.query.return_value = []
        with patch.object(bot, "_send_reply") as mock_reply:
            bot._dispatch("/processlist", "123")
            assert "No active queries" in mock_reply.call_args[0][1]

    def test_processlist_with_queries(self) -> None:
        bot, _, db = _make_bot()
        db.query.return_value = [
            (1, "root", "localhost", "test", 10, "SELECT 1"),
        ]
        with patch.object(bot, "_send_reply") as mock_reply:
            bot._dispatch("/processlist", "123")
            text = mock_reply.call_args[0][1]
            assert "ACTIVE QUERIES" in text
            assert "ID:1 root@localhost" in text
            assert "SELECT 1" in text

    def test_command_exception_sends_error(self) -> None:
        bot, _, db = _make_bot()
        db.query.side_effect = Exception("db down")
        with patch.object(bot, "_send_reply") as mock_reply:
            bot._dispatch("/threads", "123")
            assert "Error processing command" in mock_reply.call_args[0][1]


class TestSendReply:
    def test_send_reply_posts_to_api(self) -> None:
        bot, _, _ = _make_bot()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            bot._send_reply("123", "hello")
            mock_client.post.assert_called_once()
            call_kwargs = mock_client.post.call_args
            assert call_kwargs[1]["json"]["text"] == "hello"
            assert call_kwargs[1]["json"]["chat_id"] == "123"

    def test_send_reply_handles_error(self) -> None:
        bot, _, _ = _make_bot()
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=MagicMock(side_effect=Exception("net")))
            )
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            # Should not raise
            bot._send_reply("123", "hello")

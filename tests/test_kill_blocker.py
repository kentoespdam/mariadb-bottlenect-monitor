"""Test kill_blocker: 7 scenarios."""
from unittest.mock import MagicMock

from src.auto_heal import kill_blocker
from src.config import Config


class TestKillBlocker:
    def _make_cfg(self) -> Config:
        return Config(
            threads_entry=40, threads_exit=20, kill_exclusion=("repl@%",),
            monitor_user="monitor", monitor_host="127.0.0.1",
        )

    def _make_identity(self) -> dict:
        return {"thread_id": 123, "user": "user1", "host": "host1", "db": "mydb"}

    def _make_blocker(self) -> dict:
        return {"thread_id": 123, "user": "user1", "host": "host1",
                "trx_started": "...", "query_text": "SELECT", "waiter_count": 2}

    def _mock_db(self, identity: dict | None = None) -> MagicMock:
        db = MagicMock()
        if identity:
            db.query.return_value = [(identity["thread_id"], identity["user"],
                                      identity["host"], identity["db"])]
        else:
            db.query.return_value = []
        return db

    def test_kill_sent(self) -> None:
        ident = self._make_identity()
        db = self._mock_db(ident)
        ok, msg = kill_blocker(db, ident, self._make_blocker(), self._make_cfg(),
                               {"n_elapsed": 5, "age_threshold": 3})
        assert ok
        assert msg == "kill_sent"

    def test_excluded_user(self) -> None:
        ident = {"thread_id": 123, "user": "repl", "host": "host1", "db": "mydb"}
        db = self._mock_db(ident)
        ok, msg = kill_blocker(db, ident, self._make_blocker(), self._make_cfg(),
                               {"n_elapsed": 5, "age_threshold": 3})
        assert not ok
        assert msg == "excluded"



    def test_age_below_threshold(self) -> None:
        ident = self._make_identity()
        db = self._mock_db(ident)
        ok, msg = kill_blocker(db, ident, self._make_blocker(), self._make_cfg(),
                               {"n_elapsed": 1, "age_threshold": 3})
        assert not ok
        assert msg == "age_below_threshold"

    def test_excluded(self) -> None:
        ident = {"thread_id": 456, "user": "repl", "host": "slave1", "db": ""}
        db = self._mock_db(ident)
        ok, msg = kill_blocker(db, ident, self._make_blocker(), self._make_cfg(),
                               {"n_elapsed": 5, "age_threshold": 3})
        assert not ok
        assert msg == "excluded"

    def test_is_monitor_self(self) -> None:
        ident = {"thread_id": 789, "user": "monitor", "host": "127.0.0.1", "db": ""}
        db = self._mock_db(ident)
        ok, msg = kill_blocker(db, ident, self._make_blocker(), self._make_cfg(),
                               {"n_elapsed": 5, "age_threshold": 3})
        assert not ok
        assert msg == "is_monitor_self"

    def test_kill_fails(self) -> None:
        ident = self._make_identity()
        db = self._mock_db(ident)
        db.query.side_effect = Exception("KILL denied")
        ok, msg = kill_blocker(db, ident, self._make_blocker(), self._make_cfg(),
                               {"n_elapsed": 5, "age_threshold": 3})
        assert not ok
        assert "kill_failed" in msg

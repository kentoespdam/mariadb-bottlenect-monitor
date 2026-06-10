"""Test kill_blocker: fresh-identity resolution, guards, KILL escalation."""
from unittest.mock import MagicMock

from src.auto_heal import kill_blocker
from src.config import Config


class TestKillBlocker:
    def _make_cfg(self) -> Config:
        return Config(
            threads_entry=40, threads_exit=20, kill_exclusion=("repl@%",),
            monitor_user="monitor", monitor_host="127.0.0.1",
        )

    def _blocker(self) -> dict:
        return {"thread_id": 123}

    def _db(self, user: str, host: str, command: str = "Query", info: str = "SELECT 1") -> MagicMock:
        # First db.query → PROCESSLIST row for resolve_blocker_identity; KILL returns [].
        db = MagicMock()
        db.query.side_effect = [[(123, user, host, "mydb", command, info)], []]
        return db

    def test_active_blocker_killed_query(self) -> None:
        db = self._db("user1", "host1:51310")
        ok, outcome = kill_blocker(db, self._blocker(), self._make_cfg())
        assert ok
        assert outcome == "killed_query"
        assert db.query.call_args_list[1].args[0] == "KILL QUERY %s"

    def test_idle_blocker_killed_connection(self) -> None:
        db = self._db("user1", "host1:51310", command="Sleep", info="")
        ok, outcome = kill_blocker(db, self._blocker(), self._make_cfg())
        assert ok
        assert outcome == "killed_connection"
        assert db.query.call_args_list[1].args[0] == "KILL %s"

    def test_excluded_matches_after_host_normalise(self) -> None:
        # repl@% with ephemeral port must still match (regression: finding #2).
        db = self._db("repl", "192.168.230.1:51310")
        ok, outcome = kill_blocker(db, self._blocker(), self._make_cfg())
        assert not ok
        assert outcome == "excluded"

    def test_is_monitor_self(self) -> None:
        db = self._db("monitor", "127.0.0.1:33060")
        ok, outcome = kill_blocker(db, self._blocker(), self._make_cfg())
        assert not ok
        assert outcome == "is_monitor_self"

    def test_unresolved_identity_is_failsafe_excluded(self) -> None:
        db = MagicMock()
        db.query.return_value = []  # PROCESSLIST row gone between attribution and kill
        ok, outcome = kill_blocker(db, self._blocker(), self._make_cfg())
        assert not ok
        assert outcome == "excluded_unresolved"

    def test_kill_fails(self) -> None:
        db = MagicMock()
        db.query.side_effect = [[(123, "user1", "host1", "mydb", "Query", "SELECT 1")],
                                Exception("KILL denied")]
        ok, outcome = kill_blocker(db, self._blocker(), self._make_cfg())
        assert not ok
        assert "kill_failed" in outcome

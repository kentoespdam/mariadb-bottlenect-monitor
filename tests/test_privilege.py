"""Test _check_privilege and resolve_blocker_identity."""
from unittest.mock import MagicMock

from src.auto_heal import _check_privilege, resolve_blocker_identity


class TestCheckPrivilege:
    def test_has_super(self) -> None:
        db = MagicMock()
        db.query_one.return_value = ("monitor@localhost",)
        db.query.return_value = [("GRANT SUPER ON *.* TO 'monitor'@'localhost'",)]
        assert _check_privilege(db)

    def test_has_all_privileges(self) -> None:
        db = MagicMock()
        db.query_one.return_value = ("monitor@localhost",)
        db.query.return_value = [("GRANT ALL PRIVILEGES ON *.* TO 'monitor'@'localhost'",)]
        assert _check_privilege(db)

    def test_no_privilege(self) -> None:
        db = MagicMock()
        db.query_one.return_value = ("monitor@localhost",)
        db.query.return_value = [("GRANT SELECT ON *.* TO 'monitor'@'localhost'",)]
        assert not _check_privilege(db)

    def test_query_failure(self) -> None:
        db = MagicMock()
        db.query_one.side_effect = Exception("connection dead")
        assert not _check_privilege(db)

    def test_no_row_returned(self) -> None:
        db = MagicMock()
        db.query_one.return_value = None
        assert not _check_privilege(db)


class TestResolveBlockerIdentity:
    def test_found(self) -> None:
        db = MagicMock()
        db.query.return_value = [(123, "user1", "host1:3307", "mydb", "Query", "SELECT 1")]
        result = resolve_blocker_identity(db, 123)
        assert result is not None
        assert result["thread_id"] == 123
        assert result["host"] == "host1"
        assert result["command"] == "Query"
        assert result["info"] == "SELECT 1"

    def test_idle_null_info(self) -> None:
        db = MagicMock()
        db.query.return_value = [(123, "user1", "host1:3307", "mydb", "Sleep", None)]
        result = resolve_blocker_identity(db, 123)
        assert result is not None
        assert result["command"] == "Sleep"
        assert result["info"] == ""

    def test_not_found(self) -> None:
        db = MagicMock()
        db.query.return_value = []
        assert resolve_blocker_identity(db, 999) is None

    def test_query_error(self) -> None:
        db = MagicMock()
        db.query.side_effect = Exception("query failed")
        assert resolve_blocker_identity(db, 123) is None

"""Test db: connection, failure classification, health check, reconnect."""

from unittest.mock import MagicMock, patch

from src.db import ConnectionFailureKind, DatabaseConnection, _classify_failure


def _op_error(msg: str) -> Exception:
    """Create a pymysql-like OperationalError with given message."""
    import pymysql

    return pymysql.err.OperationalError(2006, msg)


class TestClassifyFailure:
    def test_refused(self) -> None:
        kind = _classify_failure(_op_error("connection refused"))
        assert kind == ConnectionFailureKind.REFUSED

    def test_timeout(self) -> None:
        kind = _classify_failure(_op_error("timed out"))
        assert kind == ConnectionFailureKind.TIMEOUT

    def test_auth_failure(self) -> None:
        kind = _classify_failure(_op_error("Access denied for user"))
        assert kind == ConnectionFailureKind.AUTH

    def test_unknown_defaults_to_refused(self) -> None:
        kind = _classify_failure(_op_error("something else"))
        assert kind == ConnectionFailureKind.REFUSED


class TestDatabaseConnection:
    def test_health_check_success(self) -> None:
        db = DatabaseConnection.__new__(DatabaseConnection)
        cursor = MagicMock()
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        db._conn = conn
        assert db.health_check()

    def test_health_check_failure(self) -> None:
        import pymysql

        db = DatabaseConnection.__new__(DatabaseConnection)
        cursor = MagicMock()
        cursor.execute.side_effect = pymysql.err.OperationalError(2006, "server gone")
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        db._conn = conn
        assert not db.health_check()
        assert db._conn is None

    def test_health_check_no_connection(self) -> None:
        db = DatabaseConnection.__new__(DatabaseConnection)
        db._conn = None
        assert not db.health_check()

    def test_conn_property_raises_when_no_connection(self) -> None:
        from src.db import DatabaseError

        db = DatabaseConnection.__new__(DatabaseConnection)
        db._conn = None
        try:
            _ = db.conn
            assert False, "Expected DatabaseError"
        except DatabaseError:
            pass

    def test_reconnect_success(self) -> None:
        db = DatabaseConnection.__new__(DatabaseConnection)
        db._config = MagicMock()
        db._config.db_port = 3307
        with patch.object(db, "connect") as mock_connect:
            mock_connect.return_value = None
            assert db.reconnect()

    def test_reconnect_failure(self) -> None:
        from src.db import DatabaseError

        db = DatabaseConnection.__new__(DatabaseConnection)
        db._config = MagicMock()
        db._config.db_port = 3307
        with patch.object(db, "connect") as mock_connect:
            mock_connect.side_effect = DatabaseError("fail")
            assert not db.reconnect()

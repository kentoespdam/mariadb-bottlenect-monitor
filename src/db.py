"""Persistent MariaDB connection via extra_port (3307).

Single persistent connection - never reconnects per poll.
Connection failure is NOT monitor-blindness at startup (no baseline).
"""

from __future__ import annotations

import logging
from enum import Enum

import pymysql

from .config import Config

log = logging.getLogger(__name__)


class ConnectionFailureKind(Enum):
    REFUSED = "refused"
    TIMEOUT = "timeout"
    DROPPED = "dropped"
    AUTH = "auth"


class DatabaseError(Exception):
    """Base for all DB errors."""

    def __init__(self, message: str, kind: ConnectionFailureKind | None = None):
        super().__init__(message)
        self.kind = kind


class DatabaseConnection:
    """Holds one persistent MariaDB connection for the monitor lifetime."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._conn: pymysql.Connection | None = None

    @property
    def conn(self) -> pymysql.Connection:
        if self._conn is None:
            raise DatabaseError("No active connection")
        return self._conn

    def connect(self) -> None:
        """Open persistent connection to extra_port (3307)."""
        try:
            self._conn = pymysql.connect(
                host=self._config.db_host,
                port=self._config.db_port,
                user=self._config.db_user,
                password=self._config.db_password,
                database=self._config.db_name or None,
                charset="utf8mb4",
                read_timeout=5,
                write_timeout=5,
                connect_timeout=5,
                autocommit=True,
            )
            log.info("Connected to MariaDB via extra_port %d", self._config.db_port)
        except pymysql.OperationalError as exc:
            self._conn = None
            kind = _classify_failure(exc)
            raise DatabaseError(f"MariaDB connection failed: {exc}", kind=kind) from exc

    def health_check(self) -> bool:
        if self._conn is None:
            return False
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except pymysql.OperationalError:
            self._conn = None
            return False

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Run a query. Raises DatabaseError on connection failure."""
        if self._conn is None:
            raise DatabaseError("No active connection")
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        except pymysql.OperationalError as exc:
            self._conn = None
            raise DatabaseError(f"Query failed: {exc}", kind=ConnectionFailureKind.DROPPED) from exc

    def query_one(self, sql: str, params: tuple = ()) -> tuple | None:
        """Run a query, return first row or None."""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def reconnect(self) -> bool:
        """Attempt reconnection. Returns True on success."""
        try:
            self.connect()
            return True
        except DatabaseError:
            return False


def _classify_failure(exc: pymysql.OperationalError) -> ConnectionFailureKind:
    msg = str(exc).lower()
    if "access denied" in msg or "authentication" in msg:
        return ConnectionFailureKind.AUTH
    if "connection refused" in msg:
        return ConnectionFailureKind.REFUSED
    if "timed out" in msg or "timeout" in msg:
        return ConnectionFailureKind.TIMEOUT
    return ConnectionFailureKind.REFUSED

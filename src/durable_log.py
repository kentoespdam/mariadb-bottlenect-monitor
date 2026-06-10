"""Append-only JSON Lines durable log — single source of truth.

Backed by host volume. Written only. fsync added for kill-audit records.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class DurableLog:
    """Append-only JSONL log with optional fsync."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._fd: int | None = None
        self._owns_fd = False
        self._ensure_writable()

    def _ensure_writable(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(str(self._path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            self._owns_fd = True
        except OSError as exc:
            raise RuntimeError(f"Durable log path not writable: {self._path} — {exc}") from exc

    def close(self) -> None:
        if self._owns_fd and self._fd is not None:
            os.close(self._fd)
            self._fd = None
            self._owns_fd = False

    def append(self, record: dict[str, Any], *, fsync: bool = False) -> None:
        """Write one JSON line. fsync=True for kill-audit intent lines."""
        record.setdefault("ts", datetime.now(timezone.utc).isoformat())
        line = (json.dumps(record, default=str) + "\n").encode("utf-8")
        try:
            if self._fd is None:
                self._fd = os.open(str(self._path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            os.write(self._fd, line)
            if fsync:
                os.fsync(self._fd)
        except OSError as exc:
            raise RuntimeError(f"Durable log write failed: {exc}") from exc

    def __enter__(self) -> DurableLog:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

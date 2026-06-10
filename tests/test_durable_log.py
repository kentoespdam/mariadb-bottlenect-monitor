"""Test durable_log: append, close, context manager, file content."""

import json
import os
import tempfile

from src.durable_log import DurableLog


class TestDurableLog:
    def _read_file(self, path: str) -> list[dict]:
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_append_writes_to_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            log = DurableLog(path)
            log.append({"event": "test", "value": 42})
            log.append({"event": "test2", "value": 99})
            log.close()
            entries = self._read_file(path)
            assert len(entries) == 2
            assert entries[0]["event"] == "test"
            assert entries[1]["value"] == 99
        finally:
            os.unlink(path)

    def test_close_releases_fd(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            log = DurableLog(path)
            log.close()
            assert log._fd is None
        finally:
            os.unlink(path)

    def test_context_manager(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            with DurableLog(path) as log:
                log.append({"event": "ctx"})
            entries = self._read_file(path)
            assert len(entries) == 1
        finally:
            os.unlink(path)

    def test_append_adds_timestamp(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            log = DurableLog(path)
            log.append({"event": "ts_test"})
            log.close()
            entries = self._read_file(path)
            assert "ts" in entries[0]
        finally:
            os.unlink(path)

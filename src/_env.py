"""Env-var helpers — parse/validate typed values from os.environ.

Three-tier contract per ADR-0001:
  Tier 1: absent → safe default
  Tier 2: absent with no default → refuse to start
  Tier 3: malformed → refuse to start
"""

from __future__ import annotations

import os
import sys


def _load_dotenv() -> None:
    """Load .env file from project root into os.environ (if not already set)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            # Don't override existing env vars
            if key not in os.environ:
                os.environ[key] = val


_load_dotenv()

DEFAULTS: dict[str, int | float | bool | str] = {
    "N": 5,
    "M": 10,
    "K": 3,
    "J": 5,
    "poll_interval_sec": 1.0,
    "alert_send_timeout_sec": 5,
    "auto_heal": False,
    "db_port": 3307,
    "durable_log_path": "/var/log/monitor/monitor.jsonl",
    "log_max_size_mb": 50,
    "log_max_files": 5,
    "log_retention_days": 30,
}

FLOOR_N_M = 1
FLOOR_K_J = 0


def _env_int(key: str, default: int | None = None) -> int:
    raw = os.environ.get(key)
    if raw is None:
        if default is None:
            sys.exit(f"Required config missing: {key}")
        return default
    try:
        return int(raw)
    except ValueError:
        sys.exit(f"Config error: {key} must be an integer, got '{raw}'")


def _env_float(key: str, default: float | None = None) -> float:
    raw = os.environ.get(key)
    if raw is None:
        if default is None:
            sys.exit(f"Required config missing: {key}")
        return default
    try:
        return float(raw)
    except ValueError:
        sys.exit(f"Config error: {key} must be a number, got '{raw}'")


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "").lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes")


def _env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_csv(key: str) -> tuple[str, ...]:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return ()
    return tuple(s.strip() for s in raw.split(",") if s.strip())

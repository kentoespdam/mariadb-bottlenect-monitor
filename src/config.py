"""Configuration — single source of truth for all monitor tunables.

Three-tier startup contract per ADR-0001:
  Tier 1: patience knobs absent → documented safe defaults
  Tier 2: detection thresholds absent → refuse to start
  Tier 3: malformed/incoherent values → refuse to start
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from ._env import FLOOR_K_J, FLOOR_N_M, _env_bool, _env_csv, _env_float, _env_int, _env_str


@dataclass(frozen=True)
class Config:
    """Immutable monitor configuration. All fields set once at startup."""

    threads_entry: int
    threads_exit: int

    N: int = 5
    M: int = 10
    K: int = 3
    J: int = 5

    db_host: str = "127.0.0.1"
    db_port: int = 3307
    db_user: str = "monitor"
    db_password: str = ""
    db_name: str = ""

    poll_interval_sec: float = 1.0
    auto_heal: bool = False
    kill_exclusion: tuple[str, ...] = ()

    durable_log_path: str = "/var/log/monitor/monitor.jsonl"
    log_max_size_mb: int = 50
    log_max_files: int = 5
    log_retention_days: int = 30

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alert_send_timeout_sec: int = 5

    monitor_user: str = "monitor"
    monitor_host: str = "127.0.0.1"

    def __post_init__(self) -> None:
        """Run Tier 2 + Tier 3 validation after construction."""
        if self.threads_exit >= self.threads_entry:
            sys.exit(
                f"Config error: threads_exit ({self.threads_exit}) must be "
                f"strictly less than threads_entry ({self.threads_entry}). "
                "Set both in environment variables."
            )
        if self.N < FLOOR_N_M:
            sys.exit(f"Config error: N must be >= {FLOOR_N_M}, got {self.N}")
        if self.M < FLOOR_N_M:
            sys.exit(f"Config error: M must be >= {FLOOR_N_M}, got {self.M}")
        if self.K < FLOOR_K_J:
            sys.exit(f"Config error: K must be >= {FLOOR_K_J}, got {self.K}")
        if self.J < FLOOR_K_J:
            sys.exit(f"Config error: J must be >= {FLOOR_K_J}, got {self.J}")


def load_config() -> Config:
    """Build a Config from environment variables."""
    from ._env import DEFAULTS

    threads_entry = _env_int("THREADS_ENTRY")
    threads_exit = _env_int("THREADS_EXIT")

    return Config(
        threads_entry=threads_entry,
        threads_exit=threads_exit,
        N=_env_int("N", DEFAULTS["N"]),
        M=_env_int("M", DEFAULTS["M"]),
        K=_env_int("K", DEFAULTS["K"]),
        J=_env_int("J", DEFAULTS["J"]),
        db_host=_env_str("DB_HOST", "127.0.0.1"),
        db_port=_env_int("DB_PORT", DEFAULTS["db_port"]),
        db_user=_env_str("DB_USER", "monitor"),
        db_password=_env_str("DB_PASSWORD", ""),
        db_name=_env_str("DB_NAME", ""),
        poll_interval_sec=_env_float("POLL_INTERVAL_SEC", DEFAULTS["poll_interval_sec"]),
        auto_heal=_env_bool("AUTO_HEAL", DEFAULTS["auto_heal"]),
        kill_exclusion=_env_csv("KILL_EXCLUSION"),
        durable_log_path=_env_str("DURABLE_LOG_PATH", DEFAULTS["durable_log_path"]),
        log_max_size_mb=_env_int("LOG_MAX_SIZE_MB", DEFAULTS["log_max_size_mb"]),
        log_max_files=_env_int("LOG_MAX_FILES", DEFAULTS["log_max_files"]),
        log_retention_days=_env_int("LOG_RETENTION_DAYS", DEFAULTS["log_retention_days"]),
        telegram_bot_token=_env_str("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=_env_str("TELEGRAM_CHAT_ID", ""),
        alert_send_timeout_sec=_env_int("ALERT_SEND_TIMEOUT_SEC", DEFAULTS["alert_send_timeout_sec"]),
        monitor_user=_env_str("MONITOR_USER", "monitor"),
        monitor_host=_env_str("MONITOR_HOST", "127.0.0.1"),
    )

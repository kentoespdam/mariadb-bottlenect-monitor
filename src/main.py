"""Entry point — parse args, load config, wire components, run poll loop."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from .config import load_config
from .counters import KCounter, NCounter
from .db import DatabaseConnection
from .durable_log import DurableLog
from .poll import PollResult
from .scheduler import schedule_polls
from .state import StateToggle
from .telegram_alert import TelegramAlert
from .auto_heal import kill_blocker, resolve_blocker_identity
from .status_report import fetch_status, format_status_report
from .telegram_bot import TelegramBot

log = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _send_telegram(telegram: TelegramAlert, alert_type: str, data: dict) -> None:
    """Send Telegram alert synchronously (best-effort, never blocks poll loop on error)."""
    try:
        import asyncio
        asyncio.run(telegram.send(alert_type, data))
    except Exception:
        log.debug("Telegram send skipped", exc_info=True)


def _on_result(
    result: PollResult,
    n_counter: NCounter,
    k_counter: KCounter,
    bottleneck: StateToggle,
    cfg: Config,
    db: DatabaseConnection,
    durable: DurableLog,
    blocker_state: dict,
    telegram: TelegramAlert,
    prev_bottleneck: list[bool],
    last_status_sent: list[float],
) -> None:
    """Log poll cycle state and trigger auto-heal when conditions are met."""
    if result.phase_one_ok:
        log.debug(
            "poll ok  tr=%s  N=%d/%s  K=%d  bottleneck=%s",
            result.threads_running,
            n_counter.value,
            "SAT" if n_counter.satisfied else n_counter.value,
            k_counter.value,
            "YES" if bottleneck.is_set else "no",
        )

        # --- Telegram: bottleneck edge detection ---
        if bottleneck.is_set and not prev_bottleneck[0]:
            log.info("Bottleneck DETECTED — sending Telegram alert")
            _send_telegram(telegram, "bottleneck_detected", {
                "threads_running": result.threads_running,
                "blocker": result.blocker,
                "action": "Bottleneck terdeteksi — threads_running melebihi threshold",
            })
        elif not bottleneck.is_set and prev_bottleneck[0]:
            log.info("Bottleneck RESOLVED — sending Telegram alert")
            _send_telegram(telegram, "bottleneck_resolved", {
                "threads_running": result.threads_running,
                "action": "Bottleneck resolved — threads_running kembali normal",
            })
        prev_bottleneck[0] = bottleneck.is_set

        # --- Periodic status report ---
        now = time.time()
        if (cfg.status_interval_sec > 0
                and now - last_status_sent[0] >= cfg.status_interval_sec):
            try:
                status = fetch_status(db)
                report = format_status_report(status)
                _send_telegram(telegram, "status_report", {"text": report})
            except Exception:
                log.debug("Status report failed", exc_info=True)
            last_status_sent[0] = now

        # Auto-heal: track blocker age and kill when threshold reached
        if cfg.auto_heal and result.blocker is not None:
            blocker_id = result.blocker["thread_id"]
            if blocker_id not in blocker_state:
                blocker_state[blocker_id] = {"seen": 0, "identity": result.blocker}
            blocker_state[blocker_id]["seen"] += 1

            if blocker_state[blocker_id]["seen"] >= cfg.M:
                identity = blocker_state[blocker_id]["identity"]
                poll_state = {"n_elapsed": blocker_state[blocker_id]["seen"], "age_threshold": cfg.M}
                success, msg = kill_blocker(db, identity, result.blocker, cfg, poll_state)
                log.info("Auto-heal thread %d: success=%s msg=%s", blocker_id, success, msg)
                durable.append({
                    "event": "auto_heal",
                    "thread_id": blocker_id,
                    "success": success,
                    "outcome": msg,
                    "user": identity.get("user"),
                    "host": identity.get("host"),
                })
                # --- Telegram: auto_heal result ---
                if success:
                    _send_telegram(telegram, "auto_heal_killed", {
                        "thread_id": blocker_id,
                        "user": identity.get("user"),
                        "host": identity.get("host"),
                        "action": f"KILL QUERY {blocker_id} — {msg}",
                    })
                    del blocker_state[blocker_id]
                else:
                    _send_telegram(telegram, "auto_heal_failed", {
                        "thread_id": blocker_id,
                        "user": identity.get("user"),
                        "host": identity.get("host"),
                        "error": msg,
                        "action": f"Gagal kill thread {blocker_id}",
                    })
        elif result.blocker is None:
            # Clear stale blocker tracking when no blocker detected
            stale_ids = [bid for bid, s in blocker_state.items() if s["seen"] > cfg.M + 3]
            for bid in stale_ids:
                del blocker_state[bid]
    else:
        log.warning(
            "poll blind  K=%d/%s  N=%s",
            k_counter.value,
            "SAT" if k_counter.satisfied else k_counter.value,
            f"{n_counter.value}*" if n_counter.value else "0",
        )


def _handle_signal(signum: int, _frame: object) -> None:
    log.info("Signal %d received, shutting down...", signum)
    raise SystemExit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="MariaDB Bottleneck Monitor")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    cfg = load_config()
    log.info(
        "Config loaded: entry=%d, exit=%d, N=%d, M=%d, K=%d, J=%d, auto_heal=%s",
        cfg.threads_entry,
        cfg.threads_exit,
        cfg.N,
        cfg.M,
        cfg.K,
        cfg.J,
        cfg.auto_heal,
    )

    durable = DurableLog(cfg.durable_log_path)
    log.info("Durable log ready: %s", cfg.durable_log_path)

    db = DatabaseConnection(cfg)
    db.connect()
    log.info("Database connected on %s:%d", cfg.db_host, cfg.db_port)

    from .auto_heal import _check_privilege

    has_super = _check_privilege(db)
    log.info("Capability check: SUPER privilege=%s", has_super)

    telegram = TelegramAlert(cfg)
    telegram_enabled = bool(cfg.telegram_bot_token and cfg.telegram_chat_id)
    log.info("Telegram alerts: %s (chat_id=%s)", "enabled" if telegram_enabled else "disabled", cfg.telegram_chat_id)

    n_counter = NCounter(cfg.N)
    k_counter = KCounter(cfg.K)
    bottleneck_state = StateToggle("bottleneck")
    prev_bottleneck: list[bool] = [False]
    last_status_sent: list[float] = [time.time()]
    log.info("State machine ready: N_threshold=%d, K_threshold=%d", cfg.N, cfg.K)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    import asyncio

    data: dict[str, object] = {
        "action": f"started on {cfg.monitor_host}",
        "threads_running": f"entry={cfg.threads_entry},exit={cfg.threads_exit}",
    }
    asyncio.run(telegram.send("started", data))

    bot = TelegramBot(cfg, db)
    if telegram_enabled:
        bot.start()

    blocker_state: dict = {}

    try:
        schedule_polls(
            cfg,
            db,
            n_counter,
            k_counter,
            bottleneck_state,
            durable,
            lambda r: _on_result(
                r, n_counter, k_counter, bottleneck_state, cfg, db, durable,
                blocker_state, telegram, prev_bottleneck, last_status_sent,
            ),
        )
    except KeyboardInterrupt:
        log.info("Shutdown requested")
    finally:
        bot.stop()
        durable.close()
        log.info("Monitor stopped")


if __name__ == "__main__":
    main()

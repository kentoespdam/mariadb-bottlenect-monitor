"""run_poll with mock DB — verifies canonical ordering and counter wiring."""

from unittest.mock import MagicMock

from src.counters import KCounter, MCounter, NCounter
from src.poll import run_poll
from src.state import StateToggle


class FakeConfig:
    threads_entry = 40
    threads_exit = 20
    N = 5
    M = 10
    K = 3
    J = 5


class TestPollIntegration:
    def _make_db(self, threads_running: int | None = 50) -> MagicMock:
        db = MagicMock()
        if threads_running is None:
            db.query_one.side_effect = Exception("connection dead")
        else:
            db.query_one.return_value = ("Threads_running", str(threads_running))
        return db

    def test_phase_one_above_entry_increments_n(self) -> None:
        db = self._make_db(50)
        cfg = FakeConfig()
        n = NCounter(cfg.N)
        k = KCounter(cfg.K)
        s = StateToggle("bottleneck")
        result = run_poll(db, cfg, n, k, s, MCounter(cfg.M))
        assert result.phase_one_ok
        assert result.threads_running == 50
        assert n.value == 1
        assert k.value == 0
        assert s.is_set is True

    def test_phase_one_below_entry_resets_n(self) -> None:
        db = self._make_db(10)
        cfg = FakeConfig()
        n = NCounter(cfg.N)
        n.increment()
        n.increment()
        assert n.value == 2
        k = KCounter(cfg.K)
        s = StateToggle("bottleneck")
        s.set(True)
        result = run_poll(db, cfg, n, k, s, MCounter(cfg.M))
        assert result.phase_one_ok
        assert result.threads_running == 10
        assert n.value == 0
        assert k.value == 0
        assert s.is_set is False

    def test_hysteresis_zone_no_change(self) -> None:
        db = self._make_db(30)
        cfg = FakeConfig()
        n = NCounter(cfg.N)
        n.increment()
        n.increment()
        k = KCounter(cfg.K)
        s = StateToggle("bottleneck")
        s.set(True)
        result = run_poll(db, cfg, n, k, s, MCounter(cfg.M))
        assert result.phase_one_ok
        assert n.value == 2
        assert s.is_set is True
        assert result.blocker is None

    def test_phase_one_failure_freezes_n_and_increments_k(self) -> None:
        db = self._make_db(None)
        cfg = FakeConfig()
        n = NCounter(cfg.N)
        n.increment()
        k = KCounter(cfg.K)
        s = StateToggle("bottleneck")
        s.set(True)
        result = run_poll(db, cfg, n, k, s, MCounter(cfg.M))
        assert not result.phase_one_ok
        assert n.value == 1
        assert k.value == 1
        assert s.is_set is True

    def test_phase_two_runs_only_above_entry(self) -> None:
        db = self._make_db(50)
        db.query.return_value = [(123, "user1", "host1", "2025-01-01", "SELECT 1", 5)]
        cfg = FakeConfig()
        n = NCounter(cfg.N)
        k = KCounter(cfg.K)
        s = StateToggle("bottleneck")
        result = run_poll(db, cfg, n, k, s, MCounter(cfg.M))
        assert result.phase_one_ok
        assert result.phase_two_ok is True
        assert result.blocker is not None
        assert result.blocker["thread_id"] == 123

    def test_phase_two_not_run_below_entry(self) -> None:
        db = self._make_db(10)
        cfg = FakeConfig()
        n = NCounter(cfg.N)
        k = KCounter(cfg.K)
        s = StateToggle("bottleneck")
        result = run_poll(db, cfg, n, k, s, MCounter(cfg.M))
        assert result.phase_one_ok
        assert result.phase_two_ok is None
        assert result.blocker is None

    def test_m_ticks_even_when_blind(self) -> None:
        # M is temporal: it must advance on a blind poll too (Heal Cooldown).
        cfg = FakeConfig()
        m = MCounter(cfg.M)
        run_poll(self._make_db(50), cfg, NCounter(cfg.N), KCounter(cfg.K), StateToggle("b"), m)
        run_poll(self._make_db(None), cfg, NCounter(cfg.N), KCounter(cfg.K), StateToggle("b"), m)
        assert m.value == 2

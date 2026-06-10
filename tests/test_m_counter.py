"""MCounter: heal cooldown counter, temporal, never freezes."""

from src.counters import MCounter


class TestMCounter:
    def test_tick(self) -> None:
        m = MCounter(5)
        m.tick()
        assert m.value == 1

    def test_satisfied_at_threshold(self) -> None:
        m = MCounter(2)
        m.tick()
        m.tick()
        assert m.satisfied

    def test_no_freeze_method(self) -> None:
        m = MCounter(5)
        assert not hasattr(m, "freeze")

    def test_reset(self) -> None:
        m = MCounter(5)
        m.tick()
        m.tick()
        m.reset()
        assert m.value == 0

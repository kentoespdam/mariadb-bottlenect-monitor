"""KCounter: blindness counter, never freezes."""

from src.counters import KCounter


class TestKCounter:
    def test_increment(self) -> None:
        k = KCounter(3)
        k.increment()
        assert k.value == 1

    def test_no_freeze_method(self) -> None:
        k = KCounter(3)
        assert not hasattr(k, "freeze")

    def test_satisfied_at_threshold(self) -> None:
        k = KCounter(2)
        k.increment()
        k.increment()
        assert k.satisfied

    def test_reset(self) -> None:
        k = KCounter(3)
        k.increment()
        k.increment()
        k.reset()
        assert k.value == 0

"""NCounter: freeze-aware sustained bottleneck counter."""

from src.counters import NCounter


class TestNCounter:
    def test_increment(self) -> None:
        n = NCounter(3)
        n.increment()
        assert n.value == 1
        assert not n.satisfied

    def test_satisfied_at_threshold(self) -> None:
        n = NCounter(2)
        n.increment()
        n.increment()
        assert n.satisfied

    def test_freeze_blocks_increment(self) -> None:
        n = NCounter(3)
        n.increment()
        n.freeze()
        n.increment()
        assert n.value == 1

    def test_freeze_blocks_reset(self) -> None:
        n = NCounter(3)
        n.increment()
        n.freeze()
        n.reset()
        assert n.value == 1

    def test_unfreeze_resumes(self) -> None:
        n = NCounter(3)
        n.increment()
        n.increment()
        n.freeze()
        n.increment()
        n.unfreeze()
        n.increment()
        assert n.satisfied

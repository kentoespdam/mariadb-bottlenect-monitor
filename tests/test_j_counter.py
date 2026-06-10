"""JCounter: attribution blindness counter, freeze-aware."""

from src.counters import JCounter


class TestJCounter:
    def test_increment(self) -> None:
        j = JCounter(3)
        j.increment()
        assert j.value == 1

    def test_freeze_blocks_increment(self) -> None:
        j = JCounter(3)
        j.increment()
        j.freeze()
        j.increment()
        assert j.value == 1

    def test_freeze_blocks_reset(self) -> None:
        j = JCounter(3)
        j.increment()
        j.freeze()
        j.reset()
        assert j.value == 1

    def test_unfreeze_resumes(self) -> None:
        j = JCounter(3)
        j.increment()
        j.freeze()
        j.unfreeze()
        j.increment()
        assert j.value == 2

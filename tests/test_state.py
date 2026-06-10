"""StateToggle: edge-triggered boolean, freeze blocks transitions."""

from src.counters import evaluate_hysteresis
from src.state import StateToggle


class TestStateToggle:
    def test_begins_false(self) -> None:
        s = StateToggle("test")
        assert not s.is_set

    def test_up_edge(self) -> None:
        events: list[str] = []
        s = StateToggle("test", on_up=lambda: events.append("up"))
        s.set(True)
        assert s.is_set
        assert events == ["up"]

    def test_down_edge(self) -> None:
        events: list[str] = []
        s = StateToggle("test", on_up=lambda: events.append("up"), on_down=lambda: events.append("down"))
        s.set(True)
        s.set(False)
        assert not s.is_set
        assert events == ["up", "down"]

    def test_no_fire_on_no_change(self) -> None:
        events: list[str] = []
        s = StateToggle("test", on_up=lambda: events.append("up"))
        s.set(True)
        s.set(True)
        assert events == ["up"]

    def test_freeze_blocks_transition(self) -> None:
        events: list[str] = []
        s = StateToggle("test", on_up=lambda: events.append("up"))
        s.freeze()
        s.set(True)
        assert not s.is_set
        assert events == []

    def test_force_bypasses_callback(self) -> None:
        events: list[str] = []
        s = StateToggle("test", on_up=lambda: events.append("up"))
        s.force(True)
        assert s.is_set
        assert events == []

    def test_double_freeze_unfreeze(self) -> None:
        events: list[str] = []
        s = StateToggle("test", on_up=lambda: events.append("up"))
        s.freeze()
        s.freeze()
        s.unfreeze()
        s.set(True)
        assert s.is_set
        assert events == ["up"]

    def test_hysteresis_entry(self) -> None:
        assert evaluate_hysteresis(50, 40, 20) is True

    def test_hysteresis_exit(self) -> None:
        assert evaluate_hysteresis(15, 40, 20) is False

    def test_hysteresis_zone(self) -> None:
        assert evaluate_hysteresis(30, 40, 20) is None

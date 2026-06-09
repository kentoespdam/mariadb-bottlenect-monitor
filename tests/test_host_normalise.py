"""Test _normalise_host."""
from src.auto_heal import _normalise_host


class TestNormaliseHost:
    def test_strips_port(self) -> None:
        assert _normalise_host("host1:3307") == "host1"

    def test_no_port_unchanged(self) -> None:
        assert _normalise_host("host1") == "host1"

    def test_empty_string(self) -> None:
        assert _normalise_host("") == ""

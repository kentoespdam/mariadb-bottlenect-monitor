"""Test _matches_exclusion."""
from src.auto_heal import _matches_exclusion


class TestMatchesExclusion:
    def test_exact_match(self) -> None:
        assert _matches_exclusion("app", "host1", ("app@host1",))

    def test_wildcard_host(self) -> None:
        assert _matches_exclusion("app", "anyhost", ("app@%",))

    def test_no_match(self) -> None:
        assert not _matches_exclusion("app", "host1", ("other@host1",))

    def test_no_at_symbol(self) -> None:
        assert not _matches_exclusion("app", "host1", ("noatsymbol",))

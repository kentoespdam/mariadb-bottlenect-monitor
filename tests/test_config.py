"""Test config: env helpers, config validation, load_config."""

from __future__ import annotations

import os

from src._env import _env_bool, _env_csv, _env_float, _env_int, _env_str


class TestEnvInt:
    def test_valid(self) -> None:
        os.environ["TEST_INT"] = "42"
        assert _env_int("TEST_INT") == 42

    def test_invalid_exits(self, monkeypatch) -> None:  # noqa: ANN001
        os.environ["TEST_INT"] = "not_a_number"
        with monkeypatch.context() as mp:
            _exits: list[str] = []
            mp.setattr("sys.exit", lambda s: _exits.append(str(s)))
            _env_int("TEST_INT")
            assert any("must be an integer" in e for e in _exits)

    def test_missing_required_exits(self, monkeypatch) -> None:  # noqa: ANN001
        os.environ.pop("TEST_MISSING", None)
        with monkeypatch.context() as mp:
            _exits: list[str] = []
            mp.setattr("sys.exit", lambda s: _exits.append(str(s)))
            _env_int("TEST_MISSING")
            assert any("Required config missing" in e for e in _exits)

    def test_default_fallback(self) -> None:
        os.environ.pop("TEST_DEFAULT", None)
        assert _env_int("TEST_DEFAULT", 99) == 99


class TestEnvFloat:
    def test_valid(self) -> None:
        os.environ["TEST_FLOAT"] = "1.5"
        assert _env_float("TEST_FLOAT") == 1.5

    def test_default(self) -> None:
        os.environ.pop("TEST_FLOAT_DEF", None)
        assert _env_float("TEST_FLOAT_DEF", 1.0) == 1.0


class TestEnvBool:
    def test_true_values(self) -> None:
        for v in ("1", "true", "yes"):
            os.environ["TEST_BOOL"] = v
            assert _env_bool("TEST_BOOL") is True

    def test_false_values(self) -> None:
        for v in ("0", "false", "no", ""):
            os.environ["TEST_BOOL"] = v
            assert _env_bool("TEST_BOOL") is False

    def test_default(self) -> None:
        os.environ.pop("TEST_BOOL_DEF", None)
        assert _env_bool("TEST_BOOL_DEF") is False


class TestEnvStr:
    def test_value(self) -> None:
        os.environ["TEST_STR"] = "hello"
        assert _env_str("TEST_STR") == "hello"

    def test_default(self) -> None:
        os.environ.pop("TEST_STR_DEF", None)
        assert _env_str("TEST_STR_DEF", "fallback") == "fallback"


class TestEnvCsv:
    def test_multiple_values(self) -> None:
        os.environ["TEST_CSV"] = "a, b, c"
        assert _env_csv("TEST_CSV") == ("a", "b", "c")

    def test_empty(self) -> None:
        os.environ.pop("TEST_CSV_EMPTY", None)
        assert _env_csv("TEST_CSV_EMPTY") == ()

    def test_single_value(self) -> None:
        os.environ["TEST_CSV_SINGLE"] = "only"
        assert _env_csv("TEST_CSV_SINGLE") == ("only",)


class TestConfigValidation:
    def test_valid_config(self) -> None:
        from src.config import Config

        cfg = Config(threads_entry=40, threads_exit=20)
        assert cfg.threads_entry == 40
        assert cfg.threads_exit == 20

    def test_hysteresis_exit_gte_entry_exits(self, monkeypatch) -> None:  # noqa: ANN001
        from src.config import Config

        _exits: list[str] = []
        monkeypatch.setattr("sys.exit", lambda s: _exits.append(str(s)))
        Config(threads_entry=20, threads_exit=20)
        assert any("must be strictly less than" in e for e in _exits)

    def test_patience_floor_N_violation_exits(self, monkeypatch) -> None:  # noqa: ANN001 N802
        from src.config import Config

        _exits: list[str] = []
        monkeypatch.setattr("sys.exit", lambda s: _exits.append(str(s)))
        Config(threads_entry=40, threads_exit=20, N=0)
        assert any("N must be >= 1" in e for e in _exits)

    def test_patience_floor_M_violation_exits(self, monkeypatch) -> None:  # noqa: ANN001 N802
        from src.config import Config

        _exits: list[str] = []
        monkeypatch.setattr("sys.exit", lambda s: _exits.append(str(s)))
        Config(threads_entry=40, threads_exit=20, M=0)
        assert any("M must be >= 1" in e for e in _exits)

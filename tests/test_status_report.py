"""Test status_report: fetch_status, format_status_report, _fmt_uptime."""

from unittest.mock import MagicMock

from src.status_report import _fmt_uptime, fetch_status, format_status_report


class TestFetchStatus:
    def _make_db(self, vars_data: dict[str, str]) -> MagicMock:
        db = MagicMock()

        def query_one(sql: str) -> tuple | None:
            for name, val in vars_data.items():
                if name in sql:
                    return (name, val)
            return None

        db.query_one.side_effect = query_one
        return db

    def test_fetch_all_vars(self) -> None:
        data = {
            "Threads_running": "12",
            "Threads_connected": "150",
            "Uptime": "200000",
            "Questions": "1234567",
            "Slow_queries": "5",
            "Innodb_buffer_pool_read_requests": "1000000",
            "Innodb_buffer_pool_reads": "2000",
        }
        db = self._make_db(data)
        result = fetch_status(db)
        assert result["Threads_running"] == 12
        assert result["Uptime"] == 200000
        assert result["Questions"] == 1234567

    def test_fetch_missing_var(self) -> None:
        db = self._make_db({"Threads_running": "5"})
        result = fetch_status(db)
        assert result["Threads_running"] == 5
        assert "Uptime" not in result


class TestFmtUptime:
    def test_days_hours_minutes(self) -> None:
        # 2d 5h 30m = 2*86400 + 5*3600 + 30*60 = 192600
        assert _fmt_uptime(192600) == "2d 5h 30m"

    def test_hours_minutes_only(self) -> None:
        # 3h 15m = 11700
        assert _fmt_uptime(11700) == "3h 15m"

    def test_minutes_only(self) -> None:
        assert _fmt_uptime(300) == "5m"

    def test_zero(self) -> None:
        assert _fmt_uptime(0) == "0m"

    def test_one_day(self) -> None:
        assert _fmt_uptime(86400) == "1d 0m"


class TestFormatStatusReport:
    def test_report_contains_sections(self) -> None:
        data = {
            "Threads_running": 12,
            "Threads_connected": 150,
            "Uptime": 200000,
            "Questions": 1234567,
            "Slow_queries": 5,
            "Innodb_buffer_pool_read_requests": 1000000,
            "Innodb_buffer_pool_reads": 2000,
        }
        report = format_status_report(data)
        assert "STATUS LAPORAN" in report
        assert "Threads: 12 running / 150 connected" in report
        assert "Slow queries: 5" in report
        assert "1,234,567" in report

    def test_qps_calculation(self) -> None:
        data = {
            "Threads_running": 1,
            "Threads_connected": 10,
            "Uptime": 100,
            "Questions": 1000,
            "Slow_queries": 0,
            "Innodb_buffer_pool_read_requests": 10000,
            "Innodb_buffer_pool_reads": 100,
        }
        report = format_status_report(data)
        assert "QPS: ~10.0" in report

    def test_buffer_pool_hit_rate(self) -> None:
        data = {
            "Threads_running": 1,
            "Threads_connected": 10,
            "Uptime": 100,
            "Questions": 100,
            "Slow_queries": 0,
            "Innodb_buffer_pool_read_requests": 1000,
            "Innodb_buffer_pool_reads": 10,
        }
        report = format_status_report(data)
        assert "99.0% hit rate" in report

    def test_zero_uptime_no_crash(self) -> None:
        data = {
            "Threads_running": 0,
            "Threads_connected": 0,
            "Uptime": 0,
            "Questions": 0,
            "Slow_queries": 0,
            "Innodb_buffer_pool_read_requests": 0,
            "Innodb_buffer_pool_reads": 0,
        }
        report = format_status_report(data)
        assert "QPS: ~0.0" in report
        assert "100.0% hit rate" in report

    def test_empty_data(self) -> None:
        report = format_status_report({})
        assert "STATUS LAPORAN" in report
        assert "Threads: 0 running / 0 connected" in report

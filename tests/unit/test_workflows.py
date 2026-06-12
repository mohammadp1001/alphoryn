"""Unit tests for workflows — momentum, mean_reversion, sector_rotation."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

# ── helpers ───────────────────────────────────────────────────────────────────


def _connect_to(db_path):
    @contextmanager
    def _connect(path=None):
        conn = sqlite3.connect(str(path or db_path), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    return _connect


def _fake_ohlcv(symbol="XLK", n=60):
    bars = [
        {
            "timestamp": f"2025-01-{i + 1:02d}T00:00:00",
            "open": 100.0 + i,
            "high": 102.0 + i,
            "low": 99.0 + i,
            "close": 101.0 + i,
            "volume": 1_000_000.0,
        }
        for i in range(n)
    ]
    return {"symbol": symbol, "timeframe": "1Day", "bars": bars}


def _fake_rsi():
    return {
        "symbol": "XLK",
        "period": 14,
        "current": 55.0,
        "values": [55.0] * 14,
        "is_overbought": False,
        "is_oversold": False,
    }


def _fake_macd():
    return {
        "symbol": "XLK",
        "macd_line": [0.1] * 30,
        "signal_line": [0.05] * 30,
        "histogram": [0.05] * 30,
        "current_macd": 0.1,
        "current_signal": 0.05,
        "current_histogram": 0.05,
    }


def _fake_momentum():
    return {
        "symbol": "XLK",
        "momentum_score": 0.65,
        "rsi_contribution": 0.2,
        "macd_contribution": 0.15,
        "price_vs_sma_contribution": 0.2,
        "volume_trend_contribution": 0.1,
        "raw_rsi": 55.0,
        "raw_macd_histogram": 0.05,
    }


def _fake_crossover():
    return {
        "symbol": "XLK",
        "crossover_type": "bullish",
        "bars_since_crossover": 2,
        "strength": 0.7,
    }


def _fake_tech_score():
    return {
        "symbol": "XLK",
        "composite_score": 0.6,
        "rsi_score": 0.5,
        "macd_score": 0.6,
        "bollinger_score": 0.7,
        "strategy": "MOMENTUM",
    }


def _fake_52w():
    return {
        "symbol": "XLK",
        "high_52w": 200.0,
        "low_52w": 140.0,
        "current_price": 160.0,
        "pct_from_high": -20.0,
        "pct_from_low": 14.3,
    }


def _fake_bollinger():
    return {
        "symbol": "XLK",
        "period": 20,
        "current_upper": 170.0,
        "current_middle": 160.0,
        "current_lower": 150.0,
        "current_price": 162.0,
        "pct_b": 0.6,
        "bandwidth": 0.125,
    }


def _fake_atr():
    return {"symbol": "XLK", "period": 14, "current": 2.5, "values": [2.5] * 14}


def _fake_support_resistance():
    return {
        "symbol": "XLK",
        "levels": [{"price": 155.0, "level_type": "support", "strength": 0.8}],
        "nearest_support": 155.0,
        "nearest_resistance": 170.0,
    }


def _fake_etf_metrics():
    return {
        "symbol": "XLK",
        "aum_usd": 50_000_000_000.0,
        "expense_ratio": 0.0010,
        "nav": 160.0,
        "shares_outstanding": 312_000_000.0,
    }


def _fake_fund_flows():
    return {"symbol": "XLK", "flow_direction": "inflow", "estimated_flow_usd": 200_000_000.0}


def _fake_sector_perf():
    return {
        "timeframe": "1mo",
        "returns": [{"symbol": "XLK", "sector": "Technology", "return_pct": 3.5}],
    }


def _fake_beta():
    return {"symbol": "XLK", "benchmark": "SPY", "beta": 1.2, "r_squared": 0.92, "period_days": 60}


# ── write_analysis_report ─────────────────────────────────────────────────────


def test_write_analysis_report_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_path / "test.db"))
    from db.schema import init_db

    init_db()

    import workflows.base as wb

    monkeypatch.setattr(wb, "register_session_file", lambda **kw: "fake-id")

    with patch("workflows.base.Path", wraps=Path) as _p:
        _ = _p  # keep unused import happy
        result = wb.write_analysis_report("sess-1", "XLK", "MOMENTUM", "# Test\n")

    assert result.endswith(".md")
    assert Path(result).exists()


def test_write_analysis_report_returns_str(tmp_path, monkeypatch):
    import workflows.base as wb

    monkeypatch.setattr(wb, "register_session_file", lambda **kw: "fake-id")
    path = wb.write_analysis_report("sess-2", "SPY", "MEAN_REVERSION", "content")
    assert isinstance(path, str)
    assert "SPY" in path
    assert "MEAN_REVERSION" in path


def test_write_analysis_report_registers_in_db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_path / "db2.db"))
    from db.schema import init_db

    init_db()

    import workflows.base as wb

    calls = []

    def _fake_register(**kw):
        calls.append(kw)
        return "fake-id"

    monkeypatch.setattr(wb, "register_session_file", _fake_register)
    wb.write_analysis_report("sess-3", "XLK", "SECTOR_ROTATION", "# Report")
    assert len(calls) == 1
    assert calls[0]["session_id"] == "sess-3"
    assert calls[0]["symbol"] == "XLK"
    assert calls[0]["file_type"] == "analysis"


# ── run_momentum_analysis ─────────────────────────────────────────────────────


def test_run_momentum_analysis_returns_dict(tmp_path, monkeypatch):
    import workflows.base as wb

    monkeypatch.setattr(wb, "register_session_file", lambda **kw: "id")

    with (
        patch("tools.market.tools.get_ohlcv", new=AsyncMock(return_value=_fake_ohlcv())),
        patch("tools.analysis.tools.compute_rsi", new=AsyncMock(return_value=_fake_rsi())),
        patch("tools.analysis.tools.compute_macd", new=AsyncMock(return_value=_fake_macd())),
        patch(
            "tools.analysis.tools.detect_crossover",
            new=AsyncMock(return_value=_fake_crossover()),
        ),
        patch(
            "tools.analysis.tools.detect_momentum",
            new=AsyncMock(return_value=_fake_momentum()),
        ),
        patch(
            "tools.analysis.tools.score_technical",
            new=AsyncMock(return_value=_fake_tech_score()),
        ),
        patch("tools.market.tools.get_52w_range", new=AsyncMock(return_value=_fake_52w())),
    ):
        from workflows.momentum import run_momentum_analysis

        result = asyncio.run(run_momentum_analysis("sess-mom", "XLK"))

    assert result["symbol"] == "XLK"
    assert result["strategy"] == "MOMENTUM"
    assert "report_path" in result
    assert result["report_path"].endswith(".md")


def test_run_momentum_analysis_writes_file(tmp_path, monkeypatch):
    import workflows.base as wb

    monkeypatch.setattr(wb, "register_session_file", lambda **kw: "id")

    with (
        patch("tools.market.tools.get_ohlcv", new=AsyncMock(return_value=_fake_ohlcv())),
        patch("tools.analysis.tools.compute_rsi", new=AsyncMock(return_value=_fake_rsi())),
        patch("tools.analysis.tools.compute_macd", new=AsyncMock(return_value=_fake_macd())),
        patch(
            "tools.analysis.tools.detect_crossover",
            new=AsyncMock(return_value=_fake_crossover()),
        ),
        patch(
            "tools.analysis.tools.detect_momentum",
            new=AsyncMock(return_value=_fake_momentum()),
        ),
        patch(
            "tools.analysis.tools.score_technical",
            new=AsyncMock(return_value=_fake_tech_score()),
        ),
        patch("tools.market.tools.get_52w_range", new=AsyncMock(return_value=_fake_52w())),
    ):
        from workflows.momentum import run_momentum_analysis

        result = asyncio.run(run_momentum_analysis("sess-mom2", "XLK"))

    assert Path(result["report_path"]).exists()
    content = Path(result["report_path"]).read_text()
    assert "XLK" in content


def test_run_momentum_analysis_insufficient_data(tmp_path, monkeypatch):
    import workflows.base as wb

    monkeypatch.setattr(wb, "register_session_file", lambda **kw: "id")
    short_ohlcv = _fake_ohlcv(n=5)  # fewer than 26 bars

    with patch("tools.market.tools.get_ohlcv", new=AsyncMock(return_value=short_ohlcv)):
        from workflows.momentum import run_momentum_analysis

        result = asyncio.run(run_momentum_analysis("sess-short", "XLK"))

    assert result["strategy"] == "MOMENTUM"
    content = Path(result["report_path"]).read_text()
    assert "Insufficient" in content


# ── run_mean_reversion_analysis ───────────────────────────────────────────────


def test_run_mean_reversion_analysis_returns_dict(tmp_path, monkeypatch):
    import workflows.base as wb

    monkeypatch.setattr(wb, "register_session_file", lambda **kw: "id")

    with (
        patch("tools.market.tools.get_ohlcv", new=AsyncMock(return_value=_fake_ohlcv())),
        patch(
            "tools.analysis.tools.compute_bollinger",
            new=AsyncMock(return_value=_fake_bollinger()),
        ),
        patch("tools.analysis.tools.compute_atr", new=AsyncMock(return_value=_fake_atr())),
        patch(
            "tools.analysis.tools.detect_support_resistance",
            new=AsyncMock(return_value=_fake_support_resistance()),
        ),
        patch(
            "tools.analysis.tools.score_technical",
            new=AsyncMock(return_value=_fake_tech_score()),
        ),
    ):
        from workflows.mean_reversion import run_mean_reversion_analysis

        result = asyncio.run(run_mean_reversion_analysis("sess-mr", "XLK"))

    assert result["symbol"] == "XLK"
    assert result["strategy"] == "MEAN_REVERSION"
    assert "report_path" in result


def test_run_mean_reversion_analysis_insufficient_data(tmp_path, monkeypatch):
    import workflows.base as wb

    monkeypatch.setattr(wb, "register_session_file", lambda **kw: "id")
    short_ohlcv = _fake_ohlcv(n=5)

    with patch("tools.market.tools.get_ohlcv", new=AsyncMock(return_value=short_ohlcv)):
        from workflows.mean_reversion import run_mean_reversion_analysis

        result = asyncio.run(run_mean_reversion_analysis("sess-short-mr", "XLK"))

    assert result["strategy"] == "MEAN_REVERSION"
    content = Path(result["report_path"]).read_text()
    assert "Insufficient" in content


# ── run_sector_rotation_analysis ──────────────────────────────────────────────


def test_run_sector_rotation_analysis_returns_dict(tmp_path, monkeypatch):
    import workflows.base as wb

    monkeypatch.setattr(wb, "register_session_file", lambda **kw: "id")

    with (
        patch("tools.market.tools.get_ohlcv", new=AsyncMock(return_value=_fake_ohlcv())),
        patch(
            "tools.research.tools.get_etf_metrics",
            new=AsyncMock(return_value=_fake_etf_metrics()),
        ),
        patch(
            "tools.research.tools.get_fund_flows",
            new=AsyncMock(return_value=_fake_fund_flows()),
        ),
        patch(
            "tools.research.tools.get_sector_performance",
            new=AsyncMock(return_value=_fake_sector_perf()),
        ),
        patch("tools.analysis.tools.compute_beta", new=AsyncMock(return_value=_fake_beta())),
    ):
        from workflows.sector_rotation import run_sector_rotation_analysis

        result = asyncio.run(run_sector_rotation_analysis("sess-sr", "XLK"))

    assert result["symbol"] == "XLK"
    assert result["strategy"] == "SECTOR_ROTATION"
    assert "report_path" in result


def test_run_sector_rotation_analysis_short_closes_skips_beta(tmp_path, monkeypatch):
    """With fewer than 20 closes, beta is skipped — no error."""
    import workflows.base as wb

    monkeypatch.setattr(wb, "register_session_file", lambda **kw: "id")
    short_ohlcv = _fake_ohlcv(n=5)

    with (
        patch("tools.market.tools.get_ohlcv", new=AsyncMock(return_value=short_ohlcv)),
        patch(
            "tools.research.tools.get_etf_metrics",
            new=AsyncMock(return_value=_fake_etf_metrics()),
        ),
        patch(
            "tools.research.tools.get_fund_flows",
            new=AsyncMock(return_value=_fake_fund_flows()),
        ),
        patch(
            "tools.research.tools.get_sector_performance",
            new=AsyncMock(return_value=_fake_sector_perf()),
        ),
    ):
        from workflows.sector_rotation import run_sector_rotation_analysis

        result = asyncio.run(run_sector_rotation_analysis("sess-sr-short", "XLK"))

    assert result["strategy"] == "SECTOR_ROTATION"


# ── registry — WORKFLOW_TOOLS ─────────────────────────────────────────────────


def test_workflow_tools_list_populated():
    from tools.registry import WORKFLOW_TOOLS

    assert len(WORKFLOW_TOOLS) == 3


def test_workflow_tools_have_workflow_prefix():
    from tools.registry import WORKFLOW_TOOLS

    for t in WORKFLOW_TOOLS:
        assert t.name.startswith("workflow__"), f"unexpected name: {t.name}"


def test_all_coordinator_tools_includes_workflow_tools():
    from tools.registry import ALL_COORDINATOR_TOOLS, WORKFLOW_TOOLS

    names = {t.name for t in ALL_COORDINATOR_TOOLS}
    for wt in WORKFLOW_TOOLS:
        assert wt.name in names

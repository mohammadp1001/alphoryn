"""Unit tests for alphoryn/reports/generator.py (T023 scope).

Tests are written BEFORE the implementation (TDD). They verify:
- Mean reversion template renders <section id="investment-thesis">
- Momentum template renders trailing stop watermark field
- Output path format: reports/run-{run_id}/session-{seq}.html
- Context object matches contracts/report-context.md
- Both templates guarantee <section id="investment-thesis"> exists
"""

from pathlib import Path

from alphoryn.reports.generator import ReportGenerator

# ---------------------------------------------------------------------------
# Fixture context objects (per contracts/report-context.md)
# ---------------------------------------------------------------------------

_MEAN_REVERSION_CONTEXT = {
    "session_id": "run-1/session-abc",
    "candle_close_at": "2026-07-05 14:00 UTC",
    "etf": "SPY",
    "strategy": "MEAN_REVERSION",
    "decision": "BUY",
    "reasoning": "RSI below 30, price below lower Bollinger Band — reversion likely.",
    "signals": {
        "rsi_14": 28.5,
        "adx_14": 18.0,
        "ema_20": 542.0,
        "ema_50": 538.0,
        "sma_20": 541.0,
        "bollinger_upper": 555.0,
        "bollinger_lower": 527.0,
        "bollinger_pct_b": 0.07,
        "macd_line": -0.3,
        "macd_signal": -0.1,
        "macd_histogram": -0.2,
        "volume_vs_avg": 1.4,
        "current_price": 528.5,
        "price_vs_ema_20_pct": -2.5,
        "price_vs_sma_20_pct": -2.3,
    },
    "execution_result": "EXECUTED",
    "position": {
        "entry_price": 528.5,
        "lot_size": 10,
        "stop_loss_price": 518.0,
        "exit_target": {"type": "price_level", "value": 542.0},
        "trailing_stop_high_watermark": None,
    },
    "memory_summary": None,
}

_MOMENTUM_CONTEXT = {
    "session_id": "run-1/session-def",
    "candle_close_at": "2026-07-05 15:00 UTC",
    "etf": "QQQ",
    "strategy": "MOMENTUM",
    "decision": "BUY",
    "reasoning": "Strong ADX, price above EMA-20, volume surge — momentum confirmed.",
    "signals": {
        "rsi_14": 62.0,
        "adx_14": 30.0,
        "ema_20": 448.0,
        "ema_50": 440.0,
        "sma_20": 447.0,
        "bollinger_upper": 460.0,
        "bollinger_lower": 434.0,
        "bollinger_pct_b": 0.65,
        "macd_line": 0.8,
        "macd_signal": 0.5,
        "macd_histogram": 0.3,
        "volume_vs_avg": 1.8,
        "current_price": 452.0,
        "price_vs_ema_20_pct": 0.89,
        "price_vs_sma_20_pct": 1.12,
    },
    "execution_result": "EXECUTED",
    "position": {
        "entry_price": 452.0,
        "lot_size": 8,
        "stop_loss_price": 443.0,
        "exit_target": {"type": "trailing_stop", "trail_pct": 0.015},
        "trailing_stop_high_watermark": 452.0,
    },
    "memory_summary": "Prior MOMENTUM BUY on QQQ returned +2.3% in 5 sessions.",
}

_HOLD_CONTEXT = {
    **_MEAN_REVERSION_CONTEXT,
    "decision": "HOLD",
    "execution_result": None,
    "position": None,
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _generator(tmp_path: Path) -> ReportGenerator:
    return ReportGenerator(output_dir=str(tmp_path / "reports"))


# ---------------------------------------------------------------------------
# Mean reversion template
# ---------------------------------------------------------------------------


def test_mean_reversion_renders_investment_thesis_section(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-abc", _MEAN_REVERSION_CONTEXT)
    assert '<section id="investment-thesis">' in html


def test_mean_reversion_contains_strategy_name(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-abc", _MEAN_REVERSION_CONTEXT)
    assert "MEAN_REVERSION" in html


def test_mean_reversion_contains_etf_ticker(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-abc", _MEAN_REVERSION_CONTEXT)
    assert "SPY" in html


def test_mean_reversion_contains_reasoning(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-abc", _MEAN_REVERSION_CONTEXT)
    assert "RSI below 30" in html


# ---------------------------------------------------------------------------
# Momentum template
# ---------------------------------------------------------------------------


def test_momentum_renders_investment_thesis_section(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-def", _MOMENTUM_CONTEXT)
    assert '<section id="investment-thesis">' in html


def test_momentum_contains_trailing_stop_watermark(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-def", _MOMENTUM_CONTEXT)
    assert "trailing_stop_high_watermark" in html or "watermark" in html.lower()


def test_momentum_contains_strategy_name(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-def", _MOMENTUM_CONTEXT)
    assert "MOMENTUM" in html


# ---------------------------------------------------------------------------
# HOLD decision — thesis still present
# ---------------------------------------------------------------------------


def test_hold_decision_still_has_investment_thesis_section(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-abc", _HOLD_CONTEXT)
    assert '<section id="investment-thesis">' in html


# ---------------------------------------------------------------------------
# Output path format
# ---------------------------------------------------------------------------


def test_write_report_creates_file_at_correct_path(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    path = gen.write("run-1", "session-abc", _MEAN_REVERSION_CONTEXT)
    expected = tmp_path / "reports" / "run-1" / "session-abc.html"
    assert Path(path) == expected
    assert expected.exists()


def test_write_report_path_format_run_2(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    path = gen.write("run-2", "session-xyz", _MOMENTUM_CONTEXT)
    assert "run-2" in path
    assert "session-xyz.html" in path


def test_write_report_creates_parent_directories(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    path = gen.write("run-42", "session-new", _MEAN_REVERSION_CONTEXT)
    assert Path(path).exists()


# ---------------------------------------------------------------------------
# Context validation
# ---------------------------------------------------------------------------


def test_render_with_memory_summary(tmp_path: Path) -> None:
    ctx = {**_MEAN_REVERSION_CONTEXT, "memory_summary": "Prior BUY CORRECT."}
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-abc", ctx)
    assert "Prior BUY CORRECT" in html


def test_render_with_no_position(tmp_path: Path) -> None:
    """HOLD decision renders without a position block."""
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-hold", _HOLD_CONTEXT)
    assert html  # just verify it renders without error

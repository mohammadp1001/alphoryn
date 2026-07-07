"""Unit tests for alphoryn/reports/generator.py (T023 scope).

Tests verify:
- session.html.j2 template renders <section id="investment-thesis">
- Momentum position renders trailing stop watermark field
- Output path format: reports/run-{run_id}/session-{seq}.html
- Context object contains tickers list and ticker_details list
- Position and signals sections are conditional
"""

from pathlib import Path

from alphoryn.reports.generator import ReportGenerator

# ---------------------------------------------------------------------------
# Fixture context objects
# ---------------------------------------------------------------------------

_MEAN_REVERSION_CONTEXT = {
    "session_id": "run-1/session-abc",
    "candle_close_at": "2026-07-05 14:00 UTC",
    "tickers": ["SPY"],
    "ticker_details": [
        {
            "ticker": "SPY",
            "action": "BUY",
            "strategy": "MEAN_REVERSION",
            "reasoning": "RSI below 30, price below lower Bollinger Band — reversion likely.",
            "memory_summary": None,
        }
    ],
    "strategy": "MEAN_REVERSION",
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
}

_MOMENTUM_CONTEXT = {
    "session_id": "run-1/session-def",
    "candle_close_at": "2026-07-05 15:00 UTC",
    "tickers": ["QQQ"],
    "ticker_details": [
        {
            "ticker": "QQQ",
            "action": "BUY",
            "strategy": "MOMENTUM",
            "reasoning": "Strong ADX, price above EMA-20, volume surge — momentum confirmed.",
            "memory_summary": "Prior MOMENTUM BUY on QQQ returned +2.3% in 5 sessions.",
        }
    ],
    "strategy": "MOMENTUM",
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
}

_HOLD_CONTEXT = {
    **_MEAN_REVERSION_CONTEXT,
    "ticker_details": [
        {
            **_MEAN_REVERSION_CONTEXT["ticker_details"][0],
            "action": "HOLD",
        }
    ],
    "execution_result": None,
    "position": None,
}

_MULTI_TICKER_CONTEXT = {
    "session_id": "run-1/session-multi",
    "candle_close_at": "2026-07-05 16:00 UTC",
    "tickers": ["SPY", "QQQ"],
    "ticker_details": [
        {
            "ticker": "SPY",
            "action": "HOLD",
            "strategy": "MEAN_REVERSION",
            "reasoning": "Entry conditions not met.",
            "memory_summary": None,
        },
        {
            "ticker": "QQQ",
            "action": "BUY",
            "strategy": "MOMENTUM",
            "reasoning": "Strong trend confirmed.",
            "memory_summary": None,
        },
    ],
    "strategy": "MEAN_REVERSION",
    "signals": None,
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
    assert "watermark" in html.lower()


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
# Multi-ticker context
# ---------------------------------------------------------------------------


def test_multi_ticker_shows_all_tickers_in_title(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-multi", _MULTI_TICKER_CONTEXT)
    assert "SPY" in html
    assert "QQQ" in html


def test_multi_ticker_shows_decisions_section(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-multi", _MULTI_TICKER_CONTEXT)
    assert '<section id="decisions">' in html


def test_multi_ticker_shows_both_reasonings(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-multi", _MULTI_TICKER_CONTEXT)
    assert "Entry conditions not met" in html
    assert "Strong trend confirmed" in html


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
    ctx = {
        **_MEAN_REVERSION_CONTEXT,
        "ticker_details": [
            {**_MEAN_REVERSION_CONTEXT["ticker_details"][0], "memory_summary": "Prior BUY CORRECT."}
        ],
    }
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-abc", ctx)
    assert "Prior BUY CORRECT" in html


def test_render_with_no_position(tmp_path: Path) -> None:
    gen = _generator(tmp_path)
    html = gen.render("run-1", "session-hold", _HOLD_CONTEXT)
    assert html

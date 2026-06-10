"""
Tool registry — wraps all 60 async functions as ADK FunctionTools.

Import the namespace sets to assign to each agent:
    MARKET_TOOLS   → analysis_agent
    ANALYSIS_TOOLS → analysis_agent
    RESEARCH_TOOLS → research_agent
    EXECUTION_TOOLS → execution_agent
    MEMORY_TOOLS   → coordinator
    COORDINATOR_TOOLS → coordinator
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from google.adk.tools import FunctionTool  # type: ignore[import]

from infra.tool_logger import log_io


def _tool(fn: Callable[..., Any]) -> FunctionTool:
    """Wrap fn with I/O logging then register as a FunctionTool."""
    return FunctionTool(func=log_io(fn))

# ── market.* ─────────────────────────────────────────────────────────────────
from tools.market.tools import (
    get_ohlcv,
    get_quote,
    get_spread,
    get_order_book,
    screen_etfs,
    get_etf_holdings,
    get_sector_map,
    get_52w_range,
    get_volume_profile,
    get_benchmark_return,
    get_intraday_bars,
    get_market_status,
)

# ── analysis.* ───────────────────────────────────────────────────────────────
from tools.analysis.tools import (
    compute_rsi,
    compute_macd,
    compute_bollinger,
    compute_atr,
    compute_beta,
    detect_momentum,
    detect_crossover,
    detect_support_resistance,
    rank_by_momentum,
    run_backtest,
    calc_sharpe,
    calc_max_drawdown,
    calc_correlation,
    score_technical,
)

# ── research.* ───────────────────────────────────────────────────────────────
from tools.research.tools import (
    get_news,
    get_sentiment,
    get_earnings_calendar,
    get_macro_data,
    get_fund_flows,
    get_etf_metrics,
    compare_etfs,
    get_expense_ratios,
    get_sector_performance,
    get_dividend_history,
    get_economic_calendar,
    detect_market_regime,
    get_analyst_ratings,
)

# ── execution.* ──────────────────────────────────────────────────────────────
from tools.execution.tools import (
    get_portfolio,
    get_position,
    place_market_order,
    place_limit_order,
    cancel_order,
    get_order_status,
    get_account_status,
)

# ── memory.* ─────────────────────────────────────────────────────────────────
from tools.memory.tools import (
    write_trade,
    resolve_trade,
    get_calibration,
    get_session_cycles,
    get_unresolved_trades,
    record_cycle,
)

# ── coordinator.* ────────────────────────────────────────────────────────────
from tools.coordinator.tools import (
    request_hitl,
    check_loss_limit,
    select_shortlist,
    synthesise_risk,
    resolve_unresolved_trades,
    update_plan_state,
    get_session_summary,
    abort_cycle,
)

# ── Wrapped FunctionTools ─────────────────────────────────────────────────────

MARKET_TOOLS: list[FunctionTool] = [
    _tool(get_ohlcv),
    _tool(get_quote),
    _tool(get_spread),
    _tool(get_order_book),
    _tool(screen_etfs),
    _tool(get_etf_holdings),
    _tool(get_sector_map),
    _tool(get_52w_range),
    _tool(get_volume_profile),
    _tool(get_benchmark_return),
    _tool(get_intraday_bars),
    _tool(get_market_status),
]

ANALYSIS_TOOLS: list[FunctionTool] = [
    _tool(compute_rsi),
    _tool(compute_macd),
    _tool(compute_bollinger),
    _tool(compute_atr),
    _tool(compute_beta),
    _tool(detect_momentum),
    _tool(detect_crossover),
    _tool(detect_support_resistance),
    _tool(rank_by_momentum),
    _tool(run_backtest),
    _tool(calc_sharpe),
    _tool(calc_max_drawdown),
    _tool(calc_correlation),
    _tool(score_technical),
]

RESEARCH_TOOLS: list[FunctionTool] = [
    _tool(get_news),
    _tool(get_sentiment),
    _tool(get_earnings_calendar),
    _tool(get_macro_data),
    _tool(get_fund_flows),
    _tool(get_etf_metrics),
    _tool(compare_etfs),
    _tool(get_expense_ratios),
    _tool(get_sector_performance),
    _tool(get_dividend_history),
    _tool(get_economic_calendar),
    _tool(detect_market_regime),
    _tool(get_analyst_ratings),
]

EXECUTION_TOOLS: list[FunctionTool] = [
    _tool(get_portfolio),
    _tool(get_position),
    _tool(place_market_order),
    _tool(place_limit_order),
    _tool(cancel_order),
    _tool(get_order_status),
    _tool(get_account_status),
]

MEMORY_TOOLS: list[FunctionTool] = [
    _tool(write_trade),
    _tool(resolve_trade),
    _tool(get_calibration),
    _tool(get_session_cycles),
    _tool(get_unresolved_trades),
    _tool(record_cycle),
]

COORDINATOR_TOOLS: list[FunctionTool] = [
    _tool(request_hitl),
    _tool(check_loss_limit),
    _tool(select_shortlist),
    _tool(synthesise_risk),
    _tool(resolve_unresolved_trades),
    _tool(update_plan_state),
    _tool(get_session_summary),
    _tool(abort_cycle),
]

# Convenience: all coordinator-scope tools (memory + coordinator)
ALL_COORDINATOR_TOOLS = MEMORY_TOOLS + COORDINATOR_TOOLS

"""
Tool registry — wraps all tool functions as ADK FunctionTools with namespace prefixes.

Tool names follow the convention  {namespace}__{function_name}  so the coordinator
LLM can filter by namespace prefix before reading full descriptions.

Namespace slices:
    MARKET_TOOLS      → market__*      (price, volume, market data)
    ANALYSIS_TOOLS    → analysis__*    (technical indicators, ranking)
    RESEARCH_TOOLS    → research__*    (macro, sentiment, regime)
    EXECUTION_TOOLS   → execution__*   (orders, portfolio — execution BaseAgent only)
    MEMORY_TOOLS      → memory__*      (DB reads/writes)
    COORDINATOR_TOOLS → coordinator__* (session control, HITL, risk synthesis)
    STRATEGY_TOOLS    → strategy__*    (strategy files + describe_tool meta-tool)

ALL_COORDINATOR_TOOLS = all slices EXCEPT EXECUTION_TOOLS (coordinator never sees order tools).
EXECUTION_TOOLS is kept separate; only the execution BaseAgent receives it.
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from google.adk.tools import FunctionTool  # type: ignore[import]

from infra.tool_logger import log_io


def _tool(fn: Callable[..., Any], namespace: str) -> FunctionTool:
    """Wrap fn with I/O logging, rename to {namespace}__{fn.__name__}, register as FunctionTool."""
    wrapped = log_io(fn)
    # Preserve the original name for logging but expose namespace-prefixed name to the LLM
    namespaced_name = f"{namespace}__{fn.__name__}"
    # functools.wraps copies __name__; override it after wrapping
    wrapped.__name__ = namespaced_name
    wrapped.__qualname__ = namespaced_name
    return FunctionTool(func=wrapped)


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

# ── strategy.* ───────────────────────────────────────────────────────────────
from tools.strategy.tools import (
    list_strategies,
    get_strategy,
    describe_tool,
)

# ── Wrapped FunctionTools ─────────────────────────────────────────────────────

MARKET_TOOLS: list[FunctionTool] = [
    _tool(get_ohlcv, "market"),
    _tool(get_quote, "market"),
    _tool(get_spread, "market"),
    _tool(get_order_book, "market"),
    _tool(screen_etfs, "market"),
    _tool(get_etf_holdings, "market"),
    _tool(get_sector_map, "market"),
    _tool(get_52w_range, "market"),
    _tool(get_volume_profile, "market"),
    _tool(get_benchmark_return, "market"),
    _tool(get_intraday_bars, "market"),
    _tool(get_market_status, "market"),
]

ANALYSIS_TOOLS: list[FunctionTool] = [
    _tool(compute_rsi, "analysis"),
    _tool(compute_macd, "analysis"),
    _tool(compute_bollinger, "analysis"),
    _tool(compute_atr, "analysis"),
    _tool(compute_beta, "analysis"),
    _tool(detect_momentum, "analysis"),
    _tool(detect_crossover, "analysis"),
    _tool(detect_support_resistance, "analysis"),
    _tool(rank_by_momentum, "analysis"),
    _tool(run_backtest, "analysis"),
    _tool(calc_sharpe, "analysis"),
    _tool(calc_max_drawdown, "analysis"),
    _tool(calc_correlation, "analysis"),
    _tool(score_technical, "analysis"),
]

RESEARCH_TOOLS: list[FunctionTool] = [
    _tool(get_news, "research"),
    _tool(get_sentiment, "research"),
    _tool(get_earnings_calendar, "research"),
    _tool(get_macro_data, "research"),
    _tool(get_fund_flows, "research"),
    _tool(get_etf_metrics, "research"),
    _tool(compare_etfs, "research"),
    _tool(get_expense_ratios, "research"),
    _tool(get_sector_performance, "research"),
    _tool(get_dividend_history, "research"),
    _tool(get_economic_calendar, "research"),
    _tool(detect_market_regime, "research"),
    _tool(get_analyst_ratings, "research"),
]

# Execution tools — ONLY assigned to the execution BaseAgent, never the coordinator
EXECUTION_TOOLS: list[FunctionTool] = [
    _tool(get_portfolio, "execution"),
    _tool(get_position, "execution"),
    _tool(place_market_order, "execution"),
    _tool(place_limit_order, "execution"),
    _tool(cancel_order, "execution"),
    _tool(get_order_status, "execution"),
    _tool(get_account_status, "execution"),
]

MEMORY_TOOLS: list[FunctionTool] = [
    _tool(write_trade, "memory"),
    _tool(resolve_trade, "memory"),
    _tool(get_calibration, "memory"),
    _tool(get_session_cycles, "memory"),
    _tool(get_unresolved_trades, "memory"),
    _tool(record_cycle, "memory"),
]

COORDINATOR_TOOLS: list[FunctionTool] = [
    _tool(request_hitl, "coordinator"),
    _tool(check_loss_limit, "coordinator"),
    _tool(select_shortlist, "coordinator"),
    _tool(synthesise_risk, "coordinator"),
    _tool(resolve_unresolved_trades, "coordinator"),
    _tool(update_plan_state, "coordinator"),
    _tool(get_session_summary, "coordinator"),
    _tool(abort_cycle, "coordinator"),
]

STRATEGY_TOOLS: list[FunctionTool] = [
    _tool(list_strategies, "strategy"),
    _tool(get_strategy, "strategy"),
    _tool(describe_tool, "strategy"),
]

# All tools the coordinator LLM sees — execution tools deliberately excluded
ALL_COORDINATOR_TOOLS: list[FunctionTool] = (
    MARKET_TOOLS
    + ANALYSIS_TOOLS
    + RESEARCH_TOOLS
    + MEMORY_TOOLS
    + COORDINATOR_TOOLS
    + STRATEGY_TOOLS
)

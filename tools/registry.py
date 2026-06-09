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

from google.adk.tools import FunctionTool  # type: ignore[import]

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
    FunctionTool(func=get_ohlcv),
    FunctionTool(func=get_quote),
    FunctionTool(func=get_spread),
    FunctionTool(func=get_order_book),
    FunctionTool(func=screen_etfs),
    FunctionTool(func=get_etf_holdings),
    FunctionTool(func=get_sector_map),
    FunctionTool(func=get_52w_range),
    FunctionTool(func=get_volume_profile),
    FunctionTool(func=get_benchmark_return),
    FunctionTool(func=get_intraday_bars),
    FunctionTool(func=get_market_status),
]

ANALYSIS_TOOLS: list[FunctionTool] = [
    FunctionTool(func=compute_rsi),
    FunctionTool(func=compute_macd),
    FunctionTool(func=compute_bollinger),
    FunctionTool(func=compute_atr),
    FunctionTool(func=compute_beta),
    FunctionTool(func=detect_momentum),
    FunctionTool(func=detect_crossover),
    FunctionTool(func=detect_support_resistance),
    FunctionTool(func=rank_by_momentum),
    FunctionTool(func=run_backtest),
    FunctionTool(func=calc_sharpe),
    FunctionTool(func=calc_max_drawdown),
    FunctionTool(func=calc_correlation),
    FunctionTool(func=score_technical),
]

RESEARCH_TOOLS: list[FunctionTool] = [
    FunctionTool(func=get_news),
    FunctionTool(func=get_sentiment),
    FunctionTool(func=get_earnings_calendar),
    FunctionTool(func=get_macro_data),
    FunctionTool(func=get_fund_flows),
    FunctionTool(func=get_etf_metrics),
    FunctionTool(func=compare_etfs),
    FunctionTool(func=get_expense_ratios),
    FunctionTool(func=get_sector_performance),
    FunctionTool(func=get_dividend_history),
    FunctionTool(func=get_economic_calendar),
    FunctionTool(func=detect_market_regime),
    FunctionTool(func=get_analyst_ratings),
]

EXECUTION_TOOLS: list[FunctionTool] = [
    FunctionTool(func=get_portfolio),
    FunctionTool(func=get_position),
    FunctionTool(func=place_market_order),
    FunctionTool(func=place_limit_order),
    FunctionTool(func=cancel_order),
    FunctionTool(func=get_order_status),
    FunctionTool(func=get_account_status),
]

MEMORY_TOOLS: list[FunctionTool] = [
    FunctionTool(func=write_trade),
    FunctionTool(func=resolve_trade),
    FunctionTool(func=get_calibration),
    FunctionTool(func=get_session_cycles),
    FunctionTool(func=get_unresolved_trades),
    FunctionTool(func=record_cycle),
]

COORDINATOR_TOOLS: list[FunctionTool] = [
    FunctionTool(func=request_hitl),
    FunctionTool(func=check_loss_limit),
    FunctionTool(func=select_shortlist),
    FunctionTool(func=synthesise_risk),
    FunctionTool(func=resolve_unresolved_trades),
    FunctionTool(func=update_plan_state),
    FunctionTool(func=get_session_summary),
    FunctionTool(func=abort_cycle),
]

# Convenience: all coordinator-scope tools (memory + coordinator)
ALL_COORDINATOR_TOOLS = MEMORY_TOOLS + COORDINATOR_TOOLS

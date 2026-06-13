"""
Tool registry — wraps all tool functions as ADK FunctionTools with namespace prefixes.

Tool names follow the convention  {namespace}__{function_name}  so the coordinator
LLM can filter by namespace prefix before reading full descriptions.

Namespace slices:
    ANALYSIS_TOOLS    → analysis__*    (technical indicators, ranking)
    EXECUTION_TOOLS   → execution__*   (orders, portfolio — execution BaseAgent only)
    MEMORY_TOOLS      → memory__*      (DB reads/writes)
    COORDINATOR_TOOLS → coordinator__* (session control, HITL, risk synthesis, regime)
    STRATEGY_TOOLS    → strategy__*    (strategy files + describe_tool meta-tool)
    FILE_TOOLS        → file__*        (read_file, write_file, register_session_file)
    WORKFLOW_TOOLS    → workflow__*    (run_momentum_analysis, run_mean_reversion_analysis,
                                        run_sector_rotation_analysis)

ALL_COORDINATOR_TOOLS = all slices EXCEPT EXECUTION_TOOLS (coordinator never sees order tools).
EXECUTION_TOOLS is kept separate; only the execution BaseAgent receives it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from google.adk.tools import FunctionTool  # type: ignore[import]

from infra.tool_logger import log_io
from tools.analysis.tools import (
    calc_correlation,
    calc_max_drawdown,
    calc_sharpe,
    compute_atr,
    compute_beta,
    compute_bollinger,
    compute_macd,
    compute_rsi,
    detect_crossover,
    detect_momentum,
    detect_support_resistance,
    rank_by_momentum,
    run_backtest,
    score_technical,
)

# ── coordinator.* ────────────────────────────────────────────────────────────
from tools.coordinator.tools import (
    check_loss_limit,
    get_market_status,
    get_session_summary,
    request_hitl,
    resolve_unresolved_trades,
    synthesise_risk,
    update_plan_state,
)
from tools.coordinator.tools import (
    detect_market_regime as coordinator_detect_market_regime,
)

# ── execution.* ──────────────────────────────────────────────────────────────
from tools.execution.tools import (
    cancel_order,
    get_account_status,
    get_order_status,
    get_portfolio,
    get_position,
    place_limit_order,
    place_market_order,
)
from tools.file_tools import read_file, register_session_file, write_file

# ── memory.* ─────────────────────────────────────────────────────────────────
from tools.memory.tools import (
    get_calibration,
    get_session_cycles,
    get_session_files,
    get_unresolved_trades,
    record_cycle,
    resolve_trade,
    write_trade,
)

# ── strategy.* ───────────────────────────────────────────────────────────────
from tools.strategy.tools import (
    describe_tool,
    get_strategy,
    list_strategies,
)

# ── workflows.* ──────────────────────────────────────────────────────────────
from workflows.mean_reversion import run_mean_reversion_analysis
from workflows.momentum import run_momentum_analysis
from workflows.sector_rotation import run_sector_rotation_analysis


def _tool(fn: Callable[..., Any], namespace: str) -> FunctionTool:
    """Wrap fn with I/O logging, rename to {namespace}__{fn.__name__}, register as FunctionTool."""
    wrapped = log_io(fn)
    # Preserve the original name for logging but expose namespace-prefixed name to the LLM
    namespaced_name = f"{namespace}__{fn.__name__}"
    # functools.wraps copies __name__; override it after wrapping
    wrapped.__name__ = namespaced_name
    wrapped.__qualname__ = namespaced_name
    return FunctionTool(func=wrapped)


# ── Wrapped FunctionTools ─────────────────────────────────────────────────────

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
    _tool(get_session_files, "memory"),
    _tool(get_unresolved_trades, "memory"),
    _tool(record_cycle, "memory"),
]

FILE_TOOLS: list[FunctionTool] = [
    _tool(read_file, "file"),
    _tool(write_file, "file"),
    _tool(register_session_file, "file"),
]

COORDINATOR_TOOLS: list[FunctionTool] = [
    _tool(request_hitl, "coordinator"),
    _tool(check_loss_limit, "coordinator"),
    _tool(synthesise_risk, "coordinator"),
    _tool(resolve_unresolved_trades, "coordinator"),
    _tool(update_plan_state, "coordinator"),
    _tool(get_session_summary, "coordinator"),
    _tool(coordinator_detect_market_regime, "coordinator"),
    _tool(get_market_status, "coordinator"),
]

STRATEGY_TOOLS: list[FunctionTool] = [
    _tool(list_strategies, "strategy"),
    _tool(get_strategy, "strategy"),
    _tool(describe_tool, "strategy"),
]

WORKFLOW_TOOLS: list[FunctionTool] = [
    _tool(run_momentum_analysis, "workflow"),
    _tool(run_mean_reversion_analysis, "workflow"),
    _tool(run_sector_rotation_analysis, "workflow"),
]

# All tools the coordinator LLM sees — execution, market, and research tool slices
# are excluded. Market data comes via Alpaca MCP; regime detection is a coordinator tool.
ALL_COORDINATOR_TOOLS: list[FunctionTool] = (
    ANALYSIS_TOOLS + MEMORY_TOOLS + COORDINATOR_TOOLS + STRATEGY_TOOLS + FILE_TOOLS + WORKFLOW_TOOLS
)

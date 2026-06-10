"""Unit tests for tools.registry — FunctionTool wrapping and namespace conventions."""
from __future__ import annotations

# ── Import registry ───────────────────────────────────────────────────────────

def test_registry_imports_without_error():
    import tools.registry  # noqa: F401


def test_market_tools_list_populated():
    from tools.registry import MARKET_TOOLS
    assert len(MARKET_TOOLS) == 12


def test_analysis_tools_list_populated():
    from tools.registry import ANALYSIS_TOOLS
    assert len(ANALYSIS_TOOLS) == 14


def test_research_tools_list_populated():
    from tools.registry import RESEARCH_TOOLS
    assert len(RESEARCH_TOOLS) == 13


def test_execution_tools_list_populated():
    from tools.registry import EXECUTION_TOOLS
    assert len(EXECUTION_TOOLS) == 7


def test_memory_tools_list_populated():
    from tools.registry import MEMORY_TOOLS
    assert len(MEMORY_TOOLS) == 6


def test_coordinator_tools_list_populated():
    from tools.registry import COORDINATOR_TOOLS
    assert len(COORDINATOR_TOOLS) == 8


def test_strategy_tools_list_populated():
    from tools.registry import STRATEGY_TOOLS
    assert len(STRATEGY_TOOLS) == 3  # list_strategies, get_strategy, describe_tool


def test_forex_tools_list_populated():
    from tools.registry import FOREX_TOOLS
    assert len(FOREX_TOOLS) == 4  # account, positions, prices, instruments


def test_all_coordinator_tools_excludes_execution():
    from tools.registry import ALL_COORDINATOR_TOOLS, EXECUTION_TOOLS
    exec_names = {t.name for t in EXECUTION_TOOLS}
    coord_names = {t.name for t in ALL_COORDINATOR_TOOLS}
    overlap = exec_names & coord_names
    assert overlap == set(), f"ALL_COORDINATOR_TOOLS must not contain execution tools: {overlap}"


def test_all_coordinator_tools_includes_strategy():
    from tools.registry import ALL_COORDINATOR_TOOLS, STRATEGY_TOOLS
    strat_names = {t.name for t in STRATEGY_TOOLS}
    coord_names = {t.name for t in ALL_COORDINATOR_TOOLS}
    assert strat_names.issubset(coord_names)


def test_all_coordinator_tools_includes_forex():
    from tools.registry import ALL_COORDINATOR_TOOLS, FOREX_TOOLS
    forex_names = {t.name for t in FOREX_TOOLS}
    coord_names = {t.name for t in ALL_COORDINATOR_TOOLS}
    assert forex_names.issubset(coord_names)


# ── Tool type checks ──────────────────────────────────────────────────────────

def test_market_tools_are_function_tools():
    from google.adk.tools import FunctionTool  # type: ignore[import]

    from tools.registry import MARKET_TOOLS
    for tool in MARKET_TOOLS:
        assert isinstance(tool, FunctionTool)


def test_execution_tools_are_function_tools():
    from google.adk.tools import FunctionTool  # type: ignore[import]

    from tools.registry import EXECUTION_TOOLS
    for tool in EXECUTION_TOOLS:
        assert isinstance(tool, FunctionTool)


def test_memory_tools_are_function_tools():
    from google.adk.tools import FunctionTool  # type: ignore[import]

    from tools.registry import MEMORY_TOOLS
    for tool in MEMORY_TOOLS:
        assert isinstance(tool, FunctionTool)


def test_coordinator_tools_are_function_tools():
    from google.adk.tools import FunctionTool  # type: ignore[import]

    from tools.registry import COORDINATOR_TOOLS
    for tool in COORDINATOR_TOOLS:
        assert isinstance(tool, FunctionTool)


# ── Namespace prefix convention ───────────────────────────────────────────────

def test_market_tools_have_market_prefix():
    from tools.registry import MARKET_TOOLS
    for tool in MARKET_TOOLS:
        assert tool.name.startswith("market__"), f"Expected market__ prefix: {tool.name}"


def test_analysis_tools_have_analysis_prefix():
    from tools.registry import ANALYSIS_TOOLS
    for tool in ANALYSIS_TOOLS:
        assert tool.name.startswith("analysis__"), f"Expected analysis__ prefix: {tool.name}"


def test_research_tools_have_research_prefix():
    from tools.registry import RESEARCH_TOOLS
    for tool in RESEARCH_TOOLS:
        assert tool.name.startswith("research__"), f"Expected research__ prefix: {tool.name}"


def test_execution_tools_have_execution_prefix():
    from tools.registry import EXECUTION_TOOLS
    for tool in EXECUTION_TOOLS:
        assert tool.name.startswith("execution__"), f"Expected execution__ prefix: {tool.name}"


def test_memory_tools_have_memory_prefix():
    from tools.registry import MEMORY_TOOLS
    for tool in MEMORY_TOOLS:
        assert tool.name.startswith("memory__"), f"Expected memory__ prefix: {tool.name}"


def test_coordinator_tools_have_coordinator_prefix():
    from tools.registry import COORDINATOR_TOOLS
    for tool in COORDINATOR_TOOLS:
        assert tool.name.startswith("coordinator__"), f"Expected coordinator__ prefix: {tool.name}"


def test_strategy_tools_have_strategy_prefix():
    from tools.registry import STRATEGY_TOOLS
    for tool in STRATEGY_TOOLS:
        assert tool.name.startswith("strategy__"), f"Expected strategy__ prefix: {tool.name}"


def test_forex_tools_have_forex_prefix():
    from tools.registry import FOREX_TOOLS
    for tool in FOREX_TOOLS:
        assert tool.name.startswith("forex__"), f"Expected forex__ prefix: {tool.name}"


# ── Uniqueness ────────────────────────────────────────────────────────────────

def test_all_coordinator_tools_names_are_unique():
    from tools.registry import ALL_COORDINATOR_TOOLS
    names = [t.name for t in ALL_COORDINATOR_TOOLS]
    assert len(names) == len(set(names))


def test_execution_tool_names_are_unique():
    from tools.registry import EXECUTION_TOOLS
    names = [t.name for t in EXECUTION_TOOLS]
    assert len(names) == len(set(names))

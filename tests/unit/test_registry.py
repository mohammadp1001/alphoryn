"""Unit tests for tools.registry — FunctionTool wrapping of all tools."""
from __future__ import annotations

import pytest


# ── Import registry and verify all tool lists ─────────────────────────────────

def test_registry_imports_without_error():
    """tools.registry must import cleanly (all tools importable)."""
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


def test_all_coordinator_tools_is_memory_plus_coordinator():
    from tools.registry import ALL_COORDINATOR_TOOLS, MEMORY_TOOLS, COORDINATOR_TOOLS
    assert len(ALL_COORDINATOR_TOOLS) == len(MEMORY_TOOLS) + len(COORDINATOR_TOOLS)
    assert ALL_COORDINATOR_TOOLS == MEMORY_TOOLS + COORDINATOR_TOOLS


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


def test_market_tool_names_are_unique():
    from tools.registry import MARKET_TOOLS
    names = [t.name for t in MARKET_TOOLS]
    assert len(names) == len(set(names))


def test_execution_tool_names_are_unique():
    from tools.registry import EXECUTION_TOOLS
    names = [t.name for t in EXECUTION_TOOLS]
    assert len(names) == len(set(names))


def test_all_coordinator_tools_names_are_unique():
    from tools.registry import ALL_COORDINATOR_TOOLS
    names = [t.name for t in ALL_COORDINATOR_TOOLS]
    assert len(names) == len(set(names))

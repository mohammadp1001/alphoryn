"""Unit tests for agent/research_agent.py and the research file-write callback."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import patch


class _FakeCallbackCtx:
    def __init__(self, state=None):
        self.state = state if state is not None else {}


# ── create_research_agent — factory ──────────────────────────────────────────


def test_create_research_agent_returns_agent():
    from agent.research_agent import create_research_agent

    agent = create_research_agent("sess-1", "XLK")
    assert agent is not None
    assert agent.name == "research_agent"


def test_create_research_agent_default_model():
    from google.adk.models.lite_llm import LiteLlm  # type: ignore[import]

    from agent.research_agent import _DEFAULT_RESEARCH_MODEL, create_research_agent

    agent = create_research_agent("sess-1", "XLK")
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == _DEFAULT_RESEARCH_MODEL


def test_create_research_agent_custom_model():
    from agent.research_agent import create_research_agent

    agent = create_research_agent("sess-1", "XLK", model="gemini-2.5-flash")
    assert agent.model == "gemini-2.5-flash"


def test_create_research_agent_has_two_tools():
    from agent.research_agent import create_research_agent

    agent = create_research_agent("sess-1", "XLK")
    assert len(agent.tools) == 2


def test_create_research_agent_tools_are_get_news_and_read_file():
    from agent.research_agent import create_research_agent

    agent = create_research_agent("sess-1", "XLK")
    tool_names = {getattr(t, "name", None) or getattr(t.func, "__name__", "") for t in agent.tools}
    assert "get_news" in tool_names
    assert "read_file" in tool_names


def test_create_research_agent_output_key():
    from agent.research_agent import _RESEARCH_OUTPUT_KEY, create_research_agent

    agent = create_research_agent("sess-1", "XLK")
    assert agent.output_key == _RESEARCH_OUTPUT_KEY


# ── make_research_file_callback ───────────────────────────────────────────────


def test_research_file_callback_writes_file():
    from agent.callbacks import make_research_file_callback

    with patch("db.schema.register_session_file", return_value="fake-id"):
        cb = make_research_file_callback("sess-rfc", "SPY", "research_output")
        ctx = _FakeCallbackCtx(
            state={"research_output": "# Research Report — SPY\n## News\nAll good."}
        )
        asyncio.run(cb(ctx))

    written_path = ctx.state.get("research_report_path")
    assert written_path is not None
    assert Path(written_path).exists()
    assert "SPY" in Path(written_path).read_text()


def test_research_file_callback_sets_state_path():
    from agent.callbacks import make_research_file_callback

    with patch("db.schema.register_session_file", return_value="fake-id"):
        cb = make_research_file_callback("sess-path", "XLK", "research_output")
        ctx = _FakeCallbackCtx(state={"research_output": "# Research"})
        asyncio.run(cb(ctx))

    path = ctx.state["research_report_path"]
    assert path.endswith(".md")
    assert "XLK" in path
    assert "sess-path" in path


def test_research_file_callback_registers_in_db():
    from agent.callbacks import make_research_file_callback

    calls = []

    with patch(
        "db.schema.register_session_file",
        side_effect=lambda **kw: calls.append(kw) or "id",
    ):
        cb = make_research_file_callback("sess-db", "EWG", "research_output")
        ctx = _FakeCallbackCtx(state={"research_output": "# Report"})
        asyncio.run(cb(ctx))

    assert len(calls) == 1
    assert calls[0]["session_id"] == "sess-db"
    assert calls[0]["symbol"] == "EWG"
    assert calls[0]["file_type"] == "research"


def test_research_file_callback_empty_output_no_write(caplog):
    from agent.callbacks import make_research_file_callback

    cb = make_research_file_callback("sess-empty", "XLK", "research_output")
    ctx = _FakeCallbackCtx(state={})  # no research_output key

    with caplog.at_level(logging.WARNING, logger="agent.callbacks"):
        asyncio.run(cb(ctx))

    assert "research_report_path" not in ctx.state
    assert any("status=empty" in r.message for r in caplog.records)


def test_create_research_agent_after_callback_writes_file():
    """The agent's after_agent_callback writes a file (exercises lines 47-48)."""
    from agent.research_agent import _RESEARCH_OUTPUT_KEY, create_research_agent

    agent = create_research_agent("sess-chain", "XLK")

    with patch("db.schema.register_session_file", return_value="id"):
        ctx = _FakeCallbackCtx(state={_RESEARCH_OUTPUT_KEY: "# Combined callback test"})
        asyncio.run(agent.after_agent_callback(ctx))

    assert "research_report_path" in ctx.state
    assert Path(ctx.state["research_report_path"]).exists()


def test_research_file_callback_path_under_reports_dir():
    from agent.callbacks import make_research_file_callback

    with patch("db.schema.register_session_file", return_value="fake-id"):
        cb = make_research_file_callback("sess-dir", "XLK", "research_output")
        ctx = _FakeCallbackCtx(state={"research_output": "content"})
        asyncio.run(cb(ctx))

    path_str = ctx.state["research_report_path"]
    assert "research" in path_str
    assert "sess-dir" in path_str
    assert "reports" in path_str


def test_research_file_callback_uses_active_symbol_from_state():
    """active_symbol in state takes priority over the closed-over symbol."""
    from agent.callbacks import make_research_file_callback

    calls = []

    with patch(
        "db.schema.register_session_file",
        side_effect=lambda **kw: calls.append(kw) or "id",
    ):
        # Created with empty symbol (as coordinator does at startup)
        cb = make_research_file_callback("sess-sym", "", "research_output")
        ctx = _FakeCallbackCtx(state={"research_output": "# Report", "active_symbol": "EWG"})
        asyncio.run(cb(ctx))

    path_str = ctx.state["research_report_path"]
    assert "EWG" in path_str
    assert calls[0]["symbol"] == "EWG"

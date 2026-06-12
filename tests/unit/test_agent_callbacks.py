"""Unit tests for agent.callbacks and agent.coordinator._make_before_callback."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

# ── Fake CallbackContext ──────────────────────────────────────────────────────


class _FakeCallbackCtx:
    def __init__(self, state=None, user_content=None):
        self.state = state if state is not None else {}
        self.user_content = user_content


# ── agent/callbacks.py: _serialise ───────────────────────────────────────────


def test_serialise_simple_dict():
    from agent.callbacks import _serialise

    result = _serialise({"key": "value", "num": 42})
    assert '"key"' in result
    assert '"value"' in result


def test_serialise_non_serializable_falls_back_to_repr():
    from agent.callbacks import _serialise

    class Unserializable:
        def __repr__(self):
            return "<Unserializable>"

    result = _serialise(Unserializable())
    assert "<Unserializable>" in result


def test_serialise_long_value_is_truncated():
    from agent.callbacks import _MAX_CHARS, _serialise

    long_dict = {"k": "x" * (_MAX_CHARS * 2)}
    result = _serialise(long_dict)
    assert len(result) <= _MAX_CHARS + len("\n  …(truncated)")
    assert "…(truncated)" in result


def test_serialise_short_value_not_truncated():
    from agent.callbacks import _serialise

    result = _serialise({"k": "v"})
    assert "…(truncated)" not in result


# ── agent/callbacks.py: before_callback ──────────────────────────────────────


def test_before_callback_acquires_gemini_rate_limit():
    from agent.callbacks import make_agent_log_callbacks

    before_cb, _ = make_agent_log_callbacks("research_agent", "market_regime")

    with patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()) as mock_acquire:
        asyncio.run(before_cb(_FakeCallbackCtx()))

    mock_acquire.assert_called()


def test_before_callback_logs_request_text(caplog):
    from agent.callbacks import make_agent_log_callbacks

    before_cb, _ = make_agent_log_callbacks("analysis_agent", "ranked_signals")

    mock_part = MagicMock()
    mock_part.text = "Analyse XLK and SPY"
    mock_content = MagicMock()
    mock_content.parts = [mock_part]
    ctx = _FakeCallbackCtx(user_content=mock_content)

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        caplog.at_level(logging.DEBUG, logger="agent.callbacks"),
    ):
        asyncio.run(before_cb(ctx))

    assert any("analysis_agent" in r.message for r in caplog.records)


def test_before_callback_handles_none_user_content(caplog):
    from agent.callbacks import make_agent_log_callbacks

    before_cb, _ = make_agent_log_callbacks("risk_optimist", "optimist_verdict")

    ctx = _FakeCallbackCtx(user_content=None)

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        caplog.at_level(logging.DEBUG, logger="agent.callbacks"),
    ):
        asyncio.run(before_cb(ctx))  # must not raise


def test_before_callback_handles_parts_with_no_text():
    from agent.callbacks import make_agent_log_callbacks

    before_cb, _ = make_agent_log_callbacks("research_agent", "market_regime")

    mock_part = MagicMock()
    del mock_part.text  # no text attribute
    mock_content = MagicMock()
    mock_content.parts = [mock_part]
    ctx = _FakeCallbackCtx(user_content=mock_content)

    with patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()):
        asyncio.run(before_cb(ctx))  # must not raise


# ── agent/callbacks.py: after_callback ───────────────────────────────────────


def test_after_callback_logs_output_when_present(caplog):
    from agent.callbacks import make_agent_log_callbacks

    _, after_cb = make_agent_log_callbacks("research_agent", "market_regime")

    ctx = _FakeCallbackCtx(state={"market_regime": {"regime": "BULL_TREND", "vix": 15.0}})

    with caplog.at_level(logging.DEBUG, logger="agent.callbacks"):
        asyncio.run(after_cb(ctx))

    assert any("market_regime" in r.message for r in caplog.records)


def test_after_callback_warns_when_output_key_missing(caplog):
    from agent.callbacks import make_agent_log_callbacks

    _, after_cb = make_agent_log_callbacks("analysis_agent", "ranked_signals")

    ctx = _FakeCallbackCtx(state={})  # ranked_signals not in state

    with caplog.at_level(logging.WARNING, logger="agent.callbacks"):
        asyncio.run(after_cb(ctx))

    assert any("EMPTY" in r.message for r in caplog.records)


# ── agent/coordinator.py: _make_before_callback ──────────────────────────────


def _make_params():
    from models.enums import OperatingMode
    from models.session import SessionParams

    return SessionParams(
        mode=OperatingMode.SEMI_AUTO,
        loss_limit_eur=500.0,
        timeframe="1Day",
        shortlist_n=2,
        hitl_timeout_seconds=60,
        hitl_timeout_action="abort",
    )


def _make_plan_state(params=None):
    from models.session import PlanState

    if params is None:
        params = _make_params()
    return PlanState(session_id="test-cb-session", params=params)


def test_coordinator_before_callback_initialises_state():
    from agent.coordinator import _make_before_callback

    params = _make_params()
    plan_state = _make_plan_state(params)
    before_cb = _make_before_callback(params, plan_state)

    ctx = _FakeCallbackCtx(state={})

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch("db.schema.init_db"),
    ):
        asyncio.run(before_cb(ctx))

    assert ctx.state["session_initialised"] is True
    assert ctx.state["cycle_count"] == 0
    assert ctx.state["active_strategy"] == ""


def test_coordinator_before_callback_skips_init_on_second_call():
    from agent.coordinator import _make_before_callback

    params = _make_params()
    plan_state = _make_plan_state(params)
    before_cb = _make_before_callback(params, plan_state)

    ctx = _FakeCallbackCtx(state={"session_initialised": True, "cycle_count": 5})

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch("db.schema.init_db") as mock_init_db,
    ):
        asyncio.run(before_cb(ctx))

    mock_init_db.assert_not_called()
    assert ctx.state["cycle_count"] == 5  # unchanged


def test_coordinator_before_callback_no_alpaca_creds(monkeypatch):
    from agent.coordinator import _make_before_callback

    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)

    params = _make_params()
    plan_state = _make_plan_state(params)
    before_cb = _make_before_callback(params, plan_state)

    ctx = _FakeCallbackCtx(state={})

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch("db.schema.init_db"),
    ):
        asyncio.run(before_cb(ctx))

    # Defaults set when no credentials
    assert ctx.state.get("account_snapshot") == {}
    assert ctx.state.get("portfolio_snapshot") == {"positions": [], "position_count": 0}


def test_coordinator_before_callback_with_alpaca_success(monkeypatch):
    from agent.coordinator import _make_before_callback

    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")

    mock_account = MagicMock()
    mock_account.buying_power = "5000.0"
    mock_account.cash = "5000.0"
    mock_account.portfolio_value = "10000.0"
    mock_account.daytrade_count = 0
    mock_account.pattern_day_trader = False
    mock_account.status = MagicMock()
    mock_account.status.__str__ = lambda self: "ACTIVE"

    mock_client = MagicMock()
    mock_client.get_account.return_value = mock_account
    mock_client.get_all_positions.return_value = []

    mock_trading_client_mod = MagicMock(TradingClient=MagicMock(return_value=mock_client))

    params = _make_params()
    plan_state = _make_plan_state(params)
    before_cb = _make_before_callback(params, plan_state)

    ctx = _FakeCallbackCtx(state={})

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch("db.schema.init_db"),
        patch.dict("sys.modules", {"alpaca.trading.client": mock_trading_client_mod}),
    ):
        asyncio.run(before_cb(ctx))

    assert "account_snapshot" in ctx.state
    assert ctx.state["account_snapshot"]["buying_power"] == 5000.0
    assert ctx.state["portfolio_snapshot"]["position_count"] == 0


def test_coordinator_before_callback_alpaca_fetch_exception(monkeypatch):
    from agent.coordinator import _make_before_callback

    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")

    mock_trading_client_mod = MagicMock(
        TradingClient=MagicMock(side_effect=RuntimeError("connection error"))
    )

    params = _make_params()
    plan_state = _make_plan_state(params)
    before_cb = _make_before_callback(params, plan_state)

    ctx = _FakeCallbackCtx(state={})

    with (
        patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()),
        patch("db.schema.init_db"),
        patch.dict("sys.modules", {"alpaca.trading.client": mock_trading_client_mod}),
    ):
        asyncio.run(before_cb(ctx))  # must not raise

    # Defaults set on exception
    assert ctx.state.get("account_snapshot") == {}


# ── _serialise exception branch ───────────────────────────────────────────────


def test_serialise_str_raises_falls_back_to_repr():
    """Lines 20-21: when json.dumps(default=str) fails because str() raises, repr() is used."""
    from agent.callbacks import _serialise

    class StrRaises:
        def __str__(self):
            raise ValueError("no str for you")

        def __repr__(self):
            return "StrRaises()"

    result = _serialise(StrRaises())
    assert "StrRaises()" in result


# ── before_callback user_content attribute raises ─────────────────────────────


def test_before_callback_user_content_raises_is_swallowed():
    """Lines 45-46: accessing user_content raises → exception is swallowed, logged as unavailable."""
    from agent.callbacks import make_agent_log_callbacks

    class _RaisingCtx:
        state = {}

        @property
        def user_content(self):
            raise AttributeError("ADK internal error")

    before_cb, _ = make_agent_log_callbacks("research_agent", "market_regime")
    ctx = _RaisingCtx()

    with patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock()):
        asyncio.run(before_cb(ctx))  # must not raise

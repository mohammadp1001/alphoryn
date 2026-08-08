"""Unit tests for alphoryn/execution/agent.py (T022 scope).

Tests verify:
- BUY decision → ORDER_PLACED + Position written to memory bank
- HOLD decision → no order placed
- Budget exceeded → no order placed, no position written
- Existing OPEN position on same ticker blocks new BUY (FR-014)
- Zero LLM model calls — constitution Principle I
"""

import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import sqlalchemy.orm as orm
from alpaca.trading.enums import OrderSide

from alphoryn.execution.agent import (
    EVALUATION_WINDOW_SESSIONS,
    AssetDecision,
    ExecutionAgent,
    SessionDecision,
)
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import Position
from alphoryn.memory.schema import Session as Sess
from alphoryn.monitor.monitor import PositionMonitor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _buy(ticker: str = "SPY", strategy: str = "MOMENTUM", lot: int = 10) -> AssetDecision:
    return AssetDecision(
        ticker=ticker,
        action="BUY",
        strategy=strategy,
        lot_size=lot,
        exit_target={"type": "trailing_stop", "trail_pct": 0.015},
        reasoning="RSI oversold",
    )


def _hold(ticker: str = "SPY", strategy: str = "MOMENTUM") -> AssetDecision:
    return AssetDecision(
        ticker=ticker,
        action="HOLD",
        strategy=strategy,
        lot_size=None,
        exit_target=None,
        reasoning="No clear signal",
    )


def _decision(*asset_decisions: AssetDecision) -> SessionDecision:
    return SessionDecision(session_id="run-1/session-abc", decisions=list(asset_decisions))


def _make_agent(bank: MemoryBank) -> ExecutionAgent:
    """Create an ExecutionAgent with a stubbed Alpaca account API."""
    return ExecutionAgent(bank=bank)


# ---------------------------------------------------------------------------
# HOLD path
# ---------------------------------------------------------------------------


def test_hold_decision_no_order_placed(tmp_path) -> None:
    bank = MemoryBank(str(tmp_path / "memory.db"))
    agent = _make_agent(bank)
    decision = _decision(_hold("SPY"), _hold("QQQ"))
    mock_alpaca = MagicMock()

    with patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca):
        agent.execute(decision)

    mock_alpaca.submit_order.assert_not_called()


def test_hold_decision_no_position_written(tmp_path) -> None:
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY","QQQ"]}', 6)
    agent = _make_agent(bank)
    decision = _decision(_hold("SPY"), _hold("QQQ"))

    with patch("alphoryn.execution.agent.TradingClient", return_value=MagicMock()):
        agent.execute(decision)

    assert bank.load_open_positions() == []


# ---------------------------------------------------------------------------
# BUY path — success
# ---------------------------------------------------------------------------


def test_buy_decision_places_market_order(tmp_path) -> None:
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY","QQQ"]}', 6)
    agent = _make_agent(bank)
    decision = _decision(_buy("SPY", lot=5), _hold("QQQ"))

    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "10000"
    mock_data = MagicMock()
    mock_data.get_stock_latest_quote.return_value = {"SPY": MagicMock(ask_price=450.0)}

    with patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca), \
         patch("alphoryn.execution.agent.StockHistoricalDataClient", return_value=mock_data):
        agent.execute(decision)

    mock_alpaca.submit_order.assert_called_once()
    order_call = mock_alpaca.submit_order.call_args
    assert order_call is not None


def test_buy_decision_writes_open_position(tmp_path) -> None:
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY","QQQ"]}', 6)
    agent = _make_agent(bank)
    decision = _decision(_buy("SPY", lot=5), _hold("QQQ"))

    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "10000"
    mock_data = MagicMock()
    mock_data.get_stock_latest_quote.return_value = {"SPY": MagicMock(ask_price=450.0)}

    with patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca), \
         patch("alphoryn.execution.agent.StockHistoricalDataClient", return_value=mock_data):
        agent.execute(decision)

    positions = bank.load_open_positions()
    assert len(positions) == 1
    assert positions[0].ticker == "SPY"
    assert positions[0].status == "OPEN"


# ---------------------------------------------------------------------------
# BUY path — budget exceeded
# ---------------------------------------------------------------------------


def test_buy_blocked_by_insufficient_budget(tmp_path) -> None:
    """buying_power < required → no order placed, no position written."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY","QQQ"]}', 6)
    agent = _make_agent(bank)
    decision = _decision(_buy("SPY", lot=1000), _hold("QQQ"))

    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "100"  # way too low
    mock_data = MagicMock()
    # 1000 x 450 = $450k
    mock_data.get_stock_latest_quote.return_value = {"SPY": MagicMock(ask_price=450.0)}

    with patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca), \
         patch("alphoryn.execution.agent.StockHistoricalDataClient", return_value=mock_data):
        agent.execute(decision)

    mock_alpaca.submit_order.assert_not_called()
    assert bank.load_open_positions() == []


# ---------------------------------------------------------------------------
# OPEN position blocking
# ---------------------------------------------------------------------------


def test_existing_open_position_blocks_new_buy(tmp_path) -> None:
    """Open position on SPY → new BUY on SPY is blocked."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 6)

    sess_id = f"run-{run_id}/session-0001"
    with orm.Session(bank._engine) as s:
        s.add(
            Sess(
                id=sess_id,
                run_id=run_id,
                candle_close_at=datetime(2024, 1, 15, 15, 0),
                created_at=datetime(2024, 1, 15, 15, 0),
                status="COMPLETED",
            )
        )
        s.commit()
        s.add(
            Position(
                session_id=sess_id,
                ticker="SPY",
                strategy="MOMENTUM",
                direction="BUY",
                entry_price=450.0,
                entry_time=datetime(2024, 1, 15, 15, 0),
                lot_size=5.0,
                stop_loss_price=441.0,
                exit_target='{"type":"trailing_stop","trail_pct":0.015}',
                evaluation_window_close_at=datetime(2024, 1, 15, 19, 0),
                status="OPEN",
            )
        )
        s.commit()

    agent = _make_agent(bank)
    decision = _decision(_buy("SPY", lot=5), _hold("QQQ"))

    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "100000"
    mock_data = MagicMock()
    mock_data.get_stock_latest_quote.return_value = {"SPY": MagicMock(ask_price=450.0)}

    with patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca), \
         patch("alphoryn.execution.agent.StockHistoricalDataClient", return_value=mock_data):
        agent.execute(decision)

    # No new order placed — blocked by existing OPEN position
    mock_alpaca.submit_order.assert_not_called()
    # Still only one open position
    assert len(bank.load_open_positions()) == 1


def test_open_position_on_ticker1_does_not_block_ticker2(tmp_path) -> None:
    """OPEN position on SPY does not block BUY on QQQ."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 6)

    sess_id = f"run-{run_id}/session-0001"
    with orm.Session(bank._engine) as s:
        s.add(
            Sess(
                id=sess_id,
                run_id=run_id,
                candle_close_at=datetime(2024, 1, 15, 15, 0),
                created_at=datetime(2024, 1, 15, 15, 0),
                status="COMPLETED",
            )
        )
        s.commit()
        s.add(
            Position(
                session_id=sess_id,
                ticker="SPY",
                strategy="MOMENTUM",
                direction="BUY",
                entry_price=450.0,
                entry_time=datetime(2024, 1, 15, 15, 0),
                lot_size=5.0,
                stop_loss_price=441.0,
                exit_target='{"type":"trailing_stop","trail_pct":0.015}',
                evaluation_window_close_at=datetime(2024, 1, 15, 19, 0),
                status="OPEN",
            )
        )
        s.commit()

    agent = _make_agent(bank)
    # SPY blocked, QQQ free to buy
    decision = _decision(_hold("SPY"), _buy("QQQ", lot=3))

    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "100000"
    mock_data = MagicMock()
    mock_data.get_stock_latest_quote.return_value = {"QQQ": MagicMock(ask_price=380.0)}

    with patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca), \
         patch("alphoryn.execution.agent.StockHistoricalDataClient", return_value=mock_data):
        agent.execute(decision)

    # QQQ order was placed
    mock_alpaca.submit_order.assert_called_once()
    positions = bank.load_open_positions()
    tickers = {p.ticker for p in positions}
    assert "QQQ" in tickers


# ---------------------------------------------------------------------------
# Zero LLM model calls — constitution Principle I
# ---------------------------------------------------------------------------


def test_execution_agent_has_no_llm_model() -> None:
    """ExecutionAgent must not have any LLM model configured."""
    bank = MagicMock()
    agent = ExecutionAgent(bank=bank)
    # Google ADK LlmAgent stores the model on self.model. ExecutionAgent must not.
    assert not hasattr(agent, "model") or agent.model is None


# ---------------------------------------------------------------------------
# Evaluation window deadline (issue #122)
# ---------------------------------------------------------------------------


def test_evaluation_window_uses_mean_reversion_horizon() -> None:
    agent = ExecutionAgent(bank=MagicMock(), candle_timeframe="1H")
    entry = datetime(2024, 1, 15, 15, 0, tzinfo=UTC)
    assert agent._evaluation_window_close_at("MEAN_REVERSION", entry) == entry + timedelta(hours=4)


def test_evaluation_window_uses_momentum_horizon() -> None:
    agent = ExecutionAgent(bank=MagicMock(), candle_timeframe="1H")
    entry = datetime(2024, 1, 15, 15, 0, tzinfo=UTC)
    assert agent._evaluation_window_close_at("MOMENTUM", entry) == entry + timedelta(hours=2)


def test_evaluation_window_scales_with_candle_timeframe() -> None:
    agent = ExecutionAgent(bank=MagicMock(), candle_timeframe="30min")
    entry = datetime(2024, 1, 15, 15, 0, tzinfo=UTC)
    assert agent._evaluation_window_close_at("MOMENTUM", entry) == entry + timedelta(hours=1)


def test_evaluation_window_falls_back_when_strategy_is_none() -> None:
    agent = ExecutionAgent(bank=MagicMock(), candle_timeframe="1H")
    entry = datetime(2024, 1, 15, 15, 0, tzinfo=UTC)
    assert agent._evaluation_window_close_at(None, entry) == entry + timedelta(hours=4)


def test_evaluation_window_horizons_match_strategy_docs() -> None:
    assert EVALUATION_WINDOW_SESSIONS == {"MEAN_REVERSION": 4, "MOMENTUM": 2}


def test_buy_writes_derived_window_deadline_not_a_fixed_ordinal(tmp_path) -> None:
    """Regression for #122: the deadline is derived from entry time, not hardcoded."""
    bank = MemoryBank(str(tmp_path / "m.db"))
    run_id = bank.start_run('{"tickers":["SPY"]}', 6)
    sess_id = f"run-{run_id}/session-0001"
    with orm.Session(bank._engine) as s:
        s.add(
            Sess(
                id=sess_id,
                run_id=run_id,
                candle_close_at=datetime(2024, 1, 15, 15, 0),
                created_at=datetime(2024, 1, 15, 15, 0),
                status="COMPLETED",
            )
        )
        s.commit()

    agent = ExecutionAgent(bank=bank, candle_timeframe="1H")
    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "100000"
    mock_data = MagicMock()
    mock_data.get_stock_latest_quote.return_value = {"SPY": MagicMock(ask_price=450.0)}

    with (
        patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca),
        patch("alphoryn.execution.agent.StockHistoricalDataClient", return_value=mock_data),
    ):
        agent.execute(
            SessionDecision(session_id=sess_id, decisions=[_buy("SPY", "MOMENTUM", 1)])
        )

    pos = bank.load_open_positions()[0]
    delta = pos.evaluation_window_close_at - pos.entry_time
    assert delta == timedelta(hours=2)  # MOMENTUM horizon at a 1H candle
    bank._engine.dispose()


# ---------------------------------------------------------------------------
# Feedback-blocking — FR-014 (issue #124)
# ---------------------------------------------------------------------------


def _sell(ticker: str = "SPY", strategy: str = "MOMENTUM", lot: int = 5) -> AssetDecision:
    return AssetDecision(
        ticker=ticker,
        action="SELL",
        strategy=strategy,
        lot_size=lot,
        exit_target=None,
        reasoning="Exit signal",
    )


def _bank_with_position(tmp_path, status: str, ticker: str = "SPY") -> MemoryBank:
    bank = MemoryBank(str(tmp_path / "memory.db"))
    run_id = bank.start_run('{"tickers":["SPY","QQQ"]}', 6)
    sess_id = f"run-{run_id}/session-0001"
    with orm.Session(bank._engine) as s:
        s.add(
            Sess(
                id=sess_id,
                run_id=run_id,
                candle_close_at=datetime(2024, 1, 15, 15, 0),
                created_at=datetime(2024, 1, 15, 15, 0),
                status="COMPLETED",
            )
        )
        s.commit()
        s.add(
            Position(
                session_id=sess_id,
                ticker=ticker,
                strategy="MOMENTUM",
                direction="BUY",
                entry_price=450.0,
                entry_time=datetime(2024, 1, 15, 15, 0),
                lot_size=5.0,
                stop_loss_price=441.0,
                exit_target='{"type":"trailing_stop","trail_pct":0.015}',
                evaluation_window_close_at=datetime(2024, 1, 15, 19, 0),
                status=status,
            )
        )
        s.commit()
    return bank


def _run(agent: ExecutionAgent, decision: SessionDecision) -> MagicMock:
    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "100000"
    mock_data = MagicMock()
    mock_data.get_stock_latest_quote.return_value = {
        "SPY": MagicMock(ask_price=450.0),
        "QQQ": MagicMock(ask_price=380.0),
    }
    with (
        patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca),
        patch("alphoryn.execution.agent.StockHistoricalDataClient", return_value=mock_data),
    ):
        agent.execute(decision)
    return mock_alpaca


def test_closed_but_unevaluated_position_blocks_new_buy(tmp_path) -> None:
    """Regression for #124: the old OPEN-only check let this straight through."""
    bank = _bank_with_position(tmp_path, status="CLOSED_PROFIT_TARGET")
    mock_alpaca = _run(ExecutionAgent(bank, "1H"), _decision(_buy("SPY", lot=5)))
    mock_alpaca.submit_order.assert_not_called()
    bank._engine.dispose()


def test_evaluated_position_does_not_block_new_buy(tmp_path) -> None:
    bank = _bank_with_position(tmp_path, status="EVALUATED")
    mock_alpaca = _run(ExecutionAgent(bank, "1H"), _decision(_buy("SPY", lot=5)))
    mock_alpaca.submit_order.assert_called_once()
    bank._engine.dispose()


def test_sell_is_not_blocked_by_the_position_it_closes(tmp_path) -> None:
    """Regression for #124: SELL used to be blocked by the very position it unwinds."""
    bank = _bank_with_position(tmp_path, status="OPEN")
    mock_alpaca = _run(ExecutionAgent(bank, "1H"), _decision(_sell("SPY", lot=5)))
    mock_alpaca.submit_order.assert_called_once()
    assert mock_alpaca.submit_order.call_args.args[0].side == OrderSide.SELL
    bank._engine.dispose()


def test_buy_on_an_unrelated_ticker_is_unaffected(tmp_path) -> None:
    bank = _bank_with_position(tmp_path, status="OPEN", ticker="SPY")
    mock_alpaca = _run(ExecutionAgent(bank, "1H"), _decision(_buy("QQQ", lot=3)))
    mock_alpaca.submit_order.assert_called_once()
    bank._engine.dispose()


# ---------------------------------------------------------------------------
# SELL closes an existing Buy; it never opens a short (issue #126)
# ---------------------------------------------------------------------------


def test_sell_with_no_open_position_is_rejected(tmp_path) -> None:
    """Regression for #126: this used to submit a sell and open a naked short."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY","QQQ"]}', 6)
    mock_alpaca = _run(ExecutionAgent(bank, "1H"), _decision(_sell("SPY", lot=5)))
    mock_alpaca.submit_order.assert_not_called()
    bank._engine.dispose()


def test_sell_with_no_open_position_writes_nothing(tmp_path) -> None:
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY","QQQ"]}', 6)
    _run(ExecutionAgent(bank, "1H"), _decision(_sell("SPY", lot=5)))
    with orm.Session(bank._engine) as s:
        assert s.query(Position).count() == 0
    bank._engine.dispose()


def test_sell_closes_the_existing_position_in_place(tmp_path) -> None:
    """Regression for #126: this used to write a second Position row."""
    bank = _bank_with_position(tmp_path, status="OPEN")
    _run(ExecutionAgent(bank, "1H"), _decision(_sell("SPY", lot=5)))

    with orm.Session(bank._engine) as s:
        positions = s.query(Position).all()
        assert len(positions) == 1  # closed in place, not duplicated
        assert positions[0].status == "CLOSED_AGENT_EXIT"
        assert positions[0].exit_reason == "AGENT_EXIT"
        assert positions[0].exit_price == 450.0
        assert positions[0].exit_time is not None
    bank._engine.dispose()


def test_sell_leaves_no_open_position_behind(tmp_path) -> None:
    bank = _bank_with_position(tmp_path, status="OPEN")
    _run(ExecutionAgent(bank, "1H"), _decision(_sell("SPY", lot=5)))
    assert bank.load_open_positions() == []
    bank._engine.dispose()


def test_sell_closes_the_full_position_not_the_decision_lot(tmp_path) -> None:
    """A Sell unwinds the whole position, whatever lot the agent suggested."""
    bank = _bank_with_position(tmp_path, status="OPEN")  # lot_size 5.0
    mock_alpaca = _run(ExecutionAgent(bank, "1H"), _decision(_sell("SPY", lot=2)))
    assert mock_alpaca.submit_order.call_args.args[0].qty == 5
    bank._engine.dispose()


def test_sell_does_not_consume_the_budget_check(tmp_path) -> None:
    """Closing never needs buying power, so a flat account must still be able to exit."""
    bank = _bank_with_position(tmp_path, status="OPEN")
    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "0"
    mock_data = MagicMock()
    mock_data.get_stock_latest_quote.return_value = {"SPY": MagicMock(ask_price=450.0)}
    with (
        patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca),
        patch("alphoryn.execution.agent.StockHistoricalDataClient", return_value=mock_data),
    ):
        ExecutionAgent(bank, "1H").execute(_decision(_sell("SPY", lot=5)))

    mock_alpaca.submit_order.assert_called_once()
    bank._engine.dispose()


def test_sell_only_closes_the_matching_ticker(tmp_path) -> None:
    bank = _bank_with_position(tmp_path, status="OPEN", ticker="SPY")
    _run(ExecutionAgent(bank, "1H"), _decision(_sell("QQQ", lot=5)))
    assert [p.ticker for p in bank.load_open_positions()] == ["SPY"]
    bank._engine.dispose()


def test_buy_always_records_direction_buy(tmp_path) -> None:
    """Shorts are out of scope, so direction is BUY by construction."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY","QQQ"]}', 6)
    _run(ExecutionAgent(bank, "1H"), _decision(_buy("SPY", lot=5)))
    assert bank.load_open_positions()[0].direction == "BUY"
    bank._engine.dispose()


# ---------------------------------------------------------------------------
# Telemetry — every order path is observable (issue #132, FR-017 / SC-004)
# ---------------------------------------------------------------------------


def _emitted(logger: MagicMock) -> list[tuple[str, dict]]:
    """Return (event_type, payload) for every emit() call on the stub logger."""
    return [(c.args[0], c.args[2]) for c in logger.emit.call_args_list]


def test_successful_buy_emits_budget_check_and_order_placed(tmp_path) -> None:
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY"]}', 6)
    logger = MagicMock()
    _run(ExecutionAgent(bank, "1H", logger), _decision(_buy("SPY", lot=5)))

    events = dict(_emitted(logger))
    assert events["BUDGET_CHECK"]["sufficient"] is True
    assert events["BUDGET_CHECK"]["required"] == 450.0 * 5
    assert events["ORDER_PLACED"] == {
        "side": "BUY",
        "qty": 5,
        "price": 450.0,
        "strategy": "MOMENTUM",
    }
    assert logger.emit.call_args.kwargs["etf"] == "SPY"
    assert logger.emit.call_args.kwargs["session_id"] == "run-1/session-abc"
    bank._engine.dispose()


def test_insufficient_budget_emits_order_failed(tmp_path) -> None:
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY"]}', 6)
    logger = MagicMock()
    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "10"
    mock_data = MagicMock()
    mock_data.get_stock_latest_quote.return_value = {"SPY": MagicMock(ask_price=450.0)}
    with (
        patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca),
        patch("alphoryn.execution.agent.StockHistoricalDataClient", return_value=mock_data),
    ):
        ExecutionAgent(bank, "1H", logger).execute(_decision(_buy("SPY", lot=5)))

    events = dict(_emitted(logger))
    assert events["BUDGET_CHECK"]["sufficient"] is False
    assert events["ORDER_FAILED"]["reason"] == "INSUFFICIENT_BUDGET"
    mock_alpaca.submit_order.assert_not_called()
    bank._engine.dispose()


def test_feedback_blocked_buy_emits_order_failed(tmp_path) -> None:
    bank = _bank_with_position(tmp_path, status="CLOSED_PROFIT_TARGET")
    logger = MagicMock()
    _run(ExecutionAgent(bank, "1H", logger), _decision(_buy("SPY", lot=5)))

    events = dict(_emitted(logger))
    assert events["ORDER_FAILED"]["reason"] == "FEEDBACK_BLOCKED"
    assert "BUDGET_CHECK" not in events  # refused before the account is queried
    bank._engine.dispose()


def test_sell_with_no_open_position_emits_order_failed(tmp_path) -> None:
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY"]}', 6)
    logger = MagicMock()
    _run(ExecutionAgent(bank, "1H", logger), _decision(_sell("SPY", lot=5)))

    events = dict(_emitted(logger))
    assert events["ORDER_FAILED"] == {"side": "SELL", "reason": "NO_OPEN_POSITION"}
    bank._engine.dispose()


def test_sell_emits_order_placed_for_the_full_position(tmp_path) -> None:
    bank = _bank_with_position(tmp_path, status="OPEN")  # lot_size 5.0
    logger = MagicMock()
    _run(ExecutionAgent(bank, "1H", logger), _decision(_sell("SPY", lot=2)))

    events = dict(_emitted(logger))
    assert events["ORDER_PLACED"]["side"] == "SELL"
    assert events["ORDER_PLACED"]["qty"] == 5  # the position, not the decision lot
    assert events["ORDER_PLACED"]["price"] == 450.0
    bank._engine.dispose()


def test_hold_emits_nothing(tmp_path) -> None:
    bank = MemoryBank(str(tmp_path / "memory.db"))
    logger = MagicMock()
    _run(ExecutionAgent(bank, "1H", logger), _decision(_hold("SPY")))
    logger.emit.assert_not_called()
    bank._engine.dispose()


def test_execution_without_a_logger_still_executes(tmp_path) -> None:
    """The logger is optional; its absence must never change behaviour."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY"]}', 6)
    mock_alpaca = _run(ExecutionAgent(bank, "1H"), _decision(_buy("SPY", lot=5)))
    mock_alpaca.submit_order.assert_called_once()
    bank._engine.dispose()


# ---------------------------------------------------------------------------
# Trailing stop watermark is seeded at entry (issue #130)
# ---------------------------------------------------------------------------


def test_entry_seeds_the_trailing_watermark_with_the_entry_price(tmp_path) -> None:
    """strategies/momentum.md: initialised to entry_price at entry."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY"]}', 6)
    _run(ExecutionAgent(bank, "1H"), _decision(_buy("SPY", lot=5)))

    position = bank.load_open_positions()[0]
    assert position.trailing_stop_high_watermark == position.entry_price == 450.0
    bank._engine.dispose()


def test_a_position_that_gaps_down_keeps_its_entry_price_as_the_trail_floor(tmp_path) -> None:
    """On main the watermark was NULL, so the first (lower) price became the floor."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY"]}', 6)
    _run(ExecutionAgent(bank, "1H"), _decision(_buy("SPY", lot=5)))

    pos = bank.load_open_positions()[0]
    monitor = PositionMonitor(
        bank=bank,
        market_data=MagicMock(get_latest_price=MagicMock(return_value=447.0)),
        logger=MagicMock(),
        stop_event=threading.Event(),
    )
    with patch("alphoryn.monitor.monitor.TradingClient"):
        monitor._check_position(pos)

    # 447 is above the 441 stop-loss and above 450 * (1 - 0.015) = 443.25, so the
    # position survives - and the watermark must not have ratcheted down to 447.
    assert bank.load_open_positions()[0].trailing_stop_high_watermark == 450.0
    bank._engine.dispose()


# ---------------------------------------------------------------------------
# FR-001 & FR-010 Risk Management and Budget Enforcement
# ---------------------------------------------------------------------------


def test_custom_stop_loss_pct_override(tmp_path) -> None:
    """FR-001: ExecutionAgent uses configured stop_loss_pct when writing Position."""
    from alphoryn.config.models import AlphorynConfig

    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY"]}', 6)
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"], stop_loss_pct=0.05)
    agent = ExecutionAgent(bank, "1H", cfg=cfg)

    _run(agent, _decision(_buy("SPY", lot=5)))

    position = bank.load_open_positions()[0]
    # ask_price = 450.0; stop_loss_pct = 0.05 -> stop_loss_price = 450 * 0.95 = 427.5
    assert position.stop_loss_price == 427.5
    bank._engine.dispose()


def test_session_money_budget_rejects_insufficient_funds(tmp_path) -> None:
    """FR-010: order requiring more than session_money_budget fails with INSUFFICIENT_BUDGET."""
    from alphoryn.config.models import AlphorynConfig

    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY"]}', 6)
    # Price is 450.0, lot=5 -> required = 2250.0; session_money_budget = 1000.0
    cfg = AlphorynConfig(tickers=["SPY", "QQQ"], session_money_budget=1000.0)
    agent = ExecutionAgent(bank, "1H", cfg=cfg)

    mock_alpaca = _run(agent, _decision(_buy("SPY", lot=5)))

    mock_alpaca.submit_order.assert_not_called()
    assert bank.load_open_positions() == []
    bank._engine.dispose()


def test_alpaca_api_exception_emits_order_failed_and_returns_failed(tmp_path) -> None:
    """Alpaca API failures emit ORDER_FAILED telemetry and return FAILED status."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"tickers":["SPY"]}', 6)
    logger = MagicMock()
    agent = ExecutionAgent(bank, "1H", logger=logger)

    with (
        patch("alphoryn.execution.agent.TradingClient") as mock_client_cls,
        patch("alphoryn.execution.agent.StockHistoricalDataClient"),
    ):
        mock_client_cls.side_effect = RuntimeError("Alpaca API unavailable")
        results = agent.execute(_decision(_buy("SPY", lot=5)))

    assert results == {"SPY": "FAILED"}
    logger.emit.assert_called_with(
        "ORDER_FAILED",
        "execution_agent",
        {"side": "BUY", "reason": "API_ERROR", "error": "Alpaca API unavailable"},
        session_id="run-1/session-abc",
        etf="SPY",
    )
    bank._engine.dispose()


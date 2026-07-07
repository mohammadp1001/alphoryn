"""Unit tests for alphoryn/execution/agent.py (T022 scope).

Tests verify:
- BUY decision → ORDER_PLACED + Position written to memory bank
- HOLD decision → no order placed
- Budget exceeded → no order placed, no position written
- Existing OPEN position on same ticker blocks new BUY (FR-014)
- Zero LLM model calls — constitution Principle I
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import sqlalchemy.orm as orm

from alphoryn.execution.agent import AssetDecision, ExecutionAgent, SessionDecision
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import Position
from alphoryn.memory.schema import Session as Sess

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
    mock_data.get_stock_latest_quote.return_value = {"SPY": MagicMock(ask_price=450.0)}  # 1000 x 450 = $450k

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
                evaluation_window_session=5,
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
                evaluation_window_session=5,
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

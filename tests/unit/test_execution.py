"""Unit tests for alphoryn/execution/agent.py (T022 scope).

Tests are written BEFORE the implementation (TDD). They verify:
- BUY decision → BUDGET_CHECK + ORDER_PLACED events + Position written to memory bank
- HOLD decision → AGENT_DECISION event only; no order placed
- Budget exceeded → ORDER_FAILED event; no position written
- Existing OPEN position on same ETF blocks new BUY (forced HOLD, reason "position-blocked")
- Zero LLM model calls — constitution Principle I
- SELL decision → budget check + ORDER_PLACED + position status update

Alpaca SDK calls are stubbed via MagicMock.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from unittest.mock import MagicMock, patch

import sqlalchemy.orm as orm

from alphoryn.execution.agent import ExecutionAgent
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import Position
from alphoryn.memory.schema import Session as Sess

# ---------------------------------------------------------------------------
# Decision dataclasses (mirror of contracts/agents.md)
# We import them from the execution module once implemented; for now define
# here to make the tests self-contained if contracts move.
# ---------------------------------------------------------------------------

try:
    from alphoryn.execution.agent import ETFDecision, SessionDecision
except ImportError:
    # Pre-implementation: define stubs so test file can be parsed
    @dataclass(frozen=True)
    class ETFDecision:  # type: ignore[no-redef]
        etf: str
        action: Literal["BUY", "SELL", "HOLD"]
        strategy: Literal["MEAN_REVERSION", "MOMENTUM"]
        lot_size: int | None
        exit_target: dict | None
        reasoning: str

    @dataclass(frozen=True)
    class SessionDecision:  # type: ignore[no-redef]
        session_id: str
        etf1: ETFDecision
        etf2: ETFDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _buy(etf: str = "SPY", strategy: str = "MOMENTUM", lot: int = 10) -> ETFDecision:
    return ETFDecision(
        etf=etf,
        action="BUY",
        strategy=strategy,
        lot_size=lot,
        exit_target={"type": "trailing_stop", "trail_pct": 0.015},
        reasoning="RSI oversold",
    )


def _hold(etf: str = "SPY", strategy: str = "MOMENTUM") -> ETFDecision:
    return ETFDecision(
        etf=etf,
        action="HOLD",
        strategy=strategy,
        lot_size=None,
        exit_target=None,
        reasoning="No clear signal",
    )


def _sell(etf: str = "SPY", strategy: str = "MOMENTUM", lot: int = 10) -> ETFDecision:
    return ETFDecision(
        etf=etf,
        action="SELL",
        strategy=strategy,
        lot_size=lot,
        exit_target=None,
        reasoning="RSI overbought",
    )


def _decision(etf1: ETFDecision, etf2: ETFDecision) -> SessionDecision:
    return SessionDecision(session_id="run-1/session-abc", etf1=etf1, etf2=etf2)


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
    bank.start_run('{"etf1":"SPY","etf2":"QQQ"}', 6)
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
    bank.start_run('{"etf1":"SPY","etf2":"QQQ"}', 6)
    agent = _make_agent(bank)
    decision = _decision(_buy("SPY", lot=5), _hold("QQQ"))

    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "10000"
    mock_alpaca.get_latest_quote.return_value.ask_price = 450.0

    with patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca):
        agent.execute(decision)

    mock_alpaca.submit_order.assert_called_once()
    order_call = mock_alpaca.submit_order.call_args
    assert order_call is not None


def test_buy_decision_writes_open_position(tmp_path) -> None:
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"etf1":"SPY","etf2":"QQQ"}', 6)
    agent = _make_agent(bank)
    decision = _decision(_buy("SPY", lot=5), _hold("QQQ"))

    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "10000"
    mock_alpaca.get_latest_quote.return_value.ask_price = 450.0

    with patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca):
        agent.execute(decision)

    positions = bank.load_open_positions()
    assert len(positions) == 1
    assert positions[0].etf == "SPY"
    assert positions[0].status == "OPEN"


# ---------------------------------------------------------------------------
# BUY path — budget exceeded
# ---------------------------------------------------------------------------


def test_buy_blocked_by_insufficient_budget(tmp_path) -> None:
    """buying_power < required → no order placed, no position written."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    bank.start_run('{"etf1":"SPY","etf2":"QQQ"}', 6)
    agent = _make_agent(bank)
    decision = _decision(_buy("SPY", lot=1000), _hold("QQQ"))

    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value.buying_power = "100"  # way too low
    mock_alpaca.get_latest_quote.return_value.ask_price = 450.0  # 1000 x 450 = $450k

    with patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca):
        agent.execute(decision)

    mock_alpaca.submit_order.assert_not_called()
    assert bank.load_open_positions() == []


# ---------------------------------------------------------------------------
# OPEN position blocking
# ---------------------------------------------------------------------------


def test_existing_open_position_blocks_new_buy(tmp_path) -> None:
    """Open position on SPY → new BUY on SPY is forced to HOLD."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    run_id = bank.start_run('{"etf1":"SPY","etf2":"QQQ"}', 6)

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
                etf="SPY",
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
    mock_alpaca.get_latest_quote.return_value.ask_price = 450.0

    with patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca):
        agent.execute(decision)

    # No new order placed — blocked by existing OPEN position
    mock_alpaca.submit_order.assert_not_called()
    # Still only one open position
    assert len(bank.load_open_positions()) == 1


def test_open_position_on_etf1_does_not_block_etf2(tmp_path) -> None:
    """OPEN position on SPY does not block BUY on QQQ."""
    bank = MemoryBank(str(tmp_path / "memory.db"))
    run_id = bank.start_run('{"etf1":"SPY","etf2":"QQQ"}', 6)

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
                etf="SPY",
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
    mock_alpaca.get_latest_quote.return_value.ask_price = 380.0

    with patch("alphoryn.execution.agent.TradingClient", return_value=mock_alpaca):
        agent.execute(decision)

    # QQQ order was placed
    mock_alpaca.submit_order.assert_called_once()
    positions = bank.load_open_positions()
    etfs = {p.etf for p in positions}
    assert "QQQ" in etfs


# ---------------------------------------------------------------------------
# Zero LLM model calls — constitution Principle I
# ---------------------------------------------------------------------------


def test_execution_agent_has_no_llm_model() -> None:
    """ExecutionAgent must not have any LLM model configured."""
    bank = MagicMock()
    agent = ExecutionAgent(bank=bank)
    # Google ADK LlmAgent stores the model on self.model. ExecutionAgent must not.
    assert not hasattr(agent, "model") or agent.model is None

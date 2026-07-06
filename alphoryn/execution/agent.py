"""Execution agent for Alphoryn.

Deterministic ADK BaseAgent subclass — no LLM model. Receives a
SessionDecision from main_agent and executes orders via alpaca-py.

Constitution Principle I: zero LLM model calls.
"""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import Position


@dataclass(frozen=True)
class ETFDecision:
    """Per-ETF decision produced by main_agent (contracts/agents.md)."""

    etf: str
    action: Literal["BUY", "SELL", "HOLD"]
    strategy: Literal["MEAN_REVERSION", "MOMENTUM"]
    lot_size: int | None
    exit_target: dict | None
    reasoning: str


@dataclass(frozen=True)
class SessionDecision:
    """Full session decision containing one ETFDecision per ETF."""

    session_id: str
    etf1: ETFDecision
    etf2: ETFDecision


class ExecutionAgent:
    """Deterministic order executor — no LLM model configured.

    Processes a SessionDecision sequentially per ETF:
      - HOLD → skip
      - BUY/SELL → budget check → market order → write Position to memory bank
      - Existing OPEN position on same ETF → force HOLD (position-blocked)
    """

    model = None  # Principle I: no LLM model

    def __init__(self, bank: MemoryBank) -> None:
        self._bank = bank

    def execute(self, decision: SessionDecision) -> None:
        """Execute a SessionDecision for both ETFs sequentially."""
        for etf_decision in (decision.etf1, decision.etf2):
            self._execute_etf(etf_decision, decision.session_id)

    def _execute_etf(self, etf_decision: ETFDecision, session_id: str) -> None:
        if etf_decision.action == "HOLD":
            return

        # Block new BUY if ETF already has an OPEN position (FR-014)
        open_positions = self._bank.load_open_positions()
        if any(p.etf == etf_decision.etf for p in open_positions):
            return  # position-blocked → treat as HOLD

        client = TradingClient(
            api_key=os.environ.get("ALPACA_API_KEY", ""),
            secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
            paper=True,
        )

        # Budget check via Alpaca account API
        account = client.get_account()
        buying_power = float(account.buying_power)
        quote = client.get_latest_quote(etf_decision.etf)
        ask_price = float(quote.ask_price)
        lot = etf_decision.lot_size or 1
        required = ask_price * lot
        if buying_power < required:
            return  # ORDER_FAILED — insufficient budget

        # Place market order
        side = OrderSide.BUY if etf_decision.action == "BUY" else OrderSide.SELL
        client.submit_order(
            MarketOrderRequest(
                symbol=etf_decision.etf,
                qty=lot,
                side=side,
                time_in_force=TimeInForce.DAY,
            )
        )

        # Write OPEN Position record to memory bank
        stop_loss_pct = 0.02
        stop_loss_price = ask_price * (1 - stop_loss_pct)
        pos = Position(
            session_id=session_id,
            etf=etf_decision.etf,
            strategy=etf_decision.strategy,
            direction=etf_decision.action,
            entry_price=ask_price,
            entry_time=datetime.now(UTC),
            lot_size=float(lot),
            stop_loss_price=stop_loss_price,
            exit_target=json.dumps(etf_decision.exit_target) if etf_decision.exit_target else "{}",
            evaluation_window_session=5,
            status="OPEN",
        )
        self._bank.write_position(pos)

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

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import Position


@dataclass(frozen=True)
class AssetDecision:
    """Per-ticker decision produced by main_agent (contracts/agents.md)."""

    ticker: str
    action: Literal["BUY", "SELL", "HOLD"]
    strategy: Literal["MEAN_REVERSION", "MOMENTUM"] | None
    lot_size: int | None
    exit_target: dict | None
    reasoning: str


@dataclass(frozen=True)
class SessionDecision:
    """Full session decision containing one AssetDecision per ticker."""

    session_id: str
    decisions: list[AssetDecision]


class ExecutionAgent:
    """Deterministic order executor — no LLM model configured.

    Processes a SessionDecision sequentially per ticker:
      - HOLD → skip
      - BUY/SELL → budget check → market order → write Position to memory bank
      - Existing OPEN position on same ticker → force HOLD (position-blocked)
    """

    model = None  # Principle I: no LLM model

    def __init__(self, bank: MemoryBank) -> None:
        self._bank = bank

    def execute(self, decision: SessionDecision) -> None:
        """Execute a SessionDecision for all tickers sequentially."""
        for asset_decision in decision.decisions:
            self._execute_ticker(asset_decision, decision.session_id)

    def _execute_ticker(self, asset_decision: AssetDecision, session_id: str) -> None:
        if asset_decision.action == "HOLD":
            return

        # Block new BUY if ticker already has an OPEN position (FR-014)
        open_positions = self._bank.load_open_positions()
        if any(p.ticker == asset_decision.ticker for p in open_positions):
            return  # position-blocked → treat as HOLD

        client = TradingClient(
            api_key=os.environ.get("ALPACA_API_KEY", ""),
            secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
            paper=True,
        )

        # Budget check via Alpaca account API
        account = client.get_account()
        buying_power = float(account.buying_power)
        data_client = StockHistoricalDataClient(
            api_key=os.environ.get("ALPACA_API_KEY", ""),
            secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
        )
        quotes = data_client.get_stock_latest_quote(
            StockLatestQuoteRequest(
                symbol_or_symbols=asset_decision.ticker,
                feed=DataFeed.IEX,
            )
        )
        ask_price = float(quotes[asset_decision.ticker].ask_price)
        lot = asset_decision.lot_size or 1
        required = ask_price * lot
        if buying_power < required:
            return  # ORDER_FAILED — insufficient budget

        # Place market order
        side = OrderSide.BUY if asset_decision.action == "BUY" else OrderSide.SELL
        client.submit_order(
            MarketOrderRequest(
                symbol=asset_decision.ticker,
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
            ticker=asset_decision.ticker,
            strategy=asset_decision.strategy,
            direction=asset_decision.action,
            entry_price=ask_price,
            entry_time=datetime.now(UTC),
            lot_size=float(lot),
            stop_loss_price=stop_loss_price,
            exit_target=json.dumps(asset_decision.exit_target) if asset_decision.exit_target else "{}",
            evaluation_window_session=5,
            status="OPEN",
        )
        self._bank.write_position(pos)

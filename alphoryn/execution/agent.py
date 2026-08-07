"""Execution agent for Alphoryn.

Deterministic ADK BaseAgent subclass — no LLM model. Receives a
SessionDecision from main_agent and executes orders via alpaca-py.

Constitution Principle I: zero LLM model calls.
"""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from alphoryn.config.models import TIMEFRAME_SECONDS
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import Position, to_db_utc

# Sessions from entry until the feedback agent evaluates the trade, per
# strategies/mean_reversion.md §Evaluation Window and strategies/momentum.md.
EVALUATION_WINDOW_SESSIONS: dict[str, int] = {
    "MEAN_REVERSION": 4,
    "MOMENTUM": 2,
}
_DEFAULT_EVALUATION_WINDOW_SESSIONS = 4


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

    def __init__(self, bank: MemoryBank, candle_timeframe: str = "1H") -> None:
        self._bank = bank
        self._candle_seconds = TIMEFRAME_SECONDS[candle_timeframe]

    def _evaluation_window_close_at(self, strategy: str | None, entry_time: datetime) -> datetime:
        """Return the absolute UTC deadline at which this position's window closes.

        Expressed as wall-clock rather than a session ordinal so it survives the
        run that opened the position (issue #122). The window burns down over
        every elapsed candle, including ones where the market was closed —
        matching the ordinal behaviour it replaces.
        """
        sessions = EVALUATION_WINDOW_SESSIONS.get(
            strategy or "", _DEFAULT_EVALUATION_WINDOW_SESSIONS
        )
        return entry_time + timedelta(seconds=sessions * self._candle_seconds)

    def execute(self, decision: SessionDecision) -> None:
        """Execute a SessionDecision for all tickers sequentially."""
        for asset_decision in decision.decisions:
            self._execute_ticker(asset_decision, decision.session_id)

    def _execute_ticker(self, asset_decision: AssetDecision, session_id: str) -> None:
        if asset_decision.action == "HOLD":
            return

        # FR-014: never open a new position on a feedback-blocked ticker. Second
        # gate only — the scheduler already keeps blocked tickers out of the
        # investigation (FR-005) — so this protects direct callers of the agent.
        # SELL is exempt: a Sell closes an existing position, so the blocking
        # position is the very thing it is trying to unwind.
        if (
            asset_decision.action == "BUY"
            and asset_decision.ticker in self._bank.get_feedback_blocked_tickers()
        ):
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
        entry_time = datetime.now(UTC)
        pos = Position(
            session_id=session_id,
            ticker=asset_decision.ticker,
            strategy=asset_decision.strategy,
            direction=asset_decision.action,
            entry_price=ask_price,
            entry_time=entry_time,
            lot_size=float(lot),
            stop_loss_price=stop_loss_price,
            exit_target=(
                json.dumps(asset_decision.exit_target) if asset_decision.exit_target else "{}"
            ),
            evaluation_window_close_at=to_db_utc(
                self._evaluation_window_close_at(asset_decision.strategy, entry_time)
            ),
            status="OPEN",
        )
        self._bank.write_position(pos)

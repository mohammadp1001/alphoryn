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

from alphoryn.config.models import TIMEFRAME_SECONDS, AlphorynConfig
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import Position, to_db_utc
from alphoryn.telemetry.logger import TelemetryLogger

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

    def __init__(
        self,
        bank: MemoryBank,
        candle_timeframe: str = "1H",
        logger: "TelemetryLogger | None" = None,
        cfg: "AlphorynConfig | None" = None,
        stop_loss_pct: float | None = None,
        session_money_budget: float | None = None,
    ) -> None:
        self._bank = bank
        self._candle_seconds = TIMEFRAME_SECONDS[candle_timeframe]
        self._logger = logger
        self._stop_loss_pct = (
            cfg.stop_loss_pct
            if cfg is not None
            else (stop_loss_pct if stop_loss_pct is not None else 0.02)
        )
        self._session_money_budget = (
            cfg.session_money_budget
            if cfg is not None
            else session_money_budget
        )

    def _emit(
        self,
        event_type: str,
        payload: dict,
        *,
        ticker: str,
        session_id: str,
    ) -> None:
        """Emit an execution event, if a logger is wired in.

        Every order path - placed or refused - goes through here. A run that
        silently places no orders must be distinguishable from one where the
        agent decided to Hold (FR-017, SC-004).
        """
        if self._logger is None:
            return
        self._logger.emit(
            event_type, "execution_agent", payload, session_id=session_id, etf=ticker
        )

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

    def execute(self, decision: SessionDecision) -> dict[str, str]:
        """Execute a SessionDecision for all tickers sequentially.

        Returns the per-ticker execution result keyed by ticker, one of
        ``EXECUTED``, ``HOLD`` or ``FAILED`` — the ``execution_result`` the
        session record carries per data-model.md.
        """
        return {
            d.ticker: self._execute_ticker(d, decision.session_id) for d in decision.decisions
        }

    def _trading_client(self) -> TradingClient:
        return TradingClient(
            api_key=os.environ.get("ALPACA_API_KEY", ""),
            secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
            paper=True,
        )

    def _latest_ask(self, ticker: str) -> float:
        """Return the latest ask price for *ticker*.

        Used for both entry and exit pricing. It is an approximation of the fill
        price in either direction — a market order does not fill at the quote —
        but keeping entry and exit on the same reference means the feedback
        agent compares like with like.
        """
        data_client = StockHistoricalDataClient(
            api_key=os.environ.get("ALPACA_API_KEY", ""),
            secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
        )
        quotes = data_client.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=ticker, feed=DataFeed.IEX)
        )
        return float(quotes[ticker].ask_price)

    def _execute_ticker(self, asset_decision: AssetDecision, session_id: str) -> str:
        if asset_decision.action == "HOLD":
            return "HOLD"
        try:
            if asset_decision.action == "SELL":
                return self._close_position(asset_decision, session_id)
            return self._open_position(asset_decision, session_id)
        except Exception as exc:
            self._emit(
                "ORDER_FAILED",
                {
                    "side": asset_decision.action,
                    "reason": "API_ERROR",
                    "error": str(exc),
                },
                ticker=asset_decision.ticker,
                session_id=session_id,
            )
            return "FAILED"

    def _close_position(self, asset_decision: AssetDecision, session_id: str) -> str:
        """Close the open position on this ticker (data-model.md: Sell closes a Buy).

        A Sell is only ever an instruction to unwind. With no open position there
        is nothing to unwind, so the order is rejected rather than submitted —
        submitting it would open a short, which v0.0.1 does not support.
        """
        open_position = next(
            (p for p in self._bank.load_open_positions() if p.ticker == asset_decision.ticker),
            None,
        )
        if open_position is None:
            self._emit(
                "ORDER_FAILED",
                {"side": "SELL", "reason": "NO_OPEN_POSITION"},
                ticker=asset_decision.ticker,
                session_id=session_id,
            )
            return "FAILED"  # nothing to close; never open a short

        exit_price = self._latest_ask(asset_decision.ticker)
        qty = int(open_position.lot_size)  # close the whole position
        self._trading_client().submit_order(
            MarketOrderRequest(
                symbol=asset_decision.ticker,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
        )
        self._emit(
            "ORDER_PLACED",
            {"side": "SELL", "qty": qty, "price": exit_price, "position_id": open_position.id},
            ticker=asset_decision.ticker,
            session_id=session_id,
        )
        self._bank.update_position_close(
            open_position.id,
            exit_price=exit_price,
            exit_time=datetime.now(UTC),
            exit_reason="AGENT_EXIT",
            status="CLOSED_AGENT_EXIT",
        )
        return "EXECUTED"

    def _open_position(self, asset_decision: AssetDecision, session_id: str) -> str:
        """Open a new long position (FR-014 blocked tickers are refused)."""
        # Second gate only — the scheduler already keeps blocked tickers out of
        # the investigation (FR-005) — so this protects direct callers.
        if asset_decision.ticker in self._bank.get_feedback_blocked_tickers():
            self._emit(
                "ORDER_FAILED",
                {"side": "BUY", "reason": "FEEDBACK_BLOCKED"},
                ticker=asset_decision.ticker,
                session_id=session_id,
            )
            return "FAILED"  # position-blocked → treat as HOLD

        client = self._trading_client()

        # Budget check via Alpaca account API and optional session_money_budget (FR-010).
        account = client.get_account()
        buying_power = float(account.buying_power)
        effective_budget = (
            min(buying_power, self._session_money_budget)
            if self._session_money_budget is not None
            else buying_power
        )
        ask_price = self._latest_ask(asset_decision.ticker)
        lot = asset_decision.lot_size or 1
        required = ask_price * lot
        self._emit(
            "BUDGET_CHECK",
            {
                "buying_power": buying_power,
                "session_money_budget": self._session_money_budget,
                "effective_budget": effective_budget,
                "required": required,
                "lot_size": lot,
                "price": ask_price,
                "sufficient": effective_budget >= required,
            },
            ticker=asset_decision.ticker,
            session_id=session_id,
        )
        if effective_budget < required:
            self._emit(
                "ORDER_FAILED",
                {
                    "side": "BUY",
                    "reason": "INSUFFICIENT_BUDGET",
                    "buying_power": buying_power,
                    "session_money_budget": self._session_money_budget,
                    "required": required,
                },
                ticker=asset_decision.ticker,
                session_id=session_id,
            )
            return "FAILED"

        client.submit_order(
            MarketOrderRequest(
                symbol=asset_decision.ticker,
                qty=lot,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
        )
        self._emit(
            "ORDER_PLACED",
            {"side": "BUY", "qty": lot, "price": ask_price, "strategy": asset_decision.strategy},
            ticker=asset_decision.ticker,
            session_id=session_id,
        )

        # Write OPEN Position record to memory bank
        stop_loss_pct = self._stop_loss_pct
        stop_loss_price = ask_price * (1 - stop_loss_pct)
        entry_time = datetime.now(UTC)
        pos = Position(
            session_id=session_id,
            ticker=asset_decision.ticker,
            strategy=asset_decision.strategy,
            direction="BUY",  # data-model.md: only Buy positions are ever tracked
            entry_price=ask_price,
            entry_time=entry_time,
            lot_size=float(lot),
            stop_loss_price=stop_loss_price,
            # strategies/momentum.md: initialised to entry_price at entry. Left
            # NULL, a position that gaps down before ever printing a new high
            # seeds its trail floor from the lower price (issue #130).
            trailing_stop_high_watermark=ask_price,
            exit_target=(
                json.dumps(asset_decision.exit_target) if asset_decision.exit_target else "{}"
            ),
            evaluation_window_close_at=to_db_utc(
                self._evaluation_window_close_at(asset_decision.strategy, entry_time)
            ),
            status="OPEN",
        )
        self._bank.write_position(pos)
        return "EXECUTED"

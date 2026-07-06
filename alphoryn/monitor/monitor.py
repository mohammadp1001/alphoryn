"""Background position monitor for Alphoryn.

Threading.Thread subclass that polls open positions every ≤30 seconds and
triggers stop-loss, profit-target, and window-expiry exits automatically.
Constitution Principle I: model = None — zero LLM calls.
"""

import json
import os
import threading
from datetime import UTC, datetime

from alpaca.trading.client import TradingClient

from alphoryn.market_data.client import MarketDataClient
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import Position
from alphoryn.telemetry.logger import TelemetryLogger


class PositionMonitor(threading.Thread):
    """Polls open positions and closes them when exit conditions are met.

    Stopped cleanly by setting the provided threading.Event. Runs as a daemon
    thread so it does not block process exit.
    """

    model = None  # Principle I: no LLM calls

    def __init__(
        self,
        bank: MemoryBank,
        market_data: MarketDataClient,
        logger: TelemetryLogger,
        current_session_ordinal: int,
        stop_event: threading.Event,
        *,
        poll_interval: float = 30.0,
    ) -> None:
        super().__init__(daemon=True)
        self._bank = bank
        self._market_data = market_data
        self._logger = logger
        self._current_session_ordinal = current_session_ordinal
        self._stop_event = stop_event
        self._poll_interval = poll_interval

    def run(self) -> None:
        """Poll positions until the stop event is set."""
        while not self._stop_event.is_set():
            self._check_positions()
            self._stop_event.wait(self._poll_interval)

    def _check_positions(self) -> None:
        """Load all OPEN positions and check each for exit conditions."""
        for pos in self._bank.load_open_positions():
            self._check_position(pos)

    def _check_position(self, pos: Position) -> None:
        current_price = self._market_data.get_latest_price(pos.etf)

        if current_price <= pos.stop_loss_price:
            self._close_position(
                pos, current_price, "STOP_LOSS", "CLOSED_STOP_LOSS", "STOP_LOSS_TRIGGERED"
            )
            return

        exit_target = json.loads(pos.exit_target)
        target_type = exit_target.get("type")

        if target_type == "price_level":
            if current_price >= float(exit_target["value"]):
                self._close_position(
                    pos,
                    current_price,
                    "PROFIT_TARGET",
                    "CLOSED_PROFIT_TARGET",
                    "PROFIT_TARGET_TRIGGERED",
                )
                return

        elif target_type == "trailing_stop":
            trail_pct = float(exit_target.get("trail_pct", 0.015))
            watermark = pos.trailing_stop_high_watermark
            if watermark is None or current_price > watermark:
                self._bank.update_trailing_watermark(pos.id, current_price)
                watermark = current_price
            stop_price = watermark * (1 - trail_pct)
            if current_price <= stop_price:
                self._close_position(
                    pos,
                    current_price,
                    "PROFIT_TARGET",
                    "CLOSED_PROFIT_TARGET",
                    "PROFIT_TARGET_TRIGGERED",
                )
                return

        if self._current_session_ordinal == pos.evaluation_window_session:
            self._close_position(
                pos,
                current_price,
                "WINDOW_EXPIRY",
                "CLOSED_WINDOW_EXPIRY",
                "WINDOW_EXPIRY_TRIGGERED",
            )

    def _close_position(
        self,
        pos: Position,
        current_price: float,
        exit_reason: str,
        new_status: str,
        trigger_event: str,
    ) -> None:
        """Call Alpaca to close, then update bank and emit telemetry.

        Returns without updating bank on Alpaca failure (retry next poll).
        """
        try:
            client = TradingClient(
                api_key=os.environ.get("ALPACA_API_KEY", ""),
                secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
                paper=True,
            )
            client.close_position(pos.etf)
        except Exception:
            return

        self._bank.update_position_close(
            pos.id,
            exit_price=current_price,
            exit_time=datetime.now(UTC),
            exit_reason=exit_reason,
            status=new_status,
        )
        self._logger.emit(
            trigger_event,
            "monitor",
            {"etf": pos.etf, "exit_price": current_price, "exit_reason": exit_reason},
            session_id=pos.session_id,
            etf=pos.etf,
        )
        self._logger.emit(
            "POSITION_CLOSED",
            "monitor",
            {"etf": pos.etf, "status": new_status},
            session_id=pos.session_id,
            etf=pos.etf,
        )

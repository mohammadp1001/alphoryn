from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from models.enums import OrderSide, OrderType


class OrderSpec(BaseModel):
    symbol: str
    side: OrderSide
    order_type: OrderType
    qty: float
    limit_price: float | None = None
    stop_price: float | None = None
    client_order_id: str | None = None
    time_in_force: str = "day"  # "day" | "gtc" | "ioc"


class OrderResult(BaseModel):
    order_id: str
    client_order_id: str | None = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    qty: float
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    status: str  # "new" | "filled" | "partially_filled" | "cancelled"
    submitted_at: datetime
    filled_at: datetime | None = None


class CancelResult(BaseModel):
    cancelled_count: int
    order_ids: list[str] = Field(default_factory=list)
    failed_ids: list[str] = Field(default_factory=list)


class Position(BaseModel):
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealised_pnl: float
    unrealised_pnl_pct: float
    side: str  # "long" | "short"


class Portfolio(BaseModel):
    account_id: str
    equity: float  # total account value
    cash: float
    buying_power: float
    positions: list[Position] = Field(default_factory=list)
    portfolio_value: float  # cash + market value of all positions
    day_pnl: float = 0.0
    day_pnl_pct: float = 0.0

    def position_for(self, symbol: str) -> Position | None:
        for p in self.positions:
            if p.symbol == symbol:
                return p
        return None


class OrderRecord(BaseModel):
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    qty: float
    filled_qty: float
    filled_avg_price: float | None
    status: str
    submitted_at: datetime
    filled_at: datetime | None


class BuyingPower(BaseModel):
    buying_power: float
    cash: float
    portfolio_value: float
    currency: str = "USD"


class AccountStatus(BaseModel):
    account_id: str
    status: str  # "ACTIVE" | "INACTIVE" | "ACCOUNT_UPDATED"
    trading_blocked: bool
    pattern_day_trader: bool
    equity: float
    currency: str = "USD"
    is_paper: bool = True

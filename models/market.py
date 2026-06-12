from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OHLCVBar(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCVData(BaseModel):
    symbol: str
    timeframe: str  # e.g. "1Day", "1Hour"
    bars: list[OHLCVBar]

    @property
    def closes(self) -> list[float]:
        return [b.close for b in self.bars]

    @property
    def volumes(self) -> list[float]:
        return [b.volume for b in self.bars]


class Quote(BaseModel):
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    timestamp: datetime


class SpreadData(BaseModel):
    symbol: str
    spread_abs: float
    spread_pct: float
    timestamp: datetime


class OrderBookLevel(BaseModel):
    price: float
    size: float


class OrderBook(BaseModel):
    symbol: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    timestamp: datetime


class ETFScreenFilter(BaseModel):
    min_avg_volume: float = 1_000_000
    min_price: float = 5.0
    symbols: list[str] = Field(default_factory=list)  # empty = full universe


class ETFScreenResult(BaseModel):
    symbol: str
    price: float
    avg_volume_30d: float
    ytd_return_pct: float
    sector: str | None = None


class ETFHolding(BaseModel):
    ticker: str
    weight_pct: float
    name: str | None = None


class ETFHoldings(BaseModel):
    symbol: str
    top_holdings: list[ETFHolding]
    as_of: datetime | None = None


class SectorAllocation(BaseModel):
    sector: str
    weight_pct: float


class SectorMap(BaseModel):
    etf_to_sector: dict[str, str]  # symbol → sector name
    sector_to_etfs: dict[str, list[str]]  # sector → [symbols]


class RangeData(BaseModel):
    symbol: str
    high_52w: float
    low_52w: float
    current_price: float
    pct_from_high: float
    pct_from_low: float


class VolumeBucket(BaseModel):
    price_level: float
    volume: float


class VolumeProfile(BaseModel):
    symbol: str
    buckets: list[VolumeBucket]
    point_of_control: float  # price level with highest volume
    days: int


class BenchmarkReturn(BaseModel):
    symbol: str
    benchmark: str
    period: str
    symbol_return_pct: float
    benchmark_return_pct: float
    excess_return_pct: float


class MarketStatus(BaseModel):
    is_open: bool
    next_open: datetime | None = None
    next_close: datetime | None = None
    timestamp: datetime

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from models.enums import MarketRegime


class NewsItem(BaseModel):
    symbol: str
    headline: str
    summary: str | None = None
    source: str | None = None
    published_at: datetime
    url: str | None = None


class SentimentScore(BaseModel):
    symbol: str
    score: float                    # -1.0 (very bearish) to +1.0 (very bullish)
    positive_count: int
    negative_count: int
    neutral_count: int
    article_count: int


class SentimentReport(BaseModel):
    scores: list[SentimentScore]
    overall_market_sentiment: float
    generated_at: datetime

    def get_score(self, symbol: str) -> float | None:
        for s in self.scores:
            if s.symbol == symbol:
                return s.score
        return None


class EarningsEvent(BaseModel):
    symbol: str
    report_date: date
    estimate_eps: float | None = None
    actual_eps: float | None = None
    surprise_pct: float | None = None


class EarningsCalendar(BaseModel):
    events: list[EarningsEvent]
    days_ahead: int


class MacroIndicator(BaseModel):
    name: str                       # e.g. "VIX", "10Y_YIELD", "CPI_YOY"
    value: float
    previous_value: float | None = None
    as_of: date


class MacroData(BaseModel):
    indicators: list[MacroIndicator]
    fetched_at: datetime

    def get(self, name: str) -> MacroIndicator | None:
        for ind in self.indicators:
            if ind.name == name:
                return ind
        return None


class FundFlowData(BaseModel):
    symbol: str
    flow_1d_usd: float | None = None
    flow_5d_usd: float | None = None
    flow_30d_usd: float | None = None
    as_of: date


class ETFMetrics(BaseModel):
    symbol: str
    expense_ratio_pct: float | None = None
    aum_usd: float | None = None
    avg_volume_30d: float | None = None
    ytd_return_pct: float | None = None


class ETFComparison(BaseModel):
    symbols: list[str]
    metrics: list[ETFMetrics]


class ExpenseRatios(BaseModel):
    ratios: dict[str, float]        # symbol → expense ratio %


class NAVDiscount(BaseModel):
    symbol: str
    nav: float
    price: float
    discount_pct: float             # negative = trading at discount to NAV
    as_of: date


class SectorReturn(BaseModel):
    sector: str
    etf_symbol: str
    return_pct: float


class SectorPerformance(BaseModel):
    timeframe: str
    returns: list[SectorReturn]
    best_sector: str
    worst_sector: str


class ETFPeer(BaseModel):
    symbol: str
    name: str | None = None
    correlation: float | None = None
    expense_ratio_pct: float | None = None


class DividendEvent(BaseModel):
    ex_date: date
    amount: float
    frequency: str | None = None    # "quarterly", "monthly", etc.


class DividendHistory(BaseModel):
    symbol: str
    events: list[DividendEvent]
    ttm_yield_pct: float | None = None


class EconomicEvent(BaseModel):
    name: str
    release_date: date
    importance: str                 # "high" | "medium" | "low"
    forecast: float | None = None
    previous: float | None = None


class EconomicCalendar(BaseModel):
    events: list[EconomicEvent]
    days_ahead: int


class MarketRegimeSummary(BaseModel):
    regime: MarketRegime
    reasoning: str
    vix_level: float | None = None
    trend_direction: str | None = None  # "up" | "down" | "sideways"
    confidence: float                   # 0.0–1.0


class AnalystRating(BaseModel):
    firm: str | None = None
    rating: str                     # "buy" | "hold" | "sell"
    price_target: float | None = None
    rating_date: date | None = None


class AnalystRatings(BaseModel):
    symbol: str
    ratings: list[AnalystRating]
    consensus: str | None = None    # "buy" | "hold" | "sell"
    avg_price_target: float | None = None

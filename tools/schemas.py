"""Pydantic output models for all tool functions.

Every tool returns one of these models via `.model_dump()`.  The `FiniteFloat`
annotated type silently converts NaN/Inf → None at construction time, which
prevents the Gemini API's 400 INVALID_ARGUMENT error caused by JSON-illegal
NaN tokens in tool responses.
"""
from __future__ import annotations

import math
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict


def _finite_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
        return None if not math.isfinite(f) else f
    except (TypeError, ValueError):
        return None


FiniteFloat = Annotated[float | None, BeforeValidator(_finite_float)]


class _Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# Market tools
# ---------------------------------------------------------------------------

class OhlcvBar(_Base):
    timestamp: str
    open: FiniteFloat
    high: FiniteFloat
    low: FiniteFloat
    close: FiniteFloat
    volume: FiniteFloat


class OhlcvResponse(_Base):
    symbol: str
    timeframe: str
    bars: list[OhlcvBar]


class QuoteResponse(_Base):
    symbol: str
    bid: FiniteFloat
    ask: FiniteFloat
    bid_size: FiniteFloat
    ask_size: FiniteFloat
    timestamp: str


class SpreadResponse(_Base):
    symbol: str
    spread_abs: FiniteFloat
    spread_pct: FiniteFloat
    timestamp: str


class OrderBookLevel(_Base):
    price: FiniteFloat
    size: FiniteFloat


class OrderBookResponse(_Base):
    symbol: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    timestamp: str


class ScreenedEtf(_Base):
    symbol: str
    price: FiniteFloat
    avg_volume_30d: FiniteFloat
    ytd_return_pct: FiniteFloat
    sector: str


class ScreenEtfsResponse(_Base):
    results: list[ScreenedEtf]


class EtfHolding(_Base):
    ticker: str
    weight_pct: FiniteFloat
    name: str


class EtfHoldingsResponse(_Base):
    symbol: str
    top_holdings: list[EtfHolding]


class SectorMapResponse(_Base):
    etf_to_sector: dict[str, str]
    sector_to_etfs: dict[str, list[str]]


class Range52wResponse(_Base):
    symbol: str
    high_52w: FiniteFloat
    low_52w: FiniteFloat
    current_price: FiniteFloat
    pct_from_high: FiniteFloat
    pct_from_low: FiniteFloat


class VolumeBucket(_Base):
    price_level: FiniteFloat
    volume: FiniteFloat


class VolumeProfileResponse(_Base):
    symbol: str
    buckets: list[VolumeBucket]
    point_of_control: FiniteFloat
    days: int


class BenchmarkReturnResponse(_Base):
    symbol: str
    benchmark: str
    period: str
    symbol_return_pct: FiniteFloat
    benchmark_return_pct: FiniteFloat
    excess_return_pct: FiniteFloat


class IntradayBar(_Base):
    timestamp: str
    open: FiniteFloat
    high: FiniteFloat
    low: FiniteFloat
    close: FiniteFloat
    volume: FiniteFloat


class IntradayBarsResponse(_Base):
    symbol: str
    timeframe: str
    bars: list[IntradayBar]


class MarketStatusResponse(_Base):
    is_open: bool
    next_open: str | None
    next_close: str | None
    timestamp: str


# ---------------------------------------------------------------------------
# Research tools
# ---------------------------------------------------------------------------

class NewsItem(_Base):
    headline: str
    source: str
    published_at: str
    url: str


class NewsResponse(_Base):
    symbol: str
    items: list[NewsItem]


class SentimentResponse(_Base):
    symbol: str
    score: FiniteFloat
    label: str
    item_count: int


class EarningsEvent(_Base):
    date: str
    estimate_eps: FiniteFloat
    surprise_pct: FiniteFloat


class EarningsCalendarResponse(_Base):
    symbol: str
    events: list[EarningsEvent]


class MacroDataResponse(_Base):
    vix: FiniteFloat
    yield_10y: FiniteFloat
    yield_2y: FiniteFloat
    dxy: FiniteFloat
    timestamp: str


class FundFlowsResponse(_Base):
    symbol: str
    flow_direction: str
    estimated_flow_usd: FiniteFloat


class EtfMetricsResponse(_Base):
    symbol: str
    aum_usd: FiniteFloat
    expense_ratio: FiniteFloat
    nav: FiniteFloat
    shares_outstanding: FiniteFloat


class EtfComparison(_Base):
    symbol: str
    aum_usd: FiniteFloat
    expense_ratio: FiniteFloat
    ytd_return_pct: FiniteFloat
    beta: FiniteFloat


class CompareEtfsResponse(_Base):
    comparisons: list[EtfComparison]


class ExpenseRatioEntry(_Base):
    symbol: str
    expense_ratio: FiniteFloat


class ExpenseRatiosResponse(_Base):
    ratios: list[ExpenseRatioEntry]


class SectorReturn(_Base):
    symbol: str
    sector: str
    return_pct: FiniteFloat


class SectorPerformanceResponse(_Base):
    timeframe: str
    returns: list[SectorReturn]


class DividendEntry(_Base):
    date: str
    amount: FiniteFloat


class DividendHistoryResponse(_Base):
    symbol: str
    dividends: list[DividendEntry]


class EconomicEvent(_Base):
    event: str
    date: str
    impact: str
    forecast: str


class EconomicCalendarResponse(_Base):
    events: list[EconomicEvent]
    days_ahead: int


class MarketRegimeResponse(_Base):
    regime: str
    reasoning: str
    vix: FiniteFloat
    yield_10y: FiniteFloat
    yield_2y: FiniteFloat
    yield_curve_spread: FiniteFloat
    benchmark_symbol: str
    benchmark_return_20d: FiniteFloat


class AnalystRating(_Base):
    firm: str
    rating: str
    price_target: FiniteFloat
    rating_date: str


class AnalystRatingsResponse(_Base):
    symbol: str
    ratings: list[AnalystRating]


# ---------------------------------------------------------------------------
# Analysis tools
# ---------------------------------------------------------------------------

class RsiResponse(_Base):
    symbol: str
    period: int
    current: FiniteFloat
    values: list[FiniteFloat]
    is_overbought: bool
    is_oversold: bool


class MacdResponse(_Base):
    symbol: str
    macd_line: list[FiniteFloat]
    signal_line: list[FiniteFloat]
    histogram: list[FiniteFloat]
    current_macd: FiniteFloat
    current_signal: FiniteFloat
    current_histogram: FiniteFloat


class BollingerResponse(_Base):
    symbol: str
    period: int
    current_upper: FiniteFloat
    current_middle: FiniteFloat
    current_lower: FiniteFloat
    current_price: FiniteFloat
    pct_b: FiniteFloat
    bandwidth: FiniteFloat


class AtrResponse(_Base):
    symbol: str
    period: int
    current: FiniteFloat
    values: list[FiniteFloat]


class BetaResponse(_Base):
    symbol: str
    benchmark: str
    beta: FiniteFloat
    r_squared: FiniteFloat
    period_days: int


class MomentumResponse(_Base):
    symbol: str
    momentum_score: FiniteFloat
    rsi_contribution: FiniteFloat
    macd_contribution: FiniteFloat
    price_vs_sma_contribution: FiniteFloat
    volume_trend_contribution: FiniteFloat
    raw_rsi: FiniteFloat
    raw_macd_histogram: FiniteFloat


class CrossoverResponse(_Base):
    symbol: str
    crossover_type: str
    bars_since_crossover: int | None
    strength: FiniteFloat


class SupportResistanceLevel(_Base):
    price: FiniteFloat
    level_type: str
    strength: FiniteFloat


class SupportResistanceResponse(_Base):
    symbol: str
    levels: list[SupportResistanceLevel]
    nearest_support: FiniteFloat
    nearest_resistance: FiniteFloat


class RankedSignal(_Base):
    symbol: str
    rank: int
    momentum_score: FiniteFloat
    technical_score: FiniteFloat
    combined_score: FiniteFloat


class RankByMomentumResponse(_Base):
    signals: list[RankedSignal]
    screened_universe: list[str]


class BacktestResponse(_Base):
    symbol: str
    strategy: str
    signal_pattern: str
    lookback_bars: int
    forward_return_days: int
    match_count: int
    avg_forward_return_pct: FiniteFloat
    win_rate_pct: FiniteFloat
    max_adverse_excursion_pct: FiniteFloat


class SharpeResponse(_Base):
    symbol: str
    sharpe_ratio: FiniteFloat
    annualised_return_pct: FiniteFloat
    annualised_volatility_pct: FiniteFloat
    risk_free_rate: FiniteFloat


class MaxDrawdownResponse(_Base):
    symbol: str
    max_drawdown_pct: FiniteFloat
    drawdown_start_bar: int
    drawdown_end_bar: int
    recovery_bars: int | None


class CorrelationResponse(_Base):
    symbols: list[str]
    matrix: list[list[FiniteFloat]]


class TechnicalScoreResponse(_Base):
    symbol: str
    composite_score: FiniteFloat
    rsi_score: FiniteFloat
    macd_score: FiniteFloat
    bollinger_score: FiniteFloat
    strategy: str


# ---------------------------------------------------------------------------
# Execution tools
# ---------------------------------------------------------------------------

class PositionEntry(_Base):
    symbol: str
    qty: float
    side: str
    avg_entry_price: float
    market_value: float
    unrealised_pnl: float
    unrealised_pnl_pct: float


class PortfolioResponse(_Base):
    positions: list[PositionEntry]
    cash_usd: float
    portfolio_value: float
    buying_power: float
    is_paper: bool


class PositionResponse(_Base):
    symbol: str
    has_position: bool
    qty: float | None = None
    side: str | None = None
    avg_entry_price: float | None = None
    market_value: float | None = None
    unrealised_pnl: float | None = None
    unrealised_pnl_pct: float | None = None


class OrderResponse(_Base):
    order_id: str
    status: str
    symbol: str
    qty: float
    side: str
    type: str
    submitted_at: str | None


class LimitOrderResponse(_Base):
    order_id: str
    status: str
    symbol: str
    qty: float
    side: str
    type: str
    limit_price: float
    submitted_at: str | None


class CancelOrderResponse(_Base):
    order_id: str
    cancelled: bool
    message: str


class OrderStatusResponse(_Base):
    order_id: str
    status: str
    filled_qty: float
    filled_avg_price: float
    updated_at: str | None


class AccountStatusResponse(_Base):
    is_paper: bool
    status: str
    buying_power: float
    cash: float
    portfolio_value: float
    daytrade_count: int
    pattern_day_trader: bool


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------

class WriteTradeResponse(_Base):
    trade_id: str
    written: bool


class ResolveTradeResponse(_Base):
    trade_id: str
    debate_winner: str
    resolved: bool


class CalibrationResponse(_Base):
    has_data: bool
    opt_win_rate: FiniteFloat
    pess_win_rate: FiniteFloat
    opt_summary: str
    pess_summary: str
    trade_count: int


class CycleRecord(_Base):
    cycle_index: int
    outcome: str
    abort_reason: str
    abort_stage: str
    shortlisted_symbols: list[str]
    risk_level: str
    trade_id: str | None
    realised_pnl_pct: FiniteFloat


class SessionCyclesResponse(_Base):
    session_id: str
    cycles: list[CycleRecord]


class UnresolvedTrade(_Base):
    trade_id: str
    symbol: str
    order_id: str
    entry_price: FiniteFloat
    side: str
    opened_at: str | None


class UnresolvedTradesResponse(_Base):
    trades: list[UnresolvedTrade]


class RecordCycleResponse(_Base):
    session_id: str
    cycle_index: int
    written: bool


# ---------------------------------------------------------------------------
# Agent output models (output_schema on Agent, written via output_key)
# ---------------------------------------------------------------------------

class MarketRegimeOutput(_Base):
    regime: str
    reasoning: str
    vix: FiniteFloat
    yield_10y: FiniteFloat
    yield_2y: FiniteFloat
    top_sector: str | None = None
    bottom_sector: str | None = None
    sentiment_label: str


class RankedSignalItem(_Base):
    symbol: str
    rank: int
    combined_score: FiniteFloat
    reasoning: str


class RankedSignalsOutput(_Base):
    strategy: str
    signals: list[RankedSignalItem]


class RiskVerdictOutput(_Base):
    recommended_level: str
    reasoning: str
    acknowledged_opposing_signal: str


class OrderResultOutput(_Base):
    order_id: str
    status: str
    symbol: str
    qty: float
    side: str
    type: str
    limit_price: float | None = None
    submitted_at: str | None = None


# ---------------------------------------------------------------------------
# Coordinator ↔ Execution BaseAgent contract
# ---------------------------------------------------------------------------

class PendingOrder(_Base):
    """Written by coordinator to state["pending_order"]; read by execution BaseAgent."""
    symbol: str
    side: str                        # "buy" | "sell"
    asset_class: str                 # "etf" | "crypto"
    order_type: str                  # "market" | "limit"
    qty: float | None = None         # shares/units; None = size by buying_power_pct
    buying_power_pct: float = 0.10   # fraction of buying power if qty is None
    limit_price: float | None = None
    strategy: str = ""
    risk_level: str = ""
    session_id: str = ""
    cycle_index: int = 0

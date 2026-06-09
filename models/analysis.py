from __future__ import annotations

from pydantic import BaseModel, Field

from models.enums import Strategy


class RSIResult(BaseModel):
    symbol: str
    period: int
    values: list[float]         # most recent last
    current: float

    @property
    def is_overbought(self) -> bool:
        return self.current > 70

    @property
    def is_oversold(self) -> bool:
        return self.current < 30


class MACDResult(BaseModel):
    symbol: str
    macd_line: list[float]
    signal_line: list[float]
    histogram: list[float]
    current_macd: float
    current_signal: float
    current_histogram: float


class BollingerResult(BaseModel):
    symbol: str
    period: int
    upper: list[float]
    middle: list[float]         # SMA
    lower: list[float]
    current_upper: float
    current_middle: float
    current_lower: float
    current_price: float

    @property
    def bandwidth(self) -> float:
        return (self.current_upper - self.current_lower) / self.current_middle

    @property
    def pct_b(self) -> float:
        """Position within the band: 0 = lower, 1 = upper."""
        band_width = self.current_upper - self.current_lower
        if band_width == 0:
            return 0.5
        return (self.current_price - self.current_lower) / band_width


class ATRResult(BaseModel):
    symbol: str
    period: int
    values: list[float]
    current: float


class BetaResult(BaseModel):
    symbol: str
    benchmark: str
    beta: float
    r_squared: float
    period_days: int


class MomentumSignal(BaseModel):
    symbol: str
    momentum_score: float           # normalised -1.0 to +1.0
    rsi_contribution: float
    macd_contribution: float
    price_vs_sma_contribution: float
    volume_trend_contribution: float
    raw_rsi: float
    raw_macd_histogram: float


class CrossoverSignal(BaseModel):
    symbol: str
    crossover_type: str             # "bullish" | "bearish" | "none"
    bars_since_crossover: int | None = None
    strength: float                 # 0.0–1.0


class SRLevel(BaseModel):
    price: float
    level_type: str                 # "support" | "resistance"
    strength: float                 # 0.0–1.0 based on touch count


class SRLevels(BaseModel):
    symbol: str
    levels: list[SRLevel]
    nearest_support: float | None = None
    nearest_resistance: float | None = None


class TechnicalScore(BaseModel):
    symbol: str
    composite_score: float          # -1.0 to +1.0
    rsi_score: float
    macd_score: float
    bollinger_score: float
    strategy: Strategy


class RankedSignal(BaseModel):
    symbol: str
    rank: int
    momentum_score: float
    technical_score: float
    combined_score: float


class RankedSignals(BaseModel):
    strategy: Strategy
    signals: list[RankedSignal]     # sorted by combined_score descending
    screened_universe: list[str]    # symbols that were evaluated


class SignalMatch(BaseModel):
    """One historical occurrence of a signal pattern similar to the current one."""
    bar_index: int                  # index in lookback window
    signal_strength: float
    forward_return_pct: float       # actual return N days after signal


class BacktestResult(BaseModel):
    """Signal lookback summary — NOT a full portfolio simulation."""
    symbol: str
    strategy: Strategy
    signal_pattern: str             # human-readable description
    lookback_bars: int
    forward_return_days: int
    match_count: int
    avg_forward_return_pct: float
    win_rate_pct: float             # % of matches with positive forward return
    max_adverse_excursion_pct: float
    matches: list[SignalMatch] = Field(default_factory=list)


class SharpeResult(BaseModel):
    symbol: str
    sharpe_ratio: float
    annualised_return_pct: float
    annualised_volatility_pct: float
    risk_free_rate: float = 0.0


class DrawdownResult(BaseModel):
    symbol: str
    max_drawdown_pct: float
    drawdown_start_bar: int | None = None
    drawdown_end_bar: int | None = None
    recovery_bars: int | None = None


class CorrelationMatrix(BaseModel):
    symbols: list[str]
    matrix: list[list[float]]       # row i, col j = corr(symbols[i], symbols[j])

    def get(self, a: str, b: str) -> float:
        i, j = self.symbols.index(a), self.symbols.index(b)
        return self.matrix[i][j]

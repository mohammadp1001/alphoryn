"""Market data client for Alphoryn.

Provides build_snapshot (ADK tool) and get_latest_price for the stop-loss
monitor. All technical signal computation is internal (_data_fetch).
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


@dataclass(frozen=True)
class ETFSignals:
    """Computed technical signals for one ETF (15 fields per data-model.md)."""

    rsi_14: float
    adx_14: float
    ema_20: float
    ema_50: float
    sma_20: float
    bollinger_upper: float
    bollinger_lower: float
    bollinger_pct_b: float
    macd_line: float
    macd_signal: float
    macd_histogram: float
    volume_vs_avg: float
    current_price: float
    price_vs_ema_20_pct: float
    price_vs_sma_20_pct: float


@dataclass(frozen=True)
class SignalSnapshot:
    """Frozen snapshot of signals for both ETFs at one candle close."""

    captured_at: datetime
    etf1_signals: ETFSignals
    etf2_signals: ETFSignals


def _ema(values: list[float], period: int) -> float:
    """Compute the final EMA of a series using the standard multiplier formula."""
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _sma(values: list[float]) -> float:
    return sum(values) / len(values)


def _compute_rsi(closes: list[float], period: int = 14) -> float:
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0.0) for c in changes[-period:]]
    losses = [max(-c, 0.0) for c in changes[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1 + rs)


def _compute_adx(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> float:
    """Compute ADX using Wilder's smoothing (simplified average TR / average DM)."""
    n = len(closes)
    if n < period + 1:
        return 0.0

    tr_list, dm_plus_list, dm_minus_list = [], [], []
    for i in range(1, n):
        hi, lo, pc = highs[i], lows[i], closes[i - 1]
        tr = max(hi - lo, abs(hi - pc), abs(lo - pc))
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        dm_plus = up_move if (up_move > down_move and up_move > 0) else 0.0
        dm_minus = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr_list.append(tr)
        dm_plus_list.append(dm_plus)
        dm_minus_list.append(dm_minus)

    atr = sum(tr_list[-period:]) / period
    if atr == 0:
        return 0.0
    di_plus = (sum(dm_plus_list[-period:]) / period) / atr * 100
    di_minus = (sum(dm_minus_list[-period:]) / period) / atr * 100
    di_sum = di_plus + di_minus
    if di_sum == 0:
        return 0.0
    return abs(di_plus - di_minus) / di_sum * 100


def _compute_bollinger(
    closes: list[float], period: int = 20, std_dev: float = 2.0
) -> tuple[float, float, float]:
    """Return (upper, lower, pct_b) for the last bar."""
    window = closes[-period:]
    sma = _sma(window)
    variance = sum((x - sma) ** 2 for x in window) / period
    std = variance ** 0.5
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    band_width = upper - lower
    pct_b = (closes[-1] - lower) / band_width if band_width != 0 else 0.5
    return upper, lower, pct_b


def _compute_macd(closes: list[float]) -> tuple[float, float, float]:
    """Return (macd_line, signal, histogram)."""
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    line = ema12 - ema26

    # Signal line: 9-period EMA of the MACD line history (need per-bar MACD values)
    # Build MACD line series from bar index 25 onwards
    macd_series: list[float] = []
    k12, k26 = 2.0 / 13, 2.0 / 27
    e12, e26 = closes[0], closes[0]
    for price in closes[1:]:
        e12 = price * k12 + e12 * (1 - k12)
        e26 = price * k26 + e26 * (1 - k26)
        macd_series.append(e12 - e26)

    signal = _ema(macd_series, 9)
    histogram = line - signal
    return line, signal, histogram


class MarketDataClient:
    """Fetches Alpaca bars and computes ETFSignals for both ETFs.

    build_snapshot is registered as an ADK tool (the agent calls it).
    _data_fetch is internal and never exposed to agents (Principle V).
    """

    def __init__(self, api_key: str = "", secret_key: str = "", paper: bool = True) -> None:
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self._secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        self._paper = paper
        self.model = None  # Principle I: no LLM model

    def build_snapshot(self, etf1: str, etf2: str, candle_close_at: datetime | str) -> SignalSnapshot:
        """ADK tool: fetch bars and return a frozen SignalSnapshot for both ETFs."""
        if isinstance(candle_close_at, str):
            candle_close_at = datetime.fromisoformat(candle_close_at)
        etf1_signals = self._data_fetch(etf1, candle_close_at)
        etf2_signals = self._data_fetch(etf2, candle_close_at)
        return SignalSnapshot(
            captured_at=candle_close_at,
            etf1_signals=etf1_signals,
            etf2_signals=etf2_signals,
        )

    def _data_fetch(self, etf: str, candle_close_at: datetime) -> ETFSignals:
        """Internal: fetch 60 1H bars ending at candle_close_at and compute all 15 signals."""
        client = StockHistoricalDataClient(
            api_key=self._api_key, secret_key=self._secret_key
        )
        start = candle_close_at - timedelta(hours=60)
        req = StockBarsRequest(
            symbol_or_symbols=etf,
            timeframe=TimeFrame.Hour,
            start=start,
            end=candle_close_at,
            feed=DataFeed.IEX,
        )
        bars = client.get_stock_bars(req)[etf]

        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        volumes = [b.volume for b in bars]

        current_price = closes[-1]

        rsi_14 = _compute_rsi(closes, 14)
        adx_14 = _compute_adx(highs, lows, closes, 14)
        ema_20 = _ema(closes, 20)
        ema_50 = _ema(closes, 50)
        sma_20 = _sma(closes[-20:])
        bollinger_upper, bollinger_lower, bollinger_pct_b = _compute_bollinger(closes)
        macd_line, macd_signal, macd_histogram = _compute_macd(closes)
        volume_vs_avg = volumes[-1] / _sma(volumes[-20:]) if volumes else 1.0
        price_vs_ema_20_pct = (current_price - ema_20) / ema_20 * 100
        price_vs_sma_20_pct = (current_price - sma_20) / sma_20 * 100

        return ETFSignals(
            rsi_14=rsi_14,
            adx_14=adx_14,
            ema_20=ema_20,
            ema_50=ema_50,
            sma_20=sma_20,
            bollinger_upper=bollinger_upper,
            bollinger_lower=bollinger_lower,
            bollinger_pct_b=bollinger_pct_b,
            macd_line=macd_line,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            volume_vs_avg=volume_vs_avg,
            current_price=current_price,
            price_vs_ema_20_pct=price_vs_ema_20_pct,
            price_vs_sma_20_pct=price_vs_sma_20_pct,
        )

    def get_latest_price(self, etf: str) -> float:
        """Return the latest 1-min bar close price for the stop-loss monitor."""
        client = StockHistoricalDataClient(
            api_key=self._api_key, secret_key=self._secret_key
        )
        now = datetime.now(UTC)
        req = StockBarsRequest(
            symbol_or_symbols=etf,
            timeframe=TimeFrame.Minute,
            start=now - timedelta(minutes=5),
            end=now,
        )
        bars = client.get_stock_bars(req)[etf]
        return float(bars[-1].close)

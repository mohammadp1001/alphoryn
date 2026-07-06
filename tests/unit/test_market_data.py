"""Unit tests for alphoryn/market_data/client.py (T021 scope).

Tests are written BEFORE the implementation (TDD). They verify:
- All 15 ETFSignals fields are computed correctly from fixture OHLCV data
- build_snapshot returns a frozen SignalSnapshot
- _data_fetch is not exposed as an ADK tool (private/underscore convention)
- get_latest_price returns a float from the latest bar

Alpaca SDK calls are stubbed via unittest.mock.
"""

import dataclasses
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from alphoryn.market_data.client import ETFSignals, MarketDataClient, SignalSnapshot

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_N_BARS = 60  # enough for EMA-50 + extra history

# Seed so results are deterministic across test runs.
import random as _rng

_rng.seed(42)


def _make_bar(close: float, volume: float = 1_000_000.0) -> MagicMock:
    bar = MagicMock()
    bar.close = close
    bar.open = close * 0.999
    bar.high = close * 1.002
    bar.low = close * 0.997
    bar.volume = volume
    return bar


def _trending_bars(n: int = _N_BARS) -> list[MagicMock]:
    """Generate n bars with a gentle upward trend (close 90 → 110)."""
    closes = [90.0 + (110.0 - 90.0) * i / (n - 1) for i in range(n)]
    return [_make_bar(c) for c in closes]


def _flat_bars(n: int = _N_BARS, price: float = 100.0) -> list[MagicMock]:
    """Generate n bars at a constant price."""
    return [_make_bar(price) for _ in range(n)]


def _client() -> MarketDataClient:
    return MarketDataClient(api_key="test-key", secret_key="test-secret", paper=True)


def _stub_data_fetch(client: MarketDataClient, etf_signals: ETFSignals):
    """Monkeypatch _data_fetch to return a given ETFSignals object."""
    client._data_fetch = MagicMock(return_value=etf_signals)  # noqa: SLF001


def _spy_signals(
    rsi_14: float = 55.0,
    adx_14: float = 25.0,
    ema_20: float = 108.0,
    ema_50: float = 105.0,
    sma_20: float = 107.0,
    bollinger_upper: float = 112.0,
    bollinger_lower: float = 102.0,
    bollinger_pct_b: float = 0.6,
    macd_line: float = 0.5,
    macd_signal: float = 0.3,
    macd_histogram: float = 0.2,
    volume_vs_avg: float = 1.1,
    current_price: float = 110.0,
    price_vs_ema_20_pct: float = 1.85,
    price_vs_sma_20_pct: float = 2.80,
) -> ETFSignals:
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


# ---------------------------------------------------------------------------
# ETFSignals structure
# ---------------------------------------------------------------------------


def test_etf_signals_is_frozen_dataclass() -> None:
    sig = _spy_signals()
    assert dataclasses.is_dataclass(sig)
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        sig.rsi_14 = 99.0  # type: ignore[misc]


def test_etf_signals_has_all_15_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(ETFSignals)}
    required = {
        "rsi_14", "adx_14", "ema_20", "ema_50", "sma_20",
        "bollinger_upper", "bollinger_lower", "bollinger_pct_b",
        "macd_line", "macd_signal", "macd_histogram",
        "volume_vs_avg", "current_price",
        "price_vs_ema_20_pct", "price_vs_sma_20_pct",
    }
    assert required == field_names


# ---------------------------------------------------------------------------
# SignalSnapshot structure
# ---------------------------------------------------------------------------


def test_signal_snapshot_is_frozen_dataclass() -> None:
    now = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
    sig = _spy_signals()
    snap = SignalSnapshot(captured_at=now, etf1_signals=sig, etf2_signals=sig)
    assert dataclasses.is_dataclass(snap)
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        snap.captured_at = datetime.now(timezone.utc)  # type: ignore[misc]


def test_signal_snapshot_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(SignalSnapshot)}
    assert field_names == {"captured_at", "etf1_signals", "etf2_signals"}


# ---------------------------------------------------------------------------
# build_snapshot wiring
# ---------------------------------------------------------------------------


def test_build_snapshot_returns_signal_snapshot() -> None:
    client = _client()
    now = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
    spy_sig = _spy_signals()
    qqq_sig = _spy_signals(current_price=450.0, ema_20=445.0)
    client._data_fetch = MagicMock(side_effect=[spy_sig, qqq_sig])  # noqa: SLF001
    snap = client.build_snapshot("SPY", "QQQ", now)
    assert isinstance(snap, SignalSnapshot)
    assert snap.captured_at == now
    assert snap.etf1_signals is spy_sig
    assert snap.etf2_signals is qqq_sig


def test_build_snapshot_calls_data_fetch_for_both_etfs() -> None:
    client = _client()
    now = datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc)
    spy_sig = _spy_signals()
    client._data_fetch = MagicMock(return_value=spy_sig)  # noqa: SLF001
    client.build_snapshot("SPY", "QQQ", now)
    assert client._data_fetch.call_count == 2  # noqa: SLF001
    calls = client._data_fetch.call_args_list  # noqa: SLF001
    assert calls[0][0][0] == "SPY"
    assert calls[1][0][0] == "QQQ"


def test_data_fetch_is_private_not_exposed_as_adk_tool() -> None:
    """_data_fetch must be a private method (underscore prefix)."""
    client = _client()
    # Confirm the private version exists …
    assert hasattr(client, "_data_fetch")
    # … and the public version does NOT exist.
    assert not hasattr(client, "data_fetch")


# ---------------------------------------------------------------------------
# _data_fetch signal computation — stubs alpaca SDK
# ---------------------------------------------------------------------------


def _patched_data_fetch(bars: list, etf: str = "SPY") -> ETFSignals:
    """Call _data_fetch with stubbed Alpaca StockHistoricalDataClient."""
    client = _client()
    mock_response = MagicMock()
    mock_response.__getitem__ = MagicMock(return_value=bars)
    with patch("alphoryn.market_data.client.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_bars.return_value = mock_response
        return client._data_fetch(etf, datetime(2024, 1, 15, 15, 0, tzinfo=timezone.utc))  # noqa: SLF001


def test_data_fetch_returns_etf_signals_instance() -> None:
    result = _patched_data_fetch(_trending_bars())
    assert isinstance(result, ETFSignals)


def test_current_price_is_last_close() -> None:
    bars = _trending_bars()
    result = _patched_data_fetch(bars)
    assert result.current_price == pytest.approx(bars[-1].close, rel=1e-6)


def test_rsi_within_valid_range() -> None:
    result = _patched_data_fetch(_trending_bars())
    assert 0.0 <= result.rsi_14 <= 100.0


def test_adx_within_valid_range() -> None:
    result = _patched_data_fetch(_trending_bars())
    assert 0.0 <= result.adx_14 <= 100.0


def test_bollinger_upper_greater_than_lower() -> None:
    result = _patched_data_fetch(_trending_bars())
    assert result.bollinger_upper >= result.bollinger_lower


def test_macd_histogram_equals_line_minus_signal() -> None:
    result = _patched_data_fetch(_trending_bars())
    assert result.macd_histogram == pytest.approx(
        result.macd_line - result.macd_signal, rel=1e-9
    )


def test_price_vs_ema_20_pct_formula() -> None:
    result = _patched_data_fetch(_trending_bars())
    expected = (result.current_price - result.ema_20) / result.ema_20 * 100
    assert result.price_vs_ema_20_pct == pytest.approx(expected, rel=1e-9)


def test_price_vs_sma_20_pct_formula() -> None:
    result = _patched_data_fetch(_trending_bars())
    expected = (result.current_price - result.sma_20) / result.sma_20 * 100
    assert result.price_vs_sma_20_pct == pytest.approx(expected, rel=1e-9)


def test_volume_vs_avg_positive() -> None:
    result = _patched_data_fetch(_trending_bars())
    assert result.volume_vs_avg > 0.0


def test_sma_20_within_price_range() -> None:
    bars = _trending_bars()
    result = _patched_data_fetch(bars)
    closes = [b.close for b in bars]
    assert min(closes) <= result.sma_20 <= max(closes)


def test_rsi_high_for_all_uptrend() -> None:
    """Strongly trending up bars → RSI > 50."""
    bars = _trending_bars(60)
    result = _patched_data_fetch(bars)
    assert result.rsi_14 > 50.0


def test_ema_20_lags_in_uptrend() -> None:
    """In an uptrend, EMA-20 should be below the latest close (lags behind)."""
    bars = _trending_bars(60)
    result = _patched_data_fetch(bars)
    assert result.ema_20 <= result.current_price


def test_bollinger_pct_b_formula() -> None:
    """%B = (close - lower) / (upper - lower). Should be in [0, 1] for normal markets."""
    bars = _trending_bars(60)
    result = _patched_data_fetch(bars)
    band_width = result.bollinger_upper - result.bollinger_lower
    if band_width > 0:
        expected_pct_b = (result.current_price - result.bollinger_lower) / band_width
        assert result.bollinger_pct_b == pytest.approx(expected_pct_b, rel=1e-9)


# ---------------------------------------------------------------------------
# get_latest_price
# ---------------------------------------------------------------------------


def test_get_latest_price_returns_float() -> None:
    client = _client()
    bar = _make_bar(close=452.75)
    mock_response = MagicMock()
    mock_response.__getitem__ = MagicMock(return_value=[bar])
    with patch("alphoryn.market_data.client.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_bars.return_value = mock_response
        price = client.get_latest_price("QQQ")
    assert isinstance(price, float)
    assert price == pytest.approx(452.75, rel=1e-6)

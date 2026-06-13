"""tools.data — OHLCV and price-range data tools used by workflow pipelines."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from infra.observability import api_call_span, get_logger
from infra.rate_limiter import acquire_alpaca_data, acquire_yfinance
from infra.retry import with_retry
from tools.schemas import OhlcvResponse, Range52wResponse

logger = get_logger("tools.data")


def _data_client():
    from alpaca.data import StockHistoricalDataClient  # type: ignore[import]

    return StockHistoricalDataClient(
        api_key=os.environ.get("ALPACA_DATA_KEY") or os.environ.get("ALPACA_API_KEY"),
        secret_key=os.environ.get("ALPACA_DATA_SECRET") or os.environ.get("ALPACA_API_SECRET"),
    )


def _crypto_client():
    from alpaca.data import CryptoHistoricalDataClient  # type: ignore[import]

    return CryptoHistoricalDataClient(
        api_key=os.environ.get("ALPACA_DATA_KEY") or os.environ.get("ALPACA_API_KEY"),
        secret_key=os.environ.get("ALPACA_DATA_SECRET") or os.environ.get("ALPACA_API_SECRET"),
    )


def _is_crypto(symbol: str) -> bool:
    return symbol.endswith("-USD")


@with_retry
async def get_ohlcv(symbol: str, timeframe: str, bars: int) -> dict:
    """Fetch OHLCV bar history for an ETF.

    Tries Alpaca IEX feed first; falls back to yfinance if IEX returns no data
    (IEX only covers symbols that actively trade on that venue — many non-US or
    less-liquid ETFs are absent from IEX even though they're US-listed).

    Args:
        symbol: Ticker symbol, e.g. 'XLK'.
        timeframe: Bar size — '30Min', '1Hour', '3Hour', '4Hour', '12Hour', '1Day'.
        bars: Number of bars to return (most recent).

    Returns:
        dict with 'symbol', 'timeframe', and 'bars' (list of OHLCV dicts).
    """
    from alpaca.data.requests import StockBarsRequest  # type: ignore[import]
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit  # type: ignore[import]

    logger.info("get_ohlcv symbol=%s timeframe=%s bars=%d", symbol, timeframe, bars)
    tf_map = {
        "1Day": TimeFrame.Day,
        "30Min": TimeFrame(30, TimeFrameUnit.Minute),
        "1Hour": TimeFrame.Hour,
        "3Hour": TimeFrame(3, TimeFrameUnit.Hour),
        "4Hour": TimeFrame(4, TimeFrameUnit.Hour),
        "12Hour": TimeFrame(12, TimeFrameUnit.Hour),
    }
    tf = tf_map.get(timeframe, TimeFrame.Day)

    end = datetime.utcnow()
    start = end - timedelta(days=bars * 2)  # over-fetch, trim to bars

    _alpaca_key = os.environ.get("ALPACA_DATA_KEY") or os.environ.get("ALPACA_API_KEY")
    bar_list = []

    if _alpaca_key:
        await acquire_alpaca_data()
        if _is_crypto(symbol):
            from alpaca.data.requests import CryptoBarsRequest  # type: ignore[import]

            alpaca_sym = symbol.replace("-", "/")
            with api_call_span("alpaca_data", "get_crypto_bars", symbol=symbol):
                resp = _crypto_client().get_crypto_bars(
                    CryptoBarsRequest(
                        symbol_or_symbols=alpaca_sym, timeframe=tf, start=start, end=end
                    )
                )
            lookup_key = alpaca_sym
        else:
            with api_call_span("alpaca_data", "get_stock_bars", symbol=symbol):
                resp = _data_client().get_stock_bars(
                    StockBarsRequest(
                        symbol_or_symbols=symbol, timeframe=tf, start=start, end=end, feed="iex"
                    )
                )
            lookup_key = symbol

        try:
            bar_list = resp[lookup_key]
        except (KeyError, TypeError):
            bar_list = []
    else:
        logger.info("get_ohlcv no Alpaca credentials, skipping to yfinance for %s", symbol)
    result = [
        {
            "timestamp": b.timestamp.isoformat(),
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": float(b.volume),
        }
        for b in bar_list[-bars:]
    ]

    if result:
        return OhlcvResponse(symbol=symbol, timeframe=timeframe, bars=result).model_dump()

    # IEX had no data — fall back to yfinance
    logger.info("get_ohlcv IEX empty for %s, falling back to yfinance", symbol)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    days_needed = bars * 2
    if days_needed <= 7:
        yf_period = "5d"
    elif days_needed <= 30:
        yf_period = "1mo"
    elif days_needed <= 90:
        yf_period = "3mo"
    else:
        yf_period = "1y"

    yf_interval = {
        "1Day": "1d",
        "12Hour": "1d",
        "4Hour": "1h",
        "3Hour": "1h",
        "1Hour": "1h",
        "30Min": "30m",
    }.get(timeframe, "1d")
    hist = yf.download(
        symbol, period=yf_period, interval=yf_interval, progress=False, auto_adjust=True
    )
    if hist.empty:
        return OhlcvResponse(symbol=symbol, timeframe=timeframe, bars=[]).model_dump()

    # yf.download returns MultiIndex columns even for a single symbol
    if hasattr(hist.columns, "nlevels") and hist.columns.nlevels > 1:
        hist.columns = hist.columns.get_level_values(0)

    ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
    hist = hist.dropna(subset=ohlcv_cols)

    result = []
    for idx, row in hist.tail(bars).iterrows():
        result.append(
            {
                "timestamp": idx.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            }
        )
    return OhlcvResponse(symbol=symbol, timeframe=timeframe, bars=result).model_dump()


@with_retry
async def get_52w_range(symbol: str) -> dict:
    """Fetch 52-week high/low range for a symbol.

    Args:
        symbol: Ticker symbol.

    Returns:
        dict with 'symbol', 'high_52w', 'low_52w', 'current_price', 'pct_from_high', 'pct_from_low'.
    """
    logger.info("get_52w_range symbol=%s", symbol)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    info = yf.Ticker(symbol).info
    high = float(info.get("fiftyTwoWeekHigh", 0))
    low = float(info.get("fiftyTwoWeekLow", 0))
    price = float(info.get("regularMarketPrice") or info.get("currentPrice", 0))
    return Range52wResponse(
        symbol=symbol,
        high_52w=high,
        low_52w=low,
        current_price=price,
        pct_from_high=round((price - high) / high * 100, 2) if high else 0.0,
        pct_from_low=round((price - low) / low * 100, 2) if low else 0.0,
    ).model_dump()

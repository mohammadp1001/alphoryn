"""market.* tools — 12 tools, analysis agent scope."""
from __future__ import annotations

import math
import os
from datetime import datetime, timedelta

from infra.observability import api_call_span, get_logger
from infra.rate_limiter import acquire_alpaca_data, acquire_yfinance
from infra.retry import with_retry

logger = get_logger("tools.market")


def _safe_float(v: float) -> float:
    """Replace NaN/Inf with 0.0 — JSON doesn't support these values."""
    return 0.0 if not math.isfinite(v) else v


def _data_client():
    from alpaca.data import StockHistoricalDataClient  # type: ignore[import]
    return StockHistoricalDataClient(
        api_key=os.environ.get("ALPACA_DATA_KEY") or os.environ.get("ALPACA_API_KEY"),
        secret_key=os.environ.get("ALPACA_DATA_SECRET") or os.environ.get("ALPACA_API_SECRET"),
    )


@with_retry
async def get_ohlcv(symbol: str, timeframe: str, bars: int) -> dict:
    """Fetch OHLCV bar history for an ETF.

    Args:
        symbol: Ticker symbol, e.g. 'XLK'.
        timeframe: Bar size — '1Day', '1Hour', '4Hour'.
        bars: Number of bars to return (most recent).

    Returns:
        dict with 'symbol', 'timeframe', and 'bars' (list of OHLCV dicts).
    """
    from alpaca.data.requests import StockBarsRequest  # type: ignore[import]
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit  # type: ignore[import]

    logger.info("get_ohlcv symbol=%s timeframe=%s bars=%d", symbol, timeframe, bars)
    tf_map = {"1Day": TimeFrame.Day, "1Hour": TimeFrame.Hour, "4Hour": TimeFrame(4, TimeFrameUnit.Hour)}
    tf = tf_map.get(timeframe, TimeFrame.Day)

    end = datetime.utcnow()
    start = end - timedelta(days=bars * 2)  # over-fetch, trim to bars

    await acquire_alpaca_data()
    with api_call_span("alpaca_data", "get_stock_bars", symbol=symbol):
        resp = _data_client().get_stock_bars(
            StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start, end=end, feed="iex")
        )

    bar_list = resp[symbol] if symbol in resp else []
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
    return {"symbol": symbol, "timeframe": timeframe, "bars": result}


@with_retry
async def get_quote(symbol: str) -> dict:
    """Fetch latest bid/ask quote for a symbol.

    Args:
        symbol: Ticker symbol.

    Returns:
        dict with 'symbol', 'bid', 'ask', 'bid_size', 'ask_size', 'timestamp'.
    """
    from alpaca.data.requests import StockLatestQuoteRequest  # type: ignore[import]

    logger.info("get_quote symbol=%s", symbol)
    await acquire_alpaca_data()
    with api_call_span("alpaca_data", "get_latest_quote", symbol=symbol):
        resp = _data_client().get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol, feed="iex"))

    q = resp[symbol]
    return {
        "symbol": symbol,
        "bid": float(q.bid_price),
        "ask": float(q.ask_price),
        "bid_size": float(q.bid_size),
        "ask_size": float(q.ask_size),
        "timestamp": q.timestamp.isoformat(),
    }


@with_retry
async def get_spread(symbol: str) -> dict:
    """Calculate bid-ask spread for a symbol.

    Args:
        symbol: Ticker symbol.

    Returns:
        dict with 'symbol', 'spread_abs', 'spread_pct', 'timestamp'.
    """
    logger.info("get_spread symbol=%s", symbol)
    quote = await get_quote(symbol)
    mid = (quote["bid"] + quote["ask"]) / 2
    spread_abs = quote["ask"] - quote["bid"]
    spread_pct = (spread_abs / mid * 100) if mid > 0 else 0.0
    return {
        "symbol": symbol,
        "spread_abs": round(spread_abs, 4),
        "spread_pct": round(spread_pct, 4),
        "timestamp": quote["timestamp"],
    }


@with_retry
async def get_order_book(symbol: str, depth: int) -> dict:
    """Fetch order book for a symbol.

    Args:
        symbol: Ticker symbol.
        depth: Number of price levels to return per side.

    Returns:
        dict with 'symbol', 'bids', 'asks' (each a list of {price, size}), 'timestamp'.
    """
    from alpaca.data.requests import StockLatestOrderbookRequest  # type: ignore[import]

    logger.info("get_order_book symbol=%s depth=%d", symbol, depth)
    await acquire_alpaca_data()
    with api_call_span("alpaca_data", "get_order_book", symbol=symbol):
        resp = _data_client().get_stock_latest_orderbook(
            StockLatestOrderbookRequest(symbol_or_symbols=symbol, feed="iex")
        )

    ob = resp[symbol]
    return {
        "symbol": symbol,
        "bids": [{"price": float(b.p), "size": float(b.s)} for b in ob.bids[:depth]],
        "asks": [{"price": float(a.p), "size": float(a.s)} for a in ob.asks[:depth]],
        "timestamp": ob.timestamp.isoformat(),
    }


async def screen_etfs(min_avg_volume: float, min_price: float, symbols: list[str] | None = None) -> dict:
    """Screen ETFs by volume and price filters.

    Args:
        min_avg_volume: Minimum 30-day average volume threshold.
        min_price: Minimum current price threshold.
        symbols: Explicit list of symbols to screen. Defaults to DEFAULT_ETF_UNIVERSE.

    Returns:
        dict with 'results' — list of {symbol, price, avg_volume_30d, ytd_return_pct, sector}.
    """
    logger.info("screen_etfs min_avg_volume=%s min_price=%s symbols=%s", min_avg_volume, min_price, symbols)
    if symbols is None:
        from config import DEFAULT_ETF_UNIVERSE
        symbols = DEFAULT_ETF_UNIVERSE

    results = []
    for symbol in symbols:
        try:
            await acquire_yfinance()
            import yfinance as yf  # type: ignore[import]
            ticker = yf.Ticker(symbol)
            info = ticker.info
            price = info.get("regularMarketPrice") or info.get("currentPrice", 0.0)
            avg_vol = info.get("averageVolume", 0)
            if price >= min_price and avg_vol >= min_avg_volume:
                results.append({
                    "symbol": symbol,
                    "price": float(price),
                    "avg_volume_30d": float(avg_vol),
                    "ytd_return_pct": float(info.get("52WeekChange", 0.0) * 100),
                    "sector": info.get("sector"),
                })
        except Exception:
            continue
    return {"results": results}


@with_retry
async def get_etf_holdings(symbol: str) -> dict:
    """Fetch top holdings for an ETF.

    Args:
        symbol: ETF ticker symbol.

    Returns:
        dict with 'symbol' and 'top_holdings' (list of {ticker, weight_pct, name}).
    """
    logger.info("get_etf_holdings symbol=%s", symbol)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    ticker = yf.Ticker(symbol)
    holdings = []
    try:
        df = ticker.funds_data.top_holdings
        for idx, row in df.iterrows():
            holdings.append({
                "ticker": str(idx),
                "weight_pct": float(row.get("Holding Percent", 0)) * 100,
                "name": str(row.get("Name", "")),
            })
    except Exception:
        pass
    return {"symbol": symbol, "top_holdings": holdings[:10]}


async def get_sector_map() -> dict:
    """Return the ETF-to-sector mapping for the default universe.

    Returns:
        dict with 'etf_to_sector' and 'sector_to_etfs' mappings.
    """
    logger.info("get_sector_map")
    etf_to_sector = {
        "XLK": "Technology", "XLE": "Energy", "XLF": "Financials",
        "XLV": "Healthcare", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
        "XLI": "Industrials", "XLB": "Materials", "XLU": "Utilities",
        "XLRE": "Real Estate", "XLC": "Communication Services",
        "SPY": "Broad Market", "QQQ": "Broad Market", "IWM": "Broad Market",
        "GLD": "Commodities", "TLT": "Fixed Income", "VNQ": "Real Estate",
    }
    sector_to_etfs: dict[str, list[str]] = {}
    for etf, sector in etf_to_sector.items():
        sector_to_etfs.setdefault(sector, []).append(etf)
    return {"etf_to_sector": etf_to_sector, "sector_to_etfs": sector_to_etfs}


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
    return {
        "symbol": symbol,
        "high_52w": high,
        "low_52w": low,
        "current_price": price,
        "pct_from_high": round((price - high) / high * 100, 2) if high else 0.0,
        "pct_from_low": round((price - low) / low * 100, 2) if low else 0.0,
    }


@with_retry
async def get_volume_profile(symbol: str, days: int) -> dict:
    """Compute volume profile (price level distribution) for recent trading days.

    Args:
        symbol: Ticker symbol.
        days: Number of trading days to analyse.

    Returns:
        dict with 'symbol', 'buckets' (list of {price_level, volume}), 'point_of_control', 'days'.
    """
    logger.info("get_volume_profile symbol=%s days=%d", symbol, days)
    ohlcv = await get_ohlcv(symbol, "1Day", days)
    import numpy as np  # type: ignore[import]

    closes = [b["close"] for b in ohlcv["bars"]]
    volumes = [b["volume"] for b in ohlcv["bars"]]
    if not closes:
        return {"symbol": symbol, "buckets": [], "point_of_control": 0.0, "days": days}

    bins = np.linspace(min(closes), max(closes), 20)
    bucket_vols = [0.0] * (len(bins) - 1)
    for c, v in zip(closes, volumes):
        idx = min(int(np.searchsorted(bins, c)), len(bucket_vols) - 1)
        bucket_vols[idx] += v

    poc = float(bins[int(np.argmax(bucket_vols))])
    buckets = [
        {"price_level": round(float((bins[i] + bins[i + 1]) / 2), 2), "volume": round(bucket_vols[i], 0)}
        for i in range(len(bucket_vols))
    ]
    return {"symbol": symbol, "buckets": buckets, "point_of_control": poc, "days": days}


@with_retry
async def get_benchmark_return(symbol: str, period: str) -> dict:
    """Compare symbol return against SPY benchmark for a period.

    Args:
        symbol: Ticker symbol.
        period: Period string — '1mo', '3mo', '6mo', '1y'.

    Returns:
        dict with 'symbol', 'benchmark', 'period', 'symbol_return_pct', 'benchmark_return_pct', 'excess_return_pct'.
    """
    logger.info("get_benchmark_return symbol=%s period=%s", symbol, period)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    hist = yf.download([symbol, "SPY"], period=period, progress=False)["Close"]
    if hist.empty:
        return {"symbol": symbol, "benchmark": "SPY", "period": period,
                "symbol_return_pct": 0.0, "benchmark_return_pct": 0.0, "excess_return_pct": 0.0}
    sym_ret = _safe_float(float((hist[symbol].iloc[-1] / hist[symbol].iloc[0] - 1) * 100))
    spy_ret = _safe_float(float((hist["SPY"].iloc[-1] / hist["SPY"].iloc[0] - 1) * 100))
    return {
        "symbol": symbol, "benchmark": "SPY", "period": period,
        "symbol_return_pct": round(sym_ret, 2),
        "benchmark_return_pct": round(spy_ret, 2),
        "excess_return_pct": round(sym_ret - spy_ret, 2),
    }


@with_retry
async def get_intraday_bars(symbol: str, resolution: str) -> dict:
    """Fetch intraday OHLCV bars for today.

    Args:
        symbol: Ticker symbol.
        resolution: Bar resolution — '1Min', '5Min', '15Min', '30Min', '1Hour'.

    Returns:
        dict with 'symbol', 'timeframe', and 'bars' (list of OHLCV dicts).
    """
    logger.info("get_intraday_bars symbol=%s resolution=%s", symbol, resolution)
    return await get_ohlcv(symbol, resolution, 100)


async def get_market_status() -> dict:
    """Check if US equities market is currently open.

    Returns:
        dict with 'is_open', 'next_open', 'next_close', 'timestamp'.
    """
    logger.info("get_market_status")
    from alpaca.trading.client import TradingClient  # type: ignore[import]

    api_key = os.environ.get("ALPACA_DATA_KEY") or os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_DATA_SECRET") or os.environ.get("ALPACA_API_SECRET")
    if not api_key:
        return {"is_open": False, "next_open": None, "next_close": None,
                "timestamp": datetime.utcnow().isoformat()}

    await acquire_alpaca_data()
    client = TradingClient(api_key, api_secret, paper=True)
    clock = client.get_clock()
    return {
        "is_open": clock.is_open,
        "next_open": clock.next_open.isoformat() if clock.next_open else None,
        "next_close": clock.next_close.isoformat() if clock.next_close else None,
        "timestamp": datetime.utcnow().isoformat(),
    }

"""market.* tools — 12 tools, analysis agent scope."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from infra.observability import api_call_span, get_logger
from infra.rate_limiter import acquire_alpaca_data, acquire_yfinance
from infra.retry import with_retry
from tools.schemas import (
    BenchmarkReturnResponse,
    EtfHoldingsResponse,
    IntradayBarsResponse,
    MarketStatusResponse,
    OhlcvResponse,
    OrderBookResponse,
    QuoteResponse,
    Range52wResponse,
    ScreenEtfsResponse,
    SectorMapResponse,
    SpreadResponse,
    VolumeProfileResponse,
)

logger = get_logger("tools.market")


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
        "1Day":   TimeFrame.Day,
        "30Min":  TimeFrame(30, TimeFrameUnit.Minute),
        "1Hour":  TimeFrame.Hour,
        "3Hour":  TimeFrame(3, TimeFrameUnit.Hour),
        "4Hour":  TimeFrame(4, TimeFrameUnit.Hour),
        "12Hour": TimeFrame(12, TimeFrameUnit.Hour),
    }
    tf = tf_map.get(timeframe, TimeFrame.Day)

    end = datetime.utcnow()
    start = end - timedelta(days=bars * 2)  # over-fetch, trim to bars

    await acquire_alpaca_data()
    if _is_crypto(symbol):
        from alpaca.data.requests import CryptoBarsRequest  # type: ignore[import]
        # Alpaca crypto API requires "BTC/USD" not "BTC-USD" (yfinance format)
        alpaca_sym = symbol.replace("-", "/")
        with api_call_span("alpaca_data", "get_crypto_bars", symbol=symbol):
            resp = _crypto_client().get_crypto_bars(
                CryptoBarsRequest(symbol_or_symbols=alpaca_sym, timeframe=tf, start=start, end=end)
            )
        lookup_key = alpaca_sym
    else:
        with api_call_span("alpaca_data", "get_stock_bars", symbol=symbol):
            resp = _data_client().get_stock_bars(
                StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start, end=end, feed="iex")
            )
        lookup_key = symbol

    try:
        bar_list = resp[lookup_key]
    except (KeyError, TypeError):
        bar_list = []
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
        "1Day": "1d", "12Hour": "1d",
        "4Hour": "1h", "3Hour": "1h",
        "1Hour": "1h", "30Min": "30m",
    }.get(timeframe, "1d")
    hist = yf.download(symbol, period=yf_period, interval=yf_interval, progress=False, auto_adjust=True)
    if hist.empty:
        return OhlcvResponse(symbol=symbol, timeframe=timeframe, bars=[]).model_dump()

    # yf.download returns MultiIndex columns ('Open', '<SYM>') even for a single symbol
    if hasattr(hist.columns, "nlevels") and hist.columns.nlevels > 1:
        hist.columns = hist.columns.get_level_values(0)

    ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
    hist = hist.dropna(subset=ohlcv_cols)

    result = []
    for idx, row in hist.tail(bars).iterrows():
        result.append({
            "timestamp": idx.isoformat(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"]),
        })
    return OhlcvResponse(symbol=symbol, timeframe=timeframe, bars=result).model_dump()


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
    return QuoteResponse(
        symbol=symbol,
        bid=float(q.bid_price),
        ask=float(q.ask_price),
        bid_size=float(q.bid_size),
        ask_size=float(q.ask_size),
        timestamp=q.timestamp.isoformat(),
    ).model_dump()


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
    return SpreadResponse(
        symbol=symbol,
        spread_abs=round(spread_abs, 4),
        spread_pct=round(spread_pct, 4),
        timestamp=quote["timestamp"],
    ).model_dump()


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
    return OrderBookResponse(
        symbol=symbol,
        bids=[{"price": float(b.p), "size": float(b.s)} for b in ob.bids[:depth]],
        asks=[{"price": float(a.p), "size": float(a.s)} for a in ob.asks[:depth]],
        timestamp=ob.timestamp.isoformat(),
    ).model_dump()


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
                    "sector": info.get("sector") or "Unknown",
                })
        except Exception:
            continue
    return ScreenEtfsResponse(results=results).model_dump()


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
    return EtfHoldingsResponse(symbol=symbol, top_holdings=holdings[:10]).model_dump()


async def get_sector_map(symbols: list[str] | None = None) -> dict:
    """Return the ETF-to-sector mapping for a symbol list or the default US universe.

    Args:
        symbols: Explicit list of ETF symbols to map. When omitted, uses the hardcoded
            US sector mapping (XL* ETFs + common broad-market / commodity tickers).

    Returns:
        dict with 'etf_to_sector' and 'sector_to_etfs' mappings.
    """
    logger.info("get_sector_map symbols=%s", symbols)
    if symbols is None:
        etf_to_sector: dict[str, str] = {
            "XLK": "Technology", "XLE": "Energy", "XLF": "Financials",
            "XLV": "Healthcare", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
            "XLI": "Industrials", "XLB": "Materials", "XLU": "Utilities",
            "XLRE": "Real Estate", "XLC": "Communication Services",
            "SPY": "Broad Market", "QQQ": "Broad Market", "IWM": "Broad Market",
            "GLD": "Commodities", "TLT": "Fixed Income", "VNQ": "Real Estate",
        }
    else:
        await acquire_yfinance()
        import yfinance as yf  # type: ignore[import]
        etf_to_sector = {}
        for sym in symbols:
            try:
                sector = yf.Ticker(sym).info.get("sector") or "Unknown"
            except Exception:
                sector = "Unknown"
            etf_to_sector[sym] = sector

    sector_to_etfs: dict[str, list[str]] = {}
    for etf, sector in etf_to_sector.items():
        sector_to_etfs.setdefault(sector, []).append(etf)
    return SectorMapResponse(etf_to_sector=etf_to_sector, sector_to_etfs=sector_to_etfs).model_dump()


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
        return VolumeProfileResponse(symbol=symbol, buckets=[], point_of_control=0.0, days=days).model_dump()

    bins = np.linspace(min(closes), max(closes), 20)
    bucket_vols = [0.0] * (len(bins) - 1)
    for c, v in zip(closes, volumes, strict=False):
        idx = min(int(np.searchsorted(bins, c)), len(bucket_vols) - 1)
        bucket_vols[idx] += v

    poc = float(bins[int(np.argmax(bucket_vols))])
    buckets = [
        {"price_level": round(float((bins[i] + bins[i + 1]) / 2), 2), "volume": round(bucket_vols[i], 0)}
        for i in range(len(bucket_vols))
    ]
    return VolumeProfileResponse(symbol=symbol, buckets=buckets, point_of_control=poc, days=days).model_dump()


@with_retry
async def get_benchmark_return(symbol: str, period: str, benchmark: str = "SPY") -> dict:
    """Compare symbol return against a benchmark for a period.

    Args:
        symbol: Ticker symbol.
        period: Period string — '1mo', '3mo', '6mo', '1y'.
        benchmark: Benchmark ticker to compare against. Defaults to 'SPY'.
            Use 'EZU' for EU markets, 'EWG' for German market, 'EFA' for international
            developed, 'EEM' for emerging markets, 'GLD' for commodities, 'TLT' for fixed income.

    Returns:
        dict with 'symbol', 'benchmark', 'period', 'symbol_return_pct', 'benchmark_return_pct', 'excess_return_pct'.
    """
    logger.info("get_benchmark_return symbol=%s period=%s benchmark=%s", symbol, period, benchmark)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    tickers = [symbol] if symbol == benchmark else [symbol, benchmark]
    hist = yf.download(tickers, period=period, progress=False)["Close"]
    if hist.empty:
        return BenchmarkReturnResponse(
            symbol=symbol, benchmark=benchmark, period=period,
            symbol_return_pct=0.0, benchmark_return_pct=0.0, excess_return_pct=0.0,
        ).model_dump()
    sym_ret = float((hist[symbol].iloc[-1] / hist[symbol].iloc[0] - 1) * 100)
    bench_ret = 0.0 if symbol == benchmark else float(
        (hist[benchmark].iloc[-1] / hist[benchmark].iloc[0] - 1) * 100
    )
    return BenchmarkReturnResponse(
        symbol=symbol, benchmark=benchmark, period=period,
        symbol_return_pct=round(sym_ret, 2),
        benchmark_return_pct=round(bench_ret, 2),
        excess_return_pct=round(sym_ret - bench_ret, 2),
    ).model_dump()


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
    ohlcv = await get_ohlcv(symbol, resolution, 100)
    return IntradayBarsResponse(
        symbol=ohlcv["symbol"], timeframe=ohlcv["timeframe"], bars=ohlcv["bars"]
    ).model_dump()


async def get_market_status(timezone: str = "America/New_York") -> dict:
    """Check if the relevant exchange is currently open.

    Dispatch rules (by timezone, which maps 1-to-1 with UNIVERSE_EXCHANGE_TZ):
      - 'UTC'           → crypto universe, trades 24/7, always open.
      - 'Europe/Berlin' → XETRA (Frankfurt), Mon-Fri 09:00-17:30 CET/CEST.
      - anything else   → Alpaca NYSE/NASDAQ clock.

    Args:
        timezone: IANA timezone name — passed from UNIVERSE_EXCHANGE_TZ config.

    Returns:
        dict with 'is_open', 'next_open', 'next_close', 'timestamp', 'timezone'.
    """
    logger.info("get_market_status timezone=%s", timezone)
    from datetime import time as dtime

    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("America/New_York")

    now_dt = datetime.now(tz)
    now_local = now_dt.isoformat()

    # ── Crypto (UTC) — 24/7, never closes ────────────────────────────────────
    if timezone == "UTC":
        return MarketStatusResponse(
            is_open=True, next_open=None, next_close=None,
            timestamp=now_local, timezone=timezone,
        ).model_dump()

    # ── European / XETRA (Berlin) — Mon-Fri 09:00-17:30 CET/CEST ─────────────
    if timezone == "Europe/Berlin":
        open_t = dtime(9, 0)
        close_t = dtime(17, 30)
        wd = now_dt.weekday()   # 0=Mon … 6=Sun
        t = now_dt.time()
        is_open = wd < 5 and open_t <= t < close_t

        def _xetra_next_open(ref: datetime) -> str:
            d = ref.date()
            if ref.weekday() < 5 and ref.time() < open_t:
                pass  # today's open hasn't arrived yet
            else:
                d += timedelta(days=1)
                while d.weekday() >= 5:
                    d += timedelta(days=1)
            return datetime(d.year, d.month, d.day, 9, 0, tzinfo=tz).isoformat()

        def _xetra_next_close(ref: datetime) -> str:
            d = ref.date()
            if ref.weekday() < 5 and ref.time() < close_t:
                pass  # today's close hasn't arrived yet
            else:
                d += timedelta(days=1)
                while d.weekday() >= 5:
                    d += timedelta(days=1)
            return datetime(d.year, d.month, d.day, 17, 30, tzinfo=tz).isoformat()

        return MarketStatusResponse(
            is_open=is_open,
            next_open=_xetra_next_open(now_dt),
            next_close=_xetra_next_close(now_dt),
            timestamp=now_local,
            timezone=timezone,
        ).model_dump()

    # ── US and all other markets — Alpaca NYSE clock ──────────────────────────
    from alpaca.trading.client import TradingClient  # type: ignore[import]

    api_key = os.environ.get("ALPACA_DATA_KEY") or os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_DATA_SECRET") or os.environ.get("ALPACA_API_SECRET")
    if not api_key:
        return MarketStatusResponse(
            is_open=False, next_open=None, next_close=None,
            timestamp=now_local, timezone=timezone,
        ).model_dump()

    await acquire_alpaca_data()
    client = TradingClient(api_key, api_secret, paper=True)
    clock = client.get_clock()

    def _to_tz(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(tz).isoformat()

    return MarketStatusResponse(
        is_open=clock.is_open,
        next_open=_to_tz(clock.next_open),
        next_close=_to_tz(clock.next_close),
        timestamp=now_local,
        timezone=timezone,
    ).model_dump()

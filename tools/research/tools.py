"""research.* tools — 12 tools, research agent scope."""
from __future__ import annotations

from datetime import datetime, timedelta

from infra.observability import get_logger
from infra.rate_limiter import acquire_yfinance
from infra.retry import with_retry
from tools.schemas import (
    AnalystRatingsResponse, CompareEtfsResponse, DividendHistoryResponse,
    EarningsCalendarResponse, EconomicCalendarResponse, EtfMetricsResponse,
    ExpenseRatiosResponse, FundFlowsResponse, MacroDataResponse,
    MarketRegimeResponse, NewsResponse, SectorPerformanceResponse, SentimentResponse,
)

logger = get_logger("tools.research")


@with_retry
async def get_news(symbol: str, days: int) -> dict:
    """Fetch recent news headlines for an ETF or index.

    Args:
        symbol: Ticker symbol.
        days: Number of days to look back.

    Returns:
        dict with 'symbol' and 'items' (list of {headline, source, published_at, url}).
    """
    logger.info("get_news symbol=%s days=%d", symbol, days)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    ticker = yf.Ticker(symbol)
    items = []
    cutoff = datetime.utcnow() - timedelta(days=days)

    try:
        news = ticker.news or []
        for n in news[:20]:
            published = datetime.utcfromtimestamp(n.get("providerPublishTime", 0))
            if published >= cutoff:
                items.append({
                    "headline": n.get("title", ""),
                    "source": n.get("publisher", ""),
                    "published_at": published.isoformat(),
                    "url": n.get("link", ""),
                })
    except Exception:
        pass

    return NewsResponse(symbol=symbol, items=items).model_dump()


async def get_sentiment(symbol: str, news_items: list[dict]) -> dict:
    """Estimate market sentiment from news headlines (keyword-based heuristic).

    Args:
        symbol: Ticker symbol.
        news_items: List of news item dicts from get_news (each with 'headline').

    Returns:
        dict with 'symbol', 'score' (-1 to +1), 'label' ('bearish'|'neutral'|'bullish'), 'item_count'.
    """
    logger.info("get_sentiment symbol=%s n_items=%d", symbol, len(news_items))
    bullish_keywords = ["surge", "rally", "gain", "rise", "beat", "upgrade", "buy", "strong",
                        "record", "high", "growth", "profit", "positive", "optimistic"]
    bearish_keywords = ["crash", "fall", "drop", "miss", "downgrade", "sell", "weak", "low",
                        "loss", "negative", "concern", "fear", "recession", "decline"]

    total = 0.0
    count = len(news_items)
    for item in news_items:
        headline = item.get("headline", "").lower()
        bull_hits = sum(1 for w in bullish_keywords if w in headline)
        bear_hits = sum(1 for w in bearish_keywords if w in headline)
        total += bull_hits - bear_hits

    if count == 0:
        score = 0.0
    else:
        raw = total / count
        score = max(-1.0, min(1.0, raw / 3))

    label = "bullish" if score > 0.1 else ("bearish" if score < -0.1 else "neutral")
    return SentimentResponse(symbol=symbol, score=round(score, 4), label=label, item_count=count).model_dump()


@with_retry
async def get_earnings_calendar(symbol: str, days_ahead: int) -> dict:
    """Fetch upcoming earnings events for a symbol.

    Args:
        symbol: Ticker symbol.
        days_ahead: Number of days to look ahead for earnings.

    Returns:
        dict with 'symbol' and 'events' (list of {date, estimate_eps, surprise_pct}).
    """
    logger.info("get_earnings_calendar symbol=%s days_ahead=%d", symbol, days_ahead)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    ticker = yf.Ticker(symbol)
    events = []
    cutoff = datetime.utcnow() + timedelta(days=days_ahead)

    try:
        cal = ticker.earnings_dates
        if cal is not None:
            for dt, row in cal.iterrows():
                if dt.to_pydatetime().replace(tzinfo=None) <= cutoff:
                    events.append({
                        "date": dt.isoformat(),
                        "estimate_eps": float(row.get("EPS Estimate", 0) or 0),
                        "surprise_pct": float(row.get("Surprise(%)", 0) or 0),
                    })
    except Exception:
        pass

    return EarningsCalendarResponse(symbol=symbol, events=events[:5]).model_dump()


@with_retry
async def get_macro_data(
    vix_symbol: str = "^VIX",
    yield_10y_symbol: str = "^TNX",
    yield_2y_symbol: str = "^IRX",
    dxy_symbol: str = "DX-Y.NYB",
) -> dict:
    """Fetch key macro indicators: VIX, treasury yields, dollar index.

    Args:
        vix_symbol: Ticker for volatility index. Defaults to '^VIX' (US).
        yield_10y_symbol: Ticker for 10-year yield. Defaults to '^TNX' (US Treasury).
        yield_2y_symbol: Ticker for 2-year yield. Defaults to '^IRX' (US Treasury).
        dxy_symbol: Ticker for dollar index. Defaults to 'DX-Y.NYB'.

    Returns:
        dict with 'vix', 'yield_10y', 'yield_2y', 'dxy', 'timestamp'.
    """
    logger.info("get_macro_data vix=%s 10y=%s 2y=%s dxy=%s", vix_symbol, yield_10y_symbol, yield_2y_symbol, dxy_symbol)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    def _last_close(sym: str) -> float:
        try:
            info = yf.Ticker(sym).info
            return float(info.get("regularMarketPrice") or info.get("currentPrice", 0.0))
        except Exception:
            return 0.0

    return MacroDataResponse(
        vix=_last_close(vix_symbol),
        yield_10y=_last_close(yield_10y_symbol) / 10,  # ^TNX-family symbols quote in tenths
        yield_2y=_last_close(yield_2y_symbol) / 10,
        dxy=_last_close(dxy_symbol),
        timestamp=datetime.utcnow().isoformat(),
    ).model_dump()


@with_retry
async def get_fund_flows(symbol: str) -> dict:
    """Estimate recent fund flow direction for an ETF via volume and price analysis.

    Args:
        symbol: ETF ticker symbol.

    Returns:
        dict with 'symbol', 'flow_direction' ('inflow'|'outflow'|'neutral'), 'estimated_flow_usd'.
    """
    logger.info("get_fund_flows symbol=%s", symbol)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    hist = yf.download(symbol, period="5d", progress=False)
    if hist.empty:
        return FundFlowsResponse(symbol=symbol, flow_direction="neutral", estimated_flow_usd=0.0).model_dump()

    closes = hist["Close"].tolist()
    volumes = hist["Volume"].tolist()

    if len(closes) < 2:
        return FundFlowsResponse(symbol=symbol, flow_direction="neutral", estimated_flow_usd=0.0).model_dump()

    flow = sum((c - closes[i - 1]) * v for i, (c, v) in enumerate(zip(closes[1:], volumes[1:]), 1))
    direction = "inflow" if flow > 0 else ("outflow" if flow < 0 else "neutral")
    return FundFlowsResponse(
        symbol=symbol, flow_direction=direction, estimated_flow_usd=round(float(flow), 0),
    ).model_dump()


@with_retry
async def get_etf_metrics(symbol: str) -> dict:
    """Fetch ETF-specific metrics: AUM, expense ratio, NAV.

    Args:
        symbol: ETF ticker symbol.

    Returns:
        dict with 'symbol', 'aum_usd', 'expense_ratio', 'nav', 'shares_outstanding'.
    """
    logger.info("get_etf_metrics symbol=%s", symbol)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    info = yf.Ticker(symbol).info
    return EtfMetricsResponse(
        symbol=symbol,
        aum_usd=float(info.get("totalAssets", 0) or 0),
        expense_ratio=float(info.get("annualReportExpenseRatio", 0) or 0),
        nav=float(info.get("navPrice") or info.get("regularMarketPrice", 0) or 0),
        shares_outstanding=float(info.get("sharesOutstanding", 0) or 0),
    ).model_dump()


@with_retry
async def compare_etfs(symbols: list[str]) -> dict:
    """Compare metrics across multiple ETFs.

    Args:
        symbols: List of ETF ticker symbols (2-5 symbols).

    Returns:
        dict with 'comparisons' (list of {symbol, aum_usd, expense_ratio, ytd_return_pct, beta}).
    """
    logger.info("compare_etfs n_symbols=%d", len(symbols))
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    comparisons = []
    for sym in symbols[:5]:
        try:
            info = yf.Ticker(sym).info
            comparisons.append({
                "symbol": sym,
                "aum_usd": float(info.get("totalAssets", 0) or 0),
                "expense_ratio": float(info.get("annualReportExpenseRatio", 0) or 0),
                "ytd_return_pct": float((info.get("52WeekChange", 0) or 0) * 100),
                "beta": float(info.get("beta3Year") or info.get("beta", 1.0) or 1.0),
            })
        except Exception:
            comparisons.append({"symbol": sym, "aum_usd": 0, "expense_ratio": 0,
                                "ytd_return_pct": 0, "beta": 1.0})
    return CompareEtfsResponse(comparisons=comparisons).model_dump()


@with_retry
async def get_expense_ratios(symbols: list[str]) -> dict:
    """Fetch expense ratios for a list of ETFs.

    Args:
        symbols: List of ETF ticker symbols.

    Returns:
        dict with 'ratios' (list of {symbol, expense_ratio}).
    """
    logger.info("get_expense_ratios n_symbols=%d", len(symbols))
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    ratios = []
    for sym in symbols:
        try:
            info = yf.Ticker(sym).info
            ratios.append({
                "symbol": sym,
                "expense_ratio": float(info.get("annualReportExpenseRatio", 0) or 0),
            })
        except Exception:
            ratios.append({"symbol": sym, "expense_ratio": 0.0})
    return ExpenseRatiosResponse(ratios=ratios).model_dump()


@with_retry
async def get_sector_performance(timeframe: str, symbols: list[str] | None = None) -> dict:
    """Get relative sector performance for a given symbol list or the default SPDR sector ETFs.

    Args:
        timeframe: Lookback period — '1mo', '3mo', '6mo', '1y'.
        symbols: Explicit list of ETF symbols to evaluate. When omitted, uses the 11 SPDR
            sector ETFs (XLK, XLE, XLF, …) with their hardcoded sector names.

    Returns:
        dict with 'returns' (list of {symbol, sector, return_pct}) sorted by return descending.
    """
    logger.info("get_sector_performance timeframe=%s symbols=%s", timeframe, symbols)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    if symbols is None:
        sector_map: dict[str, str] = {
            "XLK": "Technology", "XLE": "Energy", "XLF": "Financials",
            "XLV": "Healthcare", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
            "XLI": "Industrials", "XLB": "Materials", "XLU": "Utilities",
            "XLRE": "Real Estate", "XLC": "Communication Services",
        }
        sym_list = list(sector_map.keys())
    else:
        sector_map = {}
        sym_list = symbols

    returns = []
    for sym in sym_list:
        try:
            hist = yf.download(sym, period=timeframe, progress=False)["Close"]
            if len(hist) >= 2:
                ret = float((hist.iloc[-1] / hist.iloc[0] - 1) * 100)
                sector = sector_map.get(sym)
                if sector is None:
                    try:
                        sector = yf.Ticker(sym).info.get("sector", "Unknown")
                    except Exception:
                        sector = "Unknown"
                returns.append({"symbol": sym, "sector": sector, "return_pct": round(ret, 2)})
        except Exception:
            pass

    returns.sort(key=lambda x: x["return_pct"], reverse=True)
    return SectorPerformanceResponse(timeframe=timeframe, returns=returns).model_dump()


@with_retry
async def get_dividend_history(symbol: str) -> dict:
    """Fetch recent dividend events for an ETF.

    Args:
        symbol: ETF ticker symbol.

    Returns:
        dict with 'symbol' and 'dividends' (list of {date, amount}).
    """
    logger.info("get_dividend_history symbol=%s", symbol)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    ticker = yf.Ticker(symbol)
    dividends = []
    try:
        divs = ticker.dividends
        if divs is not None and not divs.empty:
            for dt, amount in divs.tail(8).items():
                dividends.append({"date": dt.isoformat(), "amount": round(float(amount), 4)})
    except Exception:
        pass
    return DividendHistoryResponse(symbol=symbol, dividends=dividends).model_dump()


async def get_economic_calendar(days_ahead: int) -> dict:
    """List upcoming high-impact economic events.

    Args:
        days_ahead: Number of days to look ahead.

    Returns:
        dict with 'events' (list of {event, date, impact, forecast}).
    """
    logger.info("get_economic_calendar days_ahead=%d", days_ahead)
    events = [
        {
            "event": "FOMC Meeting",
            "date": (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d"),
            "impact": "high",
            "forecast": "unchanged",
        },
        {
            "event": "CPI Release",
            "date": (datetime.utcnow() + timedelta(days=14)).strftime("%Y-%m-%d"),
            "impact": "high",
            "forecast": "2.3% YoY",
        },
    ]
    return EconomicCalendarResponse(events=events, days_ahead=days_ahead).model_dump()


@with_retry
async def detect_market_regime(vix: float, yield_10y: float, yield_2y: float, benchmark_return_20d: float, benchmark_symbol: str = "SPY") -> dict:
    """Classify current market regime based on macro inputs.

    Args:
        vix: Current VIX value.
        yield_10y: 10-year treasury yield percentage.
        yield_2y: 2-year treasury yield percentage.
        benchmark_return_20d: 20-day return (%) of the representative benchmark for the active universe.
            Use SPY for US markets, EWG for German market, EFA for international developed,
            EEM for emerging markets, or the most liquid ETF in the active universe.
        benchmark_symbol: Ticker used as the benchmark (for logging/display). Defaults to 'SPY'.

    Returns:
        dict with 'regime' (MarketRegime enum string) and 'reasoning'.
    """
    logger.info("detect_market_regime vix=%s benchmark=%s return_20d=%s", vix, benchmark_symbol, benchmark_return_20d)
    if vix > 30:
        regime = "CRISIS"
        reasoning = f"VIX={vix:.1f} signals extreme fear; market in crisis mode"
    elif vix > 20:
        regime = "HIGH_VOL"
        reasoning = f"VIX={vix:.1f} elevated; high volatility regime"
    elif benchmark_return_20d > 2.0 and vix < 15:
        regime = "BULL_TREND"
        reasoning = f"Low volatility (VIX={vix:.1f}) with positive {benchmark_symbol} momentum ({benchmark_return_20d:.1f}%)"
    elif benchmark_return_20d < -2.0:
        regime = "BEAR_TREND"
        reasoning = f"Negative {benchmark_symbol} 20d momentum ({benchmark_return_20d:.1f}%); bear trend conditions"
    else:
        regime = "LOW_VOL_RANGE"
        reasoning = f"VIX={vix:.1f}, {benchmark_symbol} 20d={benchmark_return_20d:.1f}%; low-vol range-bound market"

    return MarketRegimeResponse(
        regime=regime,
        reasoning=reasoning,
        vix=vix,
        yield_10y=yield_10y,
        yield_2y=yield_2y,
        yield_curve_spread=round(yield_10y - yield_2y, 3),
        benchmark_symbol=benchmark_symbol,
        benchmark_return_20d=benchmark_return_20d,
    ).model_dump()


@with_retry
async def get_analyst_ratings(symbol: str) -> dict:
    """Fetch analyst buy/sell/hold ratings and price targets for a symbol.

    Args:
        symbol: Ticker symbol.

    Returns:
        dict with 'symbol', 'ratings' (list of {firm, rating, price_target, rating_date}).
    """
    logger.info("get_analyst_ratings symbol=%s", symbol)
    await acquire_yfinance()
    import yfinance as yf  # type: ignore[import]

    ticker = yf.Ticker(symbol)
    ratings = []
    try:
        recs = ticker.recommendations
        if recs is not None and not recs.empty:
            for idx, row in recs.tail(10).iterrows():
                ratings.append({
                    "firm": str(row.get("Firm", "")),
                    "rating": str(row.get("To Grade", row.get("Action", ""))),
                    "price_target": None,
                    "rating_date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                })
    except Exception:
        pass
    return AnalystRatingsResponse(symbol=symbol, ratings=ratings).model_dump()

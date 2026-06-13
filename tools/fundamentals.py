"""tools.fundamentals — ETF fundamentals tools used by the sector-rotation workflow."""

from __future__ import annotations

from infra.observability import get_logger
from infra.rate_limiter import acquire_yfinance
from infra.retry import with_retry
from tools.schemas import EtfMetricsResponse, FundFlowsResponse, SectorPerformanceResponse

logger = get_logger("tools.fundamentals")


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
        return FundFlowsResponse(
            symbol=symbol, flow_direction="neutral", estimated_flow_usd=0.0
        ).model_dump()

    closes = hist["Close"].tolist()
    volumes = hist["Volume"].tolist()

    if len(closes) < 2:
        return FundFlowsResponse(
            symbol=symbol, flow_direction="neutral", estimated_flow_usd=0.0
        ).model_dump()

    flow = sum(
        (c - closes[i - 1]) * v
        for i, (c, v) in enumerate(zip(closes[1:], volumes[1:], strict=False), 1)
    )
    direction = "inflow" if flow > 0 else ("outflow" if flow < 0 else "neutral")
    return FundFlowsResponse(
        symbol=symbol,
        flow_direction=direction,
        estimated_flow_usd=round(float(flow), 0),
    ).model_dump()


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
            "XLK": "Technology",
            "XLE": "Energy",
            "XLF": "Financials",
            "XLV": "Healthcare",
            "XLY": "Consumer Discretionary",
            "XLP": "Consumer Staples",
            "XLI": "Industrials",
            "XLB": "Materials",
            "XLU": "Utilities",
            "XLRE": "Real Estate",
            "XLC": "Communication Services",
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

"""tools.news — news fetching tool used by the research agent."""

from __future__ import annotations

from datetime import datetime, timedelta

from infra.observability import get_logger
from infra.rate_limiter import acquire_yfinance
from infra.retry import with_retry
from tools.schemas import NewsResponse

logger = get_logger("tools.news")


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
                items.append(
                    {
                        "headline": n.get("title", ""),
                        "source": n.get("publisher", ""),
                        "published_at": published.isoformat(),
                        "url": n.get("link", ""),
                    }
                )
    except Exception:
        pass

    return NewsResponse(symbol=symbol, items=items).model_dump()

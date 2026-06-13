"""Unit tests for tools.news — get_news."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def test_get_news_returns_expected_keys():
    now_ts = int(datetime.now(UTC).timestamp())
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.news = [
        {
            "title": "ETF rallies",
            "publisher": "Reuters",
            "providerPublishTime": now_ts,
            "link": "https://example.com/1",
        }
    ]
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.news import get_news

        result = asyncio.run(get_news("SPY", days=7))

    assert result["symbol"] == "SPY"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["headline"] == "ETF rallies"
    assert item["source"] == "Reuters"
    assert "published_at" in item
    assert "url" in item


def test_get_news_filters_old_articles():
    old_ts = 1_000_000  # very old timestamp
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.news = [
        {
            "title": "Old news",
            "publisher": "Old Source",
            "providerPublishTime": old_ts,
            "link": "https://example.com/old",
        }
    ]
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.news import get_news

        result = asyncio.run(get_news("SPY", days=7))

    assert result["items"] == []


def test_get_news_empty_when_no_news():
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.news = []
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.news import get_news

        result = asyncio.run(get_news("XLK", days=3))

    assert result["symbol"] == "XLK"
    assert result["items"] == []


def test_get_news_exception_returns_empty():
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.news = None  # None → news or [] → empty list, no exception
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.news import get_news

        result = asyncio.run(get_news("SPY", days=7))

    assert result["items"] == []


def test_get_news_exception_in_try_block_returns_empty():
    from unittest.mock import PropertyMock

    mock_yf = MagicMock()
    mock_ticker = MagicMock()
    type(mock_ticker).news = PropertyMock(side_effect=RuntimeError("API down"))
    mock_yf.Ticker.return_value = mock_ticker
    with (
        patch("infra.rate_limiter.acquire_yfinance", new_callable=AsyncMock),
        patch.dict(sys.modules, {"yfinance": mock_yf}),
    ):
        from tools.news import get_news

        result = asyncio.run(get_news("SPY", days=7))

    assert result["items"] == []

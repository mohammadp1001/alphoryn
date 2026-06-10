"""Unit tests for tools.research.tools — 13 research tools."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_acquire():
    return patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock())


# ── get_news ──────────────────────────────────────────────────────────────────

def test_get_news_returns_items():
    ts = int(datetime.now(timezone.utc).timestamp())
    mock_news = [
        {"title": "XLK surges on AI news", "publisher": "Reuters",
         "providerPublishTime": ts, "link": "http://example.com"},
    ]
    mock_ticker = MagicMock()
    mock_ticker.news = mock_news

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_news
            result = asyncio.run(get_news("XLK", 7))

    assert result["symbol"] == "XLK"
    assert len(result["items"]) == 1
    assert result["items"][0]["headline"] == "XLK surges on AI news"


def test_get_news_filters_old_items():
    old_ts = 0  # 1970 = way before any window
    mock_news = [
        {"title": "Old news", "publisher": "Old", "providerPublishTime": old_ts, "link": ""},
    ]
    mock_ticker = MagicMock()
    mock_ticker.news = mock_news

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_news
            result = asyncio.run(get_news("XLK", 7))

    assert result["items"] == []


def test_get_news_empty_news():
    mock_ticker = MagicMock()
    mock_ticker.news = []

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_news
            result = asyncio.run(get_news("SPY", 3))

    assert result["symbol"] == "SPY"
    assert result["items"] == []


def test_get_news_exception_returns_empty():
    mock_ticker = MagicMock()
    mock_ticker.news = None  # triggers exception in iteration

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_news
            result = asyncio.run(get_news("GLD", 5))

    assert result["symbol"] == "GLD"
    assert result["items"] == []


def test_get_news_loop_exception_triggers_except_pass():
    """
    A news item that causes an exception inside the for-loop body
    triggers the `except Exception: pass` block (lines 39-40).
    """
    ts = int(datetime.now(timezone.utc).timestamp())
    # providerPublishTime is a string that int() rejects → triggers utcfromtimestamp error
    bad_news = [
        {"title": "Bad item", "publisher": "X",
         "providerPublishTime": "not-a-number", "link": ""},
    ]
    mock_ticker = MagicMock()
    mock_ticker.news = bad_news

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_news
            result = asyncio.run(get_news("VIX", 7))

    assert result["symbol"] == "VIX"
    assert result["items"] == []  # exception swallowed → empty


# ── get_sentiment ─────────────────────────────────────────────────────────────

def test_get_sentiment_bullish():
    news = [{"headline": "XLK surges to record high on strong growth profit rally"}]
    from tools.research.tools import get_sentiment
    result = asyncio.run(get_sentiment("XLK", news))
    assert result["label"] == "bullish"
    assert result["score"] > 0.1


def test_get_sentiment_bearish():
    news = [{"headline": "XLF crashes on fear of recession loss decline weakness"}]
    from tools.research.tools import get_sentiment
    result = asyncio.run(get_sentiment("XLF", news))
    assert result["label"] == "bearish"
    assert result["score"] < -0.1


def test_get_sentiment_neutral():
    news = [{"headline": "ETF shows stable performance in mixed trading session"}]
    from tools.research.tools import get_sentiment
    result = asyncio.run(get_sentiment("SPY", news))
    assert result["label"] == "neutral"


def test_get_sentiment_no_items():
    from tools.research.tools import get_sentiment
    result = asyncio.run(get_sentiment("QQQ", []))
    assert result["score"] == 0.0
    assert result["label"] == "neutral"
    assert result["item_count"] == 0


def test_get_sentiment_multiple_items():
    news = [
        {"headline": "rally surge gain buy"},
        {"headline": "crash fear loss sell"},
        {"headline": "neutral"},
    ]
    from tools.research.tools import get_sentiment
    result = asyncio.run(get_sentiment("IWM", news))
    assert result["item_count"] == 3
    assert -1.0 <= result["score"] <= 1.0


# ── get_earnings_calendar ─────────────────────────────────────────────────────

def _make_mock_cal_row(future_date: datetime):
    """Build a mock DataFrame-like object for earnings_dates without real pandas."""
    mock_row = MagicMock()
    mock_row.get = lambda key, default=0: {
        "EPS Estimate": 1.5, "Surprise(%)": 5.0
    }.get(key, default)

    mock_dt = MagicMock()
    mock_dt.isoformat.return_value = future_date.isoformat()
    # to_pydatetime().replace(tzinfo=None) must return a naive datetime in the future
    mock_py_dt = MagicMock()
    mock_py_dt.replace.return_value = future_date.replace(tzinfo=None)
    mock_dt.to_pydatetime.return_value = mock_py_dt

    mock_cal = MagicMock()
    mock_cal.iterrows.return_value = iter([(mock_dt, mock_row)])
    return mock_cal


def test_get_earnings_calendar_with_future_event():
    future_date = datetime.now(timezone.utc) + timedelta(days=5)
    mock_cal = _make_mock_cal_row(future_date)

    mock_ticker = MagicMock()
    mock_ticker.earnings_dates = mock_cal

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_earnings_calendar
            result = asyncio.run(get_earnings_calendar("AAPL", 30))

    assert result["symbol"] == "AAPL"
    assert len(result["events"]) == 1


def test_get_earnings_calendar_no_data():
    mock_ticker = MagicMock()
    mock_ticker.earnings_dates = None

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_earnings_calendar
            result = asyncio.run(get_earnings_calendar("XLK", 7))

    assert result["events"] == []


def test_get_earnings_calendar_exception_returns_empty():
    mock_ticker = MagicMock()
    mock_ticker.earnings_dates = MagicMock()
    mock_ticker.earnings_dates.iterrows.side_effect = Exception("error")

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_earnings_calendar
            result = asyncio.run(get_earnings_calendar("SPY", 7))

    assert result["events"] == []


# ── get_macro_data ────────────────────────────────────────────────────────────

def test_get_macro_data_returns_all_fields():
    mock_ticker = MagicMock()
    mock_ticker.info = {"regularMarketPrice": 18.5}

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_macro_data
            result = asyncio.run(get_macro_data())

    assert "vix" in result
    assert "yield_10y" in result
    assert "yield_2y" in result
    assert "dxy" in result
    assert "timestamp" in result


def test_get_macro_data_exception_returns_zero():
    mock_yf = MagicMock()
    mock_yf.Ticker.side_effect = Exception("network error")

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_macro_data
            result = asyncio.run(get_macro_data())

    assert result["vix"] == 0.0


# ── get_fund_flows ────────────────────────────────────────────────────────────

def _make_mock_hist(closes: list[float], volumes: list[float]):
    """Build a mock DataFrame-like object for yf.download without real pandas."""
    mock_hist = MagicMock()
    mock_hist.empty = len(closes) == 0

    # Mock hist["Close"].tolist() and hist["Volume"].tolist()
    mock_close_series = MagicMock()
    mock_close_series.tolist.return_value = closes

    mock_vol_series = MagicMock()
    mock_vol_series.tolist.return_value = volumes

    def getitem(key):
        if key == "Close":
            return mock_close_series
        if key == "Volume":
            return mock_vol_series
        raise KeyError(key)

    mock_hist.__getitem__ = MagicMock(side_effect=getitem)
    return mock_hist


def test_get_fund_flows_inflow():
    mock_hist = _make_mock_hist([100.0, 101.0, 102.0], [1e6, 1e6, 1e6])
    mock_yf = MagicMock()
    mock_yf.download.return_value = mock_hist

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_fund_flows
            result = asyncio.run(get_fund_flows("XLK"))

    assert result["symbol"] == "XLK"
    assert result["flow_direction"] == "inflow"


def test_get_fund_flows_outflow():
    mock_hist = _make_mock_hist([102.0, 101.0, 100.0], [1e6, 1e6, 1e6])
    mock_yf = MagicMock()
    mock_yf.download.return_value = mock_hist

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_fund_flows
            result = asyncio.run(get_fund_flows("SPY"))

    assert result["flow_direction"] == "outflow"


def test_get_fund_flows_empty_data():
    mock_hist = MagicMock()
    mock_hist.empty = True

    mock_yf = MagicMock()
    mock_yf.download.return_value = mock_hist

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_fund_flows
            result = asyncio.run(get_fund_flows("XYZ"))

    assert result["flow_direction"] == "neutral"
    assert result["estimated_flow_usd"] == 0.0


def test_get_fund_flows_single_row():
    mock_hist = _make_mock_hist([100.0], [1e6])
    mock_yf = MagicMock()
    mock_yf.download.return_value = mock_hist

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_fund_flows
            result = asyncio.run(get_fund_flows("X"))

    assert result["flow_direction"] == "neutral"


# ── get_etf_metrics ───────────────────────────────────────────────────────────

def test_get_etf_metrics_returns_fields():
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "totalAssets": 5e9,
        "annualReportExpenseRatio": 0.0009,
        "navPrice": 185.5,
        "sharesOutstanding": 1e8,
    }
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_etf_metrics
            result = asyncio.run(get_etf_metrics("XLK"))

    assert result["symbol"] == "XLK"
    assert result["aum_usd"] > 0
    assert result["expense_ratio"] > 0
    assert result["nav"] > 0


# ── compare_etfs ──────────────────────────────────────────────────────────────

def test_compare_etfs_returns_all_symbols():
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "totalAssets": 1e9,
        "annualReportExpenseRatio": 0.001,
        "52WeekChange": 0.12,
        "beta": 1.1,
    }
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import compare_etfs
            result = asyncio.run(compare_etfs(["XLK", "SPY"]))

    assert len(result["comparisons"]) == 2
    symbols = {c["symbol"] for c in result["comparisons"]}
    assert "XLK" in symbols
    assert "SPY" in symbols


def test_compare_etfs_caps_at_5():
    mock_ticker = MagicMock()
    mock_ticker.info = {}
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import compare_etfs
            result = asyncio.run(compare_etfs(["A", "B", "C", "D", "E", "F", "G"]))

    assert len(result["comparisons"]) <= 5


def test_compare_etfs_exception_still_includes_symbol():
    mock_yf = MagicMock()
    mock_yf.Ticker.side_effect = Exception("network error")

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import compare_etfs
            result = asyncio.run(compare_etfs(["XLK"]))

    assert len(result["comparisons"]) == 1
    assert result["comparisons"][0]["symbol"] == "XLK"
    assert result["comparisons"][0]["aum_usd"] == 0


# ── get_expense_ratios ────────────────────────────────────────────────────────

def test_get_expense_ratios_returns_all():
    mock_ticker = MagicMock()
    mock_ticker.info = {"annualReportExpenseRatio": 0.0003}
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_expense_ratios
            result = asyncio.run(get_expense_ratios(["XLK", "SPY"]))

    assert len(result["ratios"]) == 2


def test_get_expense_ratios_exception_returns_zero():
    mock_yf = MagicMock()
    mock_yf.Ticker.side_effect = Exception("error")

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_expense_ratios
            result = asyncio.run(get_expense_ratios(["FAIL"]))

    assert result["ratios"][0]["expense_ratio"] == 0.0


# ── get_sector_performance ────────────────────────────────────────────────────

def _make_mock_sector_hist(first: float, last: float):
    """Build a mock hist["Close"] series for sector performance."""
    mock_series = MagicMock()
    mock_series.__len__ = lambda s: 2
    mock_series.iloc = MagicMock()
    mock_series.iloc.__getitem__ = MagicMock(side_effect=lambda idx: last if idx == -1 else first)

    # For hist["Close"] to work: download returns a dict-like, then ["Close"] returns mock_series
    mock_download_result = MagicMock()
    mock_download_result.__getitem__ = MagicMock(return_value=mock_series)
    return mock_download_result


def test_get_sector_performance_returns_sorted():
    mock_yf = MagicMock()
    mock_yf.download.return_value = _make_mock_sector_hist(100.0, 103.0)

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_sector_performance
            result = asyncio.run(get_sector_performance("1mo"))

    assert "timeframe" in result
    assert result["timeframe"] == "1mo"
    assert "returns" in result
    assert len(result["returns"]) == 11  # all 11 sector ETFs


def test_get_sector_performance_exception_skips_sector():
    mock_yf = MagicMock()
    mock_yf.download.side_effect = Exception("network error")

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_sector_performance
            result = asyncio.run(get_sector_performance("3mo"))

    assert result["returns"] == []


# ── get_dividend_history ──────────────────────────────────────────────────────

def _make_mock_divs(items: list[tuple]):
    """Build a mock dividends series object without real pandas.

    items: list of (date_str, amount) tuples.
    """
    mock_divs = MagicMock()
    mock_divs.empty = len(items) == 0

    # Build mock dt objects
    def make_mock_dt(date_str: str):
        mock_dt = MagicMock()
        mock_dt.isoformat.return_value = date_str
        return mock_dt

    mock_tail = MagicMock()
    mock_tail.items.return_value = iter([
        (make_mock_dt(date_str), amount) for date_str, amount in items
    ])

    mock_divs.tail.return_value = mock_tail
    return mock_divs


def test_get_dividend_history_returns_dividends():
    mock_divs = _make_mock_divs([
        ("2024-12-15", 0.52),
        ("2024-09-15", 0.49),
    ])
    mock_ticker = MagicMock()
    mock_ticker.dividends = mock_divs

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_dividend_history
            result = asyncio.run(get_dividend_history("XLK"))

    assert result["symbol"] == "XLK"
    assert len(result["dividends"]) == 2


def test_get_dividend_history_empty():
    mock_divs = _make_mock_divs([])

    mock_ticker = MagicMock()
    mock_ticker.dividends = mock_divs

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_dividend_history
            result = asyncio.run(get_dividend_history("GLD"))

    assert result["dividends"] == []


def test_get_dividend_history_exception_returns_empty():
    mock_ticker = MagicMock()
    mock_ticker.dividends = MagicMock()
    mock_ticker.dividends.empty = False
    mock_ticker.dividends.tail.return_value.items.side_effect = Exception("parse error")

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_dividend_history
            result = asyncio.run(get_dividend_history("XLE"))

    assert result["dividends"] == []


# ── get_economic_calendar ─────────────────────────────────────────────────────

def test_get_economic_calendar_returns_events():
    from tools.research.tools import get_economic_calendar
    result = asyncio.run(get_economic_calendar(days_ahead=30))

    assert "events" in result
    assert result["days_ahead"] == 30
    assert len(result["events"]) >= 2  # FOMC + CPI at minimum


def test_get_economic_calendar_fomc_event():
    from tools.research.tools import get_economic_calendar
    result = asyncio.run(get_economic_calendar(7))
    event_names = [e["event"] for e in result["events"]]
    assert "FOMC Meeting" in event_names


# ── detect_market_regime ──────────────────────────────────────────────────────

def test_detect_market_regime_crisis():
    from tools.research.tools import detect_market_regime
    result = asyncio.run(detect_market_regime(vix=35.0, yield_10y=4.5, yield_2y=5.0, benchmark_return_20d=-5.0))
    assert result["regime"] == "CRISIS"


def test_detect_market_regime_high_vol():
    from tools.research.tools import detect_market_regime
    result = asyncio.run(detect_market_regime(vix=25.0, yield_10y=4.0, yield_2y=4.5, benchmark_return_20d=0.5))
    assert result["regime"] == "HIGH_VOL"


def test_detect_market_regime_bull_trend():
    from tools.research.tools import detect_market_regime
    result = asyncio.run(detect_market_regime(vix=12.0, yield_10y=4.0, yield_2y=4.2, benchmark_return_20d=3.5))
    assert result["regime"] == "BULL_TREND"


def test_detect_market_regime_bear_trend():
    from tools.research.tools import detect_market_regime
    result = asyncio.run(detect_market_regime(vix=18.0, yield_10y=4.0, yield_2y=4.2, benchmark_return_20d=-3.0))
    assert result["regime"] == "BEAR_TREND"


def test_detect_market_regime_low_vol_range():
    from tools.research.tools import detect_market_regime
    result = asyncio.run(detect_market_regime(vix=14.0, yield_10y=4.0, yield_2y=4.1, benchmark_return_20d=1.0))
    assert result["regime"] == "LOW_VOL_RANGE"


def test_detect_market_regime_returns_all_fields():
    from tools.research.tools import detect_market_regime
    result = asyncio.run(detect_market_regime(15.0, 4.0, 4.2, 2.5))
    assert "reasoning" in result
    assert "yield_curve_spread" in result
    assert "benchmark_return_20d" in result


# ── get_analyst_ratings ───────────────────────────────────────────────────────

def _make_mock_recs(rows: list[dict]):
    """Build a mock recommendations DataFrame without real pandas."""
    mock_recs = MagicMock()
    mock_recs.empty = len(rows) == 0

    def make_mock_row(row_dict: dict):
        mock_row = MagicMock()
        mock_row.get = lambda key, default=None: row_dict.get(key, default)
        return mock_row

    def make_mock_dt(date_str: str):
        mock_dt = MagicMock()
        mock_dt.isoformat.return_value = date_str
        return mock_dt

    mock_tail = MagicMock()
    mock_tail.iterrows.return_value = iter([
        (make_mock_dt("2025-01-15"), make_mock_row(r)) for r in rows
    ])
    mock_recs.tail.return_value = mock_tail
    return mock_recs


def test_get_analyst_ratings_with_data():
    mock_recs = _make_mock_recs([{"Firm": "Goldman Sachs", "To Grade": "Buy"}])

    mock_ticker = MagicMock()
    mock_ticker.recommendations = mock_recs

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_analyst_ratings
            result = asyncio.run(get_analyst_ratings("XLK"))

    assert result["symbol"] == "XLK"
    assert len(result["ratings"]) == 1
    assert result["ratings"][0]["firm"] == "Goldman Sachs"


def test_get_analyst_ratings_no_data():
    mock_ticker = MagicMock()
    mock_ticker.recommendations = None

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_analyst_ratings
            result = asyncio.run(get_analyst_ratings("SPY"))

    assert result["ratings"] == []


def test_get_analyst_ratings_exception_returns_empty():
    mock_ticker = MagicMock()
    mock_ticker.recommendations = MagicMock()
    mock_ticker.recommendations.empty = False
    mock_ticker.recommendations.tail.return_value.iterrows.side_effect = Exception("parse error")

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire():
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            from tools.research.tools import get_analyst_ratings
            result = asyncio.run(get_analyst_ratings("QQQ"))

    assert result["ratings"] == []

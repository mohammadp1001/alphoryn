"""Unit tests for tools.market.tools — 12 market data tools."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_acquire():
    return patch("infra.rate_limiter.TokenBucket.acquire", new=AsyncMock())


def _make_bar(ts=None, open=100.0, high=105.0, low=99.0, close=103.0, volume=1000000.0):
    b = MagicMock()
    b.timestamp = ts or datetime(2025, 1, 1, tzinfo=UTC)
    b.open = open
    b.high = high
    b.low = low
    b.close = close
    b.volume = volume
    return b


def _make_quote(bid=100.0, ask=100.05, bid_size=100.0, ask_size=200.0, ts=None):
    q = MagicMock()
    q.bid_price = bid
    q.ask_price = ask
    q.bid_size = bid_size
    q.ask_size = ask_size
    q.timestamp = ts or datetime(2025, 1, 1, tzinfo=UTC)
    return q


# ── get_ohlcv ─────────────────────────────────────────────────────────────────

def test_get_ohlcv_returns_correct_structure():
    bars = [_make_bar(close=103.0 + i) for i in range(5)]
    mock_resp = {"XLK": bars}
    mock_client = MagicMock()
    mock_client.get_stock_bars.return_value = mock_resp

    with _mock_acquire(), patch("tools.market.tools._data_client", return_value=mock_client):
        from tools.market.tools import get_ohlcv
        result = asyncio.run(get_ohlcv("XLK", "1Day", 5))

    assert result["symbol"] == "XLK"
    assert result["timeframe"] == "1Day"
    assert len(result["bars"]) == 5
    assert "open" in result["bars"][0]
    assert "close" in result["bars"][0]
    assert "volume" in result["bars"][0]


def test_get_ohlcv_symbol_not_in_response():
    """Symbol missing from response returns empty bars."""
    mock_resp = {}
    mock_client = MagicMock()
    mock_client.get_stock_bars.return_value = mock_resp

    with _mock_acquire(), patch("tools.market.tools._data_client", return_value=mock_client):
        from tools.market.tools import get_ohlcv
        result = asyncio.run(get_ohlcv("MISSING", "1Day", 10))

    assert result["bars"] == []


def test_get_ohlcv_4hour_timeframe():
    bars = [_make_bar()]
    mock_resp = {"SPY": bars}
    mock_client = MagicMock()
    mock_client.get_stock_bars.return_value = mock_resp

    with _mock_acquire(), patch("tools.market.tools._data_client", return_value=mock_client):
        from tools.market.tools import get_ohlcv
        result = asyncio.run(get_ohlcv("SPY", "4Hour", 1))

    assert result["symbol"] == "SPY"


def test_get_ohlcv_unknown_timeframe_defaults_to_day():
    bars = [_make_bar()]
    mock_resp = {"QQQ": bars}
    mock_client = MagicMock()
    mock_client.get_stock_bars.return_value = mock_resp

    with _mock_acquire(), patch("tools.market.tools._data_client", return_value=mock_client):
        from tools.market.tools import get_ohlcv
        result = asyncio.run(get_ohlcv("QQQ", "WeeklyX", 1))

    assert result["symbol"] == "QQQ"


# ── get_quote ─────────────────────────────────────────────────────────────────

def test_get_quote_returns_bid_ask():
    quote = _make_quote(bid=180.0, ask=180.05)
    mock_resp = {"XLK": quote}
    mock_client = MagicMock()
    mock_client.get_stock_latest_quote.return_value = mock_resp

    with _mock_acquire(), patch("tools.market.tools._data_client", return_value=mock_client):
        from tools.market.tools import get_quote
        result = asyncio.run(get_quote("XLK"))

    assert result["symbol"] == "XLK"
    assert result["bid"] == 180.0
    assert result["ask"] == 180.05
    assert "timestamp" in result


# ── get_spread ────────────────────────────────────────────────────────────────

def test_get_spread_calculates_correctly():
    quote = _make_quote(bid=100.0, ask=100.10)
    mock_resp = {"SPY": quote}
    mock_client = MagicMock()
    mock_client.get_stock_latest_quote.return_value = mock_resp

    with _mock_acquire(), patch("tools.market.tools._data_client", return_value=mock_client):
        from tools.market.tools import get_spread
        result = asyncio.run(get_spread("SPY"))

    assert result["symbol"] == "SPY"
    assert abs(result["spread_abs"] - 0.10) < 0.001
    assert result["spread_pct"] > 0


def test_get_spread_zero_mid_returns_zero_pct():
    quote = _make_quote(bid=0.0, ask=0.0)
    mock_resp = {"XYZ": quote}
    mock_client = MagicMock()
    mock_client.get_stock_latest_quote.return_value = mock_resp

    with _mock_acquire(), patch("tools.market.tools._data_client", return_value=mock_client):
        from tools.market.tools import get_spread
        result = asyncio.run(get_spread("XYZ"))

    assert result["spread_pct"] == 0.0


# ── get_order_book ────────────────────────────────────────────────────────────

def test_get_order_book_returns_bids_asks():
    import alpaca.data.requests as alpaca_reqs

    bid = MagicMock()
    bid.p = 99.9
    bid.s = 100.0
    ask = MagicMock()
    ask.p = 100.1
    ask.s = 50.0

    ob = MagicMock()
    ob.bids = [bid]
    ob.asks = [ask]
    ob.timestamp = datetime(2025, 1, 1, tzinfo=UTC)

    mock_resp = {"XLK": ob}
    mock_client = MagicMock()
    mock_client.get_stock_latest_orderbook.return_value = mock_resp

    # Patch missing StockLatestOrderbookRequest in alpaca-py version
    mock_req_class = MagicMock()
    with (
        patch.object(alpaca_reqs, "StockLatestOrderbookRequest", mock_req_class, create=True),
        _mock_acquire(),
        patch("tools.market.tools._data_client", return_value=mock_client),
    ):
        from tools.market.tools import get_order_book
        result = asyncio.run(get_order_book("XLK", depth=5))

    assert result["symbol"] == "XLK"
    assert len(result["bids"]) == 1
    assert len(result["asks"]) == 1
    assert result["bids"][0]["price"] == 99.9
    assert result["asks"][0]["price"] == 100.1


# ── screen_etfs ───────────────────────────────────────────────────────────────

def test_screen_etfs_returns_filtered_results():
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "regularMarketPrice": 200.0,
        "averageVolume": 5_000_000,
        "52WeekChange": 0.15,
        "sector": "Technology",
    }
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire(), patch.dict("sys.modules", {"yfinance": mock_yf}):
        from tools.market.tools import screen_etfs
        result = asyncio.run(screen_etfs(min_avg_volume=1_000_000, min_price=50.0))

    assert "results" in result
    assert all(r["price"] >= 50.0 for r in result["results"])
    assert all(r["avg_volume_30d"] >= 1_000_000 for r in result["results"])


def test_screen_etfs_filters_below_min_price():
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "regularMarketPrice": 10.0,  # below min_price
        "averageVolume": 5_000_000,
        "52WeekChange": 0.0,
    }
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire(), patch.dict("sys.modules", {"yfinance": mock_yf}):
        from tools.market.tools import screen_etfs
        result = asyncio.run(screen_etfs(min_avg_volume=1_000_000, min_price=100.0))

    assert result["results"] == []


def test_screen_etfs_skips_erroring_tickers():
    mock_ticker = MagicMock()
    mock_ticker.info = {}  # no price field → price = 0.0 → filtered out

    mock_yf = MagicMock()
    mock_yf.Ticker.side_effect = Exception("network error")

    with _mock_acquire(), patch.dict("sys.modules", {"yfinance": mock_yf}):
        from tools.market.tools import screen_etfs
        result = asyncio.run(screen_etfs(min_avg_volume=0, min_price=0.0))

    assert result["results"] == []


def test_screen_etfs_uses_explicit_symbols():
    """symbols parameter overrides DEFAULT_ETF_UNIVERSE."""
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "regularMarketPrice": 100.0,
        "averageVolume": 2_000_000,
        "52WeekChange": 0.10,
        "sector": "International",
    }
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire(), patch.dict("sys.modules", {"yfinance": mock_yf}):
        from tools.market.tools import screen_etfs
        result = asyncio.run(
            screen_etfs(min_avg_volume=0, min_price=0.0, symbols=["EWG", "FEZ"])
        )

    assert [r["symbol"] for r in result["results"]] == ["EWG", "FEZ"]


# ── get_etf_holdings ──────────────────────────────────────────────────────────

def test_get_etf_holdings_returns_list():
    import pandas as pd

    df = pd.DataFrame(
        {"Holding Percent": [0.12, 0.08], "Name": ["Apple", "Microsoft"]},
        index=["AAPL", "MSFT"],
    )

    mock_ticker = MagicMock()
    mock_ticker.funds_data.top_holdings = df

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire(), patch.dict("sys.modules", {"yfinance": mock_yf}):
        from tools.market.tools import get_etf_holdings
        result = asyncio.run(get_etf_holdings("XLK"))

    assert result["symbol"] == "XLK"
    assert len(result["top_holdings"]) == 2
    assert result["top_holdings"][0]["ticker"] == "AAPL"
    assert abs(result["top_holdings"][0]["weight_pct"] - 12.0) < 0.01


def test_get_etf_holdings_exception_returns_empty():
    """When funds_data raises, empty list returned."""
    mock_funds_data = MagicMock()
    mock_funds_data.top_holdings = MagicMock()
    mock_funds_data.top_holdings.iterrows.side_effect = Exception("parse error")

    mock_ticker = MagicMock()
    mock_ticker.funds_data = mock_funds_data

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire(), patch.dict("sys.modules", {"yfinance": mock_yf}):
        from tools.market.tools import get_etf_holdings
        result = asyncio.run(get_etf_holdings("XLK"))

    assert result["symbol"] == "XLK"
    assert result["top_holdings"] == []


# ── get_sector_map ────────────────────────────────────────────────────────────

def test_get_sector_map_contains_xlk():
    from tools.market.tools import get_sector_map
    result = asyncio.run(get_sector_map())

    assert "etf_to_sector" in result
    assert "sector_to_etfs" in result
    assert result["etf_to_sector"]["XLK"] == "Technology"
    assert "XLK" in result["sector_to_etfs"]["Technology"]


def test_get_sector_map_spy_in_broad_market():
    from tools.market.tools import get_sector_map
    result = asyncio.run(get_sector_map())

    assert result["etf_to_sector"]["SPY"] == "Broad Market"
    assert "SPY" in result["sector_to_etfs"]["Broad Market"]


# ── get_52w_range ─────────────────────────────────────────────────────────────

def test_get_52w_range_returns_correct_fields():
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "fiftyTwoWeekHigh": 200.0,
        "fiftyTwoWeekLow": 150.0,
        "regularMarketPrice": 180.0,
    }
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire(), patch.dict("sys.modules", {"yfinance": mock_yf}):
        from tools.market.tools import get_52w_range
        result = asyncio.run(get_52w_range("SPY"))

    assert result["symbol"] == "SPY"
    assert result["high_52w"] == 200.0
    assert result["low_52w"] == 150.0
    assert result["current_price"] == 180.0
    assert result["pct_from_high"] < 0  # below high
    assert result["pct_from_low"] > 0  # above low


def test_get_52w_range_zero_high_returns_zero_pct():
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "fiftyTwoWeekHigh": 0,
        "fiftyTwoWeekLow": 0,
        "regularMarketPrice": 0,
    }
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with _mock_acquire(), patch.dict("sys.modules", {"yfinance": mock_yf}):
        from tools.market.tools import get_52w_range
        result = asyncio.run(get_52w_range("ZZZ"))

    assert result["pct_from_high"] == 0.0
    assert result["pct_from_low"] == 0.0


# ── get_volume_profile ────────────────────────────────────────────────────────

def test_get_volume_profile_empty_bars():
    mock_resp = {}  # no bars for symbol

    mock_client = MagicMock()
    mock_client.get_stock_bars.return_value = mock_resp

    with _mock_acquire(), patch("tools.market.tools._data_client", return_value=mock_client):
        from tools.market.tools import get_volume_profile
        result = asyncio.run(get_volume_profile("MISS", 5))

    assert result["symbol"] == "MISS"
    assert result["buckets"] == []
    assert result["point_of_control"] == 0.0


def test_get_volume_profile_with_bars():
    bars = [_make_bar(close=100.0 + i, volume=1000.0 * (i + 1)) for i in range(10)]
    mock_resp = {"XLK": bars}
    mock_client = MagicMock()
    mock_client.get_stock_bars.return_value = mock_resp

    with _mock_acquire(), patch("tools.market.tools._data_client", return_value=mock_client):
        from tools.market.tools import get_volume_profile
        result = asyncio.run(get_volume_profile("XLK", 10))

    assert result["symbol"] == "XLK"
    assert len(result["buckets"]) > 0
    assert result["point_of_control"] > 0
    assert result["days"] == 10


# ── get_benchmark_return ──────────────────────────────────────────────────────

def test_get_benchmark_return_empty_data():
    import pandas as pd

    empty_df = pd.DataFrame()
    mock_yf = MagicMock()
    mock_yf.download.return_value = MagicMock(empty=True)
    # patch the 'Close' attribute to be an empty df
    download_result = MagicMock()
    download_result.empty = True
    mock_yf.download.return_value = download_result
    # Make indexing return empty df
    download_result.__getitem__ = lambda self, key: empty_df

    with _mock_acquire(), patch.dict("sys.modules", {"yfinance": mock_yf}):
        from tools.market.tools import get_benchmark_return
        result = asyncio.run(get_benchmark_return("XLK", "1mo"))

    assert result["symbol"] == "XLK"
    assert result["benchmark"] == "SPY"
    assert result["symbol_return_pct"] == 0.0


def test_get_benchmark_return_with_data():
    import pandas as pd

    dates = pd.date_range("2025-01-01", periods=5)
    data = pd.DataFrame({
        "XLK": [100.0, 101.0, 102.0, 103.0, 105.0],
        "SPY": [400.0, 401.0, 402.0, 403.0, 404.0],
    }, index=dates)

    mock_yf = MagicMock()
    download_mock = MagicMock()
    download_mock.empty = False
    download_mock.__getitem__ = lambda self, key: data

    mock_yf.download.return_value = download_mock

    with _mock_acquire(), patch.dict("sys.modules", {"yfinance": mock_yf}):
        from tools.market.tools import get_benchmark_return
        result = asyncio.run(get_benchmark_return("XLK", "1mo"))

    assert result["symbol"] == "XLK"
    assert "symbol_return_pct" in result
    assert "excess_return_pct" in result


# ── get_intraday_bars ─────────────────────────────────────────────────────────

def test_get_intraday_bars_delegates_to_get_ohlcv():
    bars = [_make_bar()]
    mock_resp = {"SPY": bars}
    mock_client = MagicMock()
    mock_client.get_stock_bars.return_value = mock_resp

    with _mock_acquire(), patch("tools.market.tools._data_client", return_value=mock_client):
        from tools.market.tools import get_intraday_bars
        result = asyncio.run(get_intraday_bars("SPY", "5Min"))

    assert result["symbol"] == "SPY"
    assert result["timeframe"] == "5Min"


# ── get_market_status ─────────────────────────────────────────────────────────

def test_get_market_status_no_api_key(monkeypatch):
    monkeypatch.delenv("ALPACA_DATA_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)

    from tools.market.tools import get_market_status
    result = asyncio.run(get_market_status())

    assert result["is_open"] is False
    assert result["next_open"] is None
    assert "timestamp" in result


def test_get_market_status_with_api_key(monkeypatch):
    monkeypatch.setenv("ALPACA_DATA_KEY", "test-data-key")
    monkeypatch.setenv("ALPACA_DATA_SECRET", "test-data-secret")

    clock = MagicMock()
    clock.is_open = True
    clock.next_open = datetime(2025, 1, 2, 9, 30, tzinfo=UTC)
    clock.next_close = datetime(2025, 1, 2, 16, 0, tzinfo=UTC)

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.get_clock.return_value = clock

    with _mock_acquire(), patch("alpaca.trading.client.TradingClient", mock_client_cls):
        from tools.market.tools import get_market_status
        result = asyncio.run(get_market_status())

    assert result["is_open"] is True
    assert result["next_open"] is not None
    assert result["next_close"] is not None


# ── _data_client factory ──────────────────────────────────────────────────────

def test_data_client_factory_returns_instance(monkeypatch):
    """Lines 13-14: _data_client() builds a StockHistoricalDataClient from env vars."""
    monkeypatch.setenv("ALPACA_DATA_KEY", "data-key")
    monkeypatch.setenv("ALPACA_DATA_SECRET", "data-secret")

    mock_instance = MagicMock()
    mock_cls = MagicMock(return_value=mock_instance)
    mock_data_mod = MagicMock(StockHistoricalDataClient=mock_cls)

    with patch.dict("sys.modules", {
        "alpaca": MagicMock(),
        "alpaca.data": mock_data_mod,
    }):
        import importlib

        import tools.market.tools as market_tools
        importlib.reload(market_tools)
        result = market_tools._data_client()

    mock_cls.assert_called_once_with(api_key="data-key", secret_key="data-secret")
    assert result is mock_instance

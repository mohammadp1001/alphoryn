"""Unit tests for Pydantic model properties/methods not covered elsewhere."""
from __future__ import annotations

from datetime import date, datetime

# ── models.analysis ───────────────────────────────────────────────────────────

def test_rsi_result_is_overbought():
    from models.analysis import RSIResult
    r = RSIResult(symbol="X", period=14, current=75.0, values=[], is_overbought=True, is_oversold=False)
    assert r.is_overbought is True


def test_rsi_result_is_oversold():
    from models.analysis import RSIResult
    r = RSIResult(symbol="X", period=14, current=25.0, values=[], is_overbought=False, is_oversold=True)
    assert r.is_oversold is True


def test_bollinger_bandwidth_property():
    from models.analysis import BollingerResult
    b = BollingerResult(
        symbol="X", period=20,
        upper=[105.0], middle=[100.0], lower=[95.0],
        current_upper=105.0, current_middle=100.0, current_lower=95.0,
        current_price=101.0,
    )
    assert abs(b.bandwidth - 0.1) < 0.001  # (105-95)/100 = 0.1


def test_bollinger_pct_b_mid():
    from models.analysis import BollingerResult
    b = BollingerResult(
        symbol="X", period=20,
        upper=[110.0], middle=[100.0], lower=[90.0],
        current_upper=110.0, current_middle=100.0, current_lower=90.0,
        current_price=100.0,  # exactly mid
    )
    assert abs(b.pct_b - 0.5) < 0.001  # (100-90)/(110-90) = 0.5


def test_bollinger_pct_b_zero_bandwidth():
    from models.analysis import BollingerResult
    b = BollingerResult(
        symbol="X", period=20,
        upper=[100.0], middle=[100.0], lower=[100.0],
        current_upper=100.0, current_middle=100.0, current_lower=100.0,
        current_price=100.0,
    )
    assert b.pct_b == 0.5  # band_width=0 → fallback 0.5


def test_correlation_matrix_get():
    from models.analysis import CorrelationMatrix
    cm = CorrelationMatrix(
        symbols=["XLK", "SPY"],
        matrix=[[1.0, 0.85], [0.85, 1.0]],
    )
    assert abs(cm.get("XLK", "SPY") - 0.85) < 0.001
    assert abs(cm.get("SPY", "XLK") - 0.85) < 0.001


# ── models.execution ─────────────────────────────────────────────────────────

def test_portfolio_position_for_found():
    from models.execution import Portfolio, Position
    pos = Position(symbol="XLK", qty=10.0, avg_entry_price=180.0, market_value=1850.0,
                   unrealised_pnl=50.0, unrealised_pnl_pct=2.8, side="long",
                   current_price=185.0)
    portfolio = Portfolio(
        account_id="paper",
        equity=10000.0,
        cash=5000.0,
        buying_power=5000.0,
        portfolio_value=10000.0,
        positions=[pos],
    )
    found = portfolio.position_for("XLK")
    assert found is not None
    assert found.symbol == "XLK"


def test_portfolio_position_for_not_found():
    from models.execution import Portfolio
    portfolio = Portfolio(
        account_id="paper",
        equity=10000.0,
        cash=10000.0,
        buying_power=10000.0,
        portfolio_value=10000.0,
        positions=[],
    )
    assert portfolio.position_for("MISSING") is None


# ── models.market ─────────────────────────────────────────────────────────────

def test_ohlcv_data_closes_property():
    from models.market import OHLCVBar, OHLCVData
    bars = [
        OHLCVBar(timestamp="2025-01-01", open=100.0, high=102.0, low=99.0, close=101.0, volume=1e6),
        OHLCVBar(timestamp="2025-01-02", open=101.0, high=103.0, low=100.0, close=102.0, volume=1.1e6),
    ]
    data = OHLCVData(symbol="XLK", timeframe="1Day", bars=bars)
    assert data.closes == [101.0, 102.0]


def test_ohlcv_data_volumes_property():
    from models.market import OHLCVBar, OHLCVData
    bars = [
        OHLCVBar(timestamp="2025-01-01", open=100.0, high=102.0, low=99.0, close=101.0, volume=1e6),
        OHLCVBar(timestamp="2025-01-02", open=101.0, high=103.0, low=100.0, close=102.0, volume=2e6),
    ]
    data = OHLCVData(symbol="SPY", timeframe="1Day", bars=bars)
    assert data.volumes == [1e6, 2e6]


# ── models.memory ─────────────────────────────────────────────────────────────

def test_agent_pairwise_win_rate_with_data():
    from models.enums import MarketRegime, Strategy
    from models.memory import AgentPairwise
    pw = AgentPairwise(
        agent="optimist",
        market_regime=MarketRegime.BULL_TREND,
        strategy=Strategy.MOMENTUM,
        wins=7,
        losses=3,
    )
    assert abs(pw.win_rate - 0.7) < 0.001
    assert pw.has_data is True


def test_agent_pairwise_win_rate_no_data():
    from models.enums import MarketRegime, Strategy
    from models.memory import AgentPairwise
    pw = AgentPairwise(
        agent="pessimist",
        market_regime=MarketRegime.HIGH_VOL,
        strategy=Strategy.MEAN_REVERSION,
        wins=0,
        losses=0,
    )
    assert pw.win_rate == 0.5  # default
    assert pw.has_data is False


# ── models.research ───────────────────────────────────────────────────────────

def test_sentiment_report_get_score_found():
    from models.research import SentimentReport, SentimentScore
    scores = [
        SentimentScore(symbol="XLK", score=0.7, positive_count=3, negative_count=1, neutral_count=1, article_count=5),
        SentimentScore(symbol="SPY", score=-0.2, positive_count=1, negative_count=2, neutral_count=0, article_count=3),
    ]
    sa = SentimentReport(
        scores=scores,
        overall_market_sentiment=0.2,
        generated_at=datetime.utcnow(),
    )
    assert abs(sa.get_score("XLK") - 0.7) < 0.001
    assert abs(sa.get_score("SPY") + 0.2) < 0.001


def test_sentiment_report_get_score_not_found():
    from models.research import SentimentReport
    sa = SentimentReport(
        scores=[],
        overall_market_sentiment=0.0,
        generated_at=datetime.utcnow(),
    )
    assert sa.get_score("MISSING") is None


def test_macro_data_get_found():
    from models.research import MacroData, MacroIndicator
    indicators = [
        MacroIndicator(name="VIX", value=18.5, as_of=date.today()),
        MacroIndicator(name="10Y_YIELD", value=4.2, as_of=date.today()),
    ]
    md = MacroData(indicators=indicators, fetched_at=datetime.utcnow())
    vix = md.get("VIX")
    assert vix is not None
    assert vix.value == 18.5


def test_macro_data_get_not_found():
    from models.research import MacroData
    md = MacroData(indicators=[], fetched_at=datetime.utcnow())
    assert md.get("MISSING") is None

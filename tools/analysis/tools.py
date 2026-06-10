"""analysis.* tools — 14 tools, analysis agent scope."""
from __future__ import annotations

import math

from infra.observability import get_logger
from tools.schemas import (
    AtrResponse,
    BacktestResponse,
    BetaResponse,
    BollingerResponse,
    CorrelationResponse,
    CrossoverResponse,
    MacdResponse,
    MaxDrawdownResponse,
    MomentumResponse,
    RankByMomentumResponse,
    RsiResponse,
    SharpeResponse,
    SupportResistanceResponse,
    TechnicalScoreResponse,
)

logger = get_logger("tools.analysis")


# ── Technical indicators (pure numpy, no TA-Lib dependency) ──────────────────

async def compute_rsi(symbol: str, closes: list[float], period: int) -> dict:
    """Compute RSI (Relative Strength Index) from close prices.

    Args:
        symbol: Ticker symbol.
        closes: List of close prices (most recent last), minimum period+1 values.
        period: RSI period, typically 14.

    Returns:
        dict with 'symbol', 'period', 'current', 'values' (last 10), 'is_overbought', 'is_oversold'.
    """
    logger.info("compute_rsi symbol=%s period=%d n_closes=%d", symbol, period, len(closes))
    import numpy as np  # type: ignore[import]

    arr = np.array(closes, dtype=float)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    values: list[float] = []
    if len(gains) < period:
        return RsiResponse(symbol=symbol, period=period, current=50.0,
                           values=[], is_overbought=False, is_oversold=False).model_dump()

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        values.append(round(100 - 100 / (1 + rs), 2))

    current = values[-1] if values else 50.0
    return RsiResponse(
        symbol=symbol, period=period, current=current,
        values=values[-10:], is_overbought=current > 70, is_oversold=current < 30,
    ).model_dump()


async def compute_macd(symbol: str, closes: list[float]) -> dict:
    """Compute MACD (12/26/9 EMA) from close prices.

    Args:
        symbol: Ticker symbol.
        closes: List of close prices (most recent last), minimum 35 values.

    Returns:
        dict with 'symbol', 'current_macd', 'current_signal', 'current_histogram'.
    """
    logger.info("compute_macd symbol=%s n_closes=%d", symbol, len(closes))

    def ema(data: list[float], span: int) -> list[float]:
        k = 2 / (span + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    arr = closes[:]
    ema12 = ema(arr, 12)
    ema26 = ema(arr, 26)
    macd_line = [m - s for m, s in zip(ema12, ema26, strict=False)]

    # signal starts after 26 bars; guard against insufficient data
    if len(macd_line) > 25:
        signal_line = ema(macd_line[25:], 9)
        hist = [m - s for m, s in zip(macd_line[25 + 8:], signal_line[8:], strict=False)]
    else:
        signal_line = []
        hist = []

    n = min(10, len(hist))
    return MacdResponse(
        symbol=symbol,
        macd_line=[round(v, 4) for v in macd_line[-n:]],
        signal_line=[round(v, 4) for v in signal_line[-n:]],
        histogram=[round(v, 4) for v in hist[-n:]],
        current_macd=round(macd_line[-1], 4) if macd_line else 0.0,
        current_signal=round(signal_line[-1], 4) if signal_line else 0.0,
        current_histogram=round(hist[-1], 4) if hist else 0.0,
    ).model_dump()


async def compute_bollinger(symbol: str, closes: list[float], period: int) -> dict:
    """Compute Bollinger Bands from close prices.

    Args:
        symbol: Ticker symbol.
        closes: List of close prices (most recent last).
        period: SMA period, typically 20.

    Returns:
        dict with 'symbol', 'current_upper', 'current_middle', 'current_lower', 'current_price', 'pct_b', 'bandwidth'.
    """
    logger.info("compute_bollinger symbol=%s period=%d n_closes=%d", symbol, period, len(closes))
    import numpy as np  # type: ignore[import]

    arr = np.array(closes[-period:], dtype=float)
    mid = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    upper = mid + 2 * std
    lower = mid - 2 * std
    price = closes[-1]
    band_width = upper - lower
    pct_b = (price - lower) / band_width if band_width > 0 else 0.5

    return BollingerResponse(
        symbol=symbol, period=period,
        current_upper=round(upper, 4), current_middle=round(mid, 4),
        current_lower=round(lower, 4), current_price=round(price, 4),
        pct_b=round(pct_b, 4), bandwidth=round(band_width / mid if mid else 0, 4),
    ).model_dump()


async def compute_atr(symbol: str, highs: list[float], lows: list[float], closes: list[float], period: int) -> dict:
    """Compute ATR (Average True Range).

    Args:
        symbol: Ticker symbol.
        highs: List of high prices.
        lows: List of low prices.
        closes: List of close prices.
        period: ATR period, typically 14.

    Returns:
        dict with 'symbol', 'period', 'current', 'values' (last 5).
    """
    logger.info("compute_atr symbol=%s period=%d n_bars=%d", symbol, period, len(closes))
    tr_values = []
    for i in range(1, len(closes)):
        high_low = highs[i] - lows[i]
        high_close = abs(highs[i] - closes[i - 1])
        low_close = abs(lows[i] - closes[i - 1])
        tr_values.append(max(high_low, high_close, low_close))

    if len(tr_values) < period:
        return AtrResponse(symbol=symbol, period=period, current=0.0, values=[]).model_dump()

    atr = sum(tr_values[:period]) / period
    atrs = [atr]
    for tr in tr_values[period:]:
        atr = (atr * (period - 1) + tr) / period
        atrs.append(atr)

    return AtrResponse(
        symbol=symbol, period=period,
        current=round(atrs[-1], 4), values=[round(v, 4) for v in atrs[-5:]],
    ).model_dump()


async def compute_beta(
    symbol: str,
    symbol_returns: list[float],
    benchmark_returns: list[float],
    benchmark: str = "SPY",
) -> dict:
    """Compute beta of a symbol against a benchmark.

    Args:
        symbol: Ticker symbol.
        symbol_returns: List of daily return percentages for the symbol.
        benchmark_returns: List of daily return percentages for the benchmark (same length).
        benchmark: Ticker used as the benchmark (for display). Defaults to 'SPY'.

    Returns:
        dict with 'symbol', 'benchmark', 'beta', 'r_squared'.
    """
    logger.info("compute_beta symbol=%s benchmark=%s n_returns=%d", symbol, benchmark, len(symbol_returns))
    import numpy as np  # type: ignore[import]

    x = np.array(benchmark_returns)
    y = np.array(symbol_returns)
    if len(x) < 2:
        return BetaResponse(symbol=symbol, benchmark=benchmark, beta=1.0, r_squared=0.0, period_days=len(x)).model_dump()

    cov = float(np.cov(x, y)[0][1])
    var = float(np.var(x, ddof=1))
    beta = cov / var if var != 0 else 1.0
    corr = float(np.corrcoef(x, y)[0][1])
    return BetaResponse(
        symbol=symbol, benchmark=benchmark,
        beta=round(beta, 4), r_squared=round(corr ** 2, 4), period_days=len(x),
    ).model_dump()


async def detect_momentum(symbol: str, closes: list[float], volumes: list[float]) -> dict:
    """Detect and score price momentum for a symbol.

    Args:
        symbol: Ticker symbol.
        closes: List of close prices (most recent last), minimum 30 values.
        volumes: List of volume values corresponding to closes.

    Returns:
        dict with 'symbol', 'momentum_score' (-1 to +1), and component contributions.
    """
    logger.info("detect_momentum symbol=%s n_closes=%d", symbol, len(closes))
    if len(closes) < 20:
        return MomentumResponse(
            symbol=symbol, momentum_score=0.0, rsi_contribution=0.0,
            macd_contribution=0.0, price_vs_sma_contribution=0.0,
            volume_trend_contribution=0.0, raw_rsi=50.0, raw_macd_histogram=0.0,
        ).model_dump()

    import numpy as np  # type: ignore[import]

    # RSI contribution
    rsi_result = await compute_rsi(symbol, closes, 14)
    rsi = rsi_result["current"]
    rsi_score = (rsi - 50) / 50  # -1 to +1

    # MACD contribution
    macd_result = await compute_macd(symbol, closes)
    macd_hist = macd_result["current_histogram"]
    price_scale = closes[-1] if closes[-1] != 0 else 1
    macd_score = max(-1.0, min(1.0, macd_hist / (price_scale * 0.005)))

    # Price vs 20-SMA
    sma20 = float(np.mean(closes[-20:]))
    price_sma_score = max(-1.0, min(1.0, (closes[-1] - sma20) / sma20 * 10))

    # Volume trend (recent vs older)
    vol_recent = float(np.mean(volumes[-5:]))
    vol_old = float(np.mean(volumes[-20:-5]))
    vol_score = max(-1.0, min(1.0, (vol_recent / vol_old - 1) * 2)) if vol_old > 0 else 0.0

    composite = (rsi_score * 0.3 + macd_score * 0.3 + price_sma_score * 0.25 + vol_score * 0.15)
    return MomentumResponse(
        symbol=symbol, momentum_score=round(composite, 4),
        rsi_contribution=round(rsi_score, 4), macd_contribution=round(macd_score, 4),
        price_vs_sma_contribution=round(price_sma_score, 4),
        volume_trend_contribution=round(vol_score, 4),
        raw_rsi=rsi, raw_macd_histogram=macd_hist,
    ).model_dump()


async def detect_crossover(symbol: str, macd_histogram: list[float]) -> dict:
    """Detect MACD bullish or bearish crossover from histogram.

    Args:
        symbol: Ticker symbol.
        macd_histogram: Recent histogram values (most recent last), minimum 2.

    Returns:
        dict with 'symbol', 'crossover_type' ('bullish'|'bearish'|'none'), 'bars_since_crossover', 'strength'.
    """
    logger.info("detect_crossover symbol=%s", symbol)
    if len(macd_histogram) < 2:
        return CrossoverResponse(symbol=symbol, crossover_type="none", bars_since_crossover=None, strength=0.0).model_dump()

    current = macd_histogram[-1]
    prev = macd_histogram[-2]

    if prev < 0 <= current:
        crossover_type = "bullish"
        strength = min(1.0, abs(current - prev) * 10)
    elif prev > 0 >= current:
        crossover_type = "bearish"
        strength = min(1.0, abs(current - prev) * 10)
    else:
        crossover_type = "none"
        strength = 0.0

    return CrossoverResponse(
        symbol=symbol, crossover_type=crossover_type,
        bars_since_crossover=0 if crossover_type != "none" else None,
        strength=round(strength, 4),
    ).model_dump()


async def detect_support_resistance(symbol: str, highs: list[float], lows: list[float], closes: list[float]) -> dict:
    """Detect key support and resistance price levels.

    Args:
        symbol: Ticker symbol.
        highs: List of daily highs.
        lows: List of daily lows.
        closes: List of close prices (most recent last).

    Returns:
        dict with 'symbol', 'levels', 'nearest_support', 'nearest_resistance'.
    """
    logger.info("detect_support_resistance symbol=%s n_bars=%d", symbol, len(closes))

    price = closes[-1]
    all_levels = highs + lows
    all_levels.sort()

    # Cluster nearby levels
    clusters: list[float] = []
    for level in all_levels:
        if not clusters or abs(level - clusters[-1]) / clusters[-1] > 0.005:
            clusters.append(level)

    levels = []
    for level in clusters:
        touch_count = sum(
            1 for hi, lo in zip(highs, lows, strict=False)
            if lo <= level * 1.005 and hi >= level * 0.995
        )
        level_type = "resistance" if level > price else "support"
        if touch_count >= 2:
            levels.append({
                "price": round(level, 2),
                "level_type": level_type,
                "strength": round(min(1.0, touch_count / 5), 2),
            })

    support_levels = [item["price"] for item in levels if item["level_type"] == "support"]
    resistance_levels = [item["price"] for item in levels if item["level_type"] == "resistance"]

    return SupportResistanceResponse(
        symbol=symbol, levels=levels[:10],
        nearest_support=max(support_levels) if support_levels else None,
        nearest_resistance=min(resistance_levels) if resistance_levels else None,
    ).model_dump()


async def rank_by_momentum(momentum_scores: list[dict]) -> dict:
    """Rank ETFs by their momentum scores from highest to lowest.

    Args:
        momentum_scores: List of momentum signal dicts from detect_momentum, each with 'symbol' and 'momentum_score'.

    Returns:
        dict with 'signals' (ranked list) and 'screened_universe' (all symbols evaluated).
    """
    logger.info("rank_by_momentum n_symbols=%d", len(momentum_scores))
    universe = [m["symbol"] for m in momentum_scores]
    ranked = sorted(momentum_scores, key=lambda x: x["momentum_score"], reverse=True)

    signals = [
        {
            "symbol": r["symbol"],
            "rank": i + 1,
            "momentum_score": r["momentum_score"],
            "technical_score": r.get("technical_score", r["momentum_score"]),
            "combined_score": r["momentum_score"],
        }
        for i, r in enumerate(ranked)
    ]
    return RankByMomentumResponse(signals=signals, screened_universe=universe).model_dump()


async def run_backtest(symbol: str, strategy: str, closes: list[float], volumes: list[float]) -> dict:
    """Run signal lookback analysis — historical signal matches and forward returns.

    Args:
        symbol: Ticker symbol.
        strategy: Active strategy — 'MOMENTUM', 'MEAN_REVERSION', or 'SECTOR_ROTATION'.
        closes: Historical close prices (at least 90 bars).
        volumes: Historical volumes corresponding to closes.

    Returns:
        dict with signal pattern stats: 'avg_forward_return_pct', 'win_rate_pct', 'match_count', etc.
    """
    logger.info("run_backtest symbol=%s strategy=%s n_closes=%d", symbol, strategy, len(closes))
    import numpy as np  # type: ignore[import]

    from config import SIGNAL_FORWARD_RETURN_DAYS, SIGNAL_LOOKBACK_BARS

    fwd = SIGNAL_FORWARD_RETURN_DAYS
    lookback = min(SIGNAL_LOOKBACK_BARS, len(closes) - fwd - 1)
    if lookback < 20:
        return BacktestResponse(
            symbol=symbol, strategy=strategy, signal_pattern="insufficient_data",
            lookback_bars=lookback, forward_return_days=fwd,
            match_count=0, avg_forward_return_pct=0.0,
            win_rate_pct=0.0, max_adverse_excursion_pct=0.0,
        ).model_dump()

    current_momentum = await detect_momentum(symbol, closes[-20:], volumes[-20:])
    current_score = current_momentum["momentum_score"]

    matches = []
    for i in range(20, lookback):
        window_closes = closes[i - 20:i]
        window_vols = volumes[i - 20:i]
        hist_momentum = await detect_momentum(symbol, window_closes, window_vols)
        hist_score = hist_momentum["momentum_score"]

        if abs(hist_score - current_score) < 0.2:
            fwd_return = (closes[i + fwd] - closes[i]) / closes[i] * 100
            mae = min((closes[i + j] - closes[i]) / closes[i] * 100 for j in range(1, fwd + 1))
            matches.append({"bar_index": i, "signal_strength": hist_score, "forward_return_pct": fwd_return, "mae": mae})

    if not matches:
        return BacktestResponse(
            symbol=symbol, strategy=strategy, signal_pattern=f"{strategy.lower()}_no_matches",
            lookback_bars=lookback, forward_return_days=fwd,
            match_count=0, avg_forward_return_pct=0.0,
            win_rate_pct=0.0, max_adverse_excursion_pct=0.0,
        ).model_dump()

    forward_returns = [m["forward_return_pct"] for m in matches]
    avg_fwd = float(np.mean(forward_returns))
    win_rate = sum(1 for r in forward_returns if r > 0) / len(forward_returns) * 100
    max_mae = float(min(m["mae"] for m in matches))

    return BacktestResponse(
        symbol=symbol, strategy=strategy,
        signal_pattern=f"{strategy.lower()}_momentum_score_{current_score:.2f}",
        lookback_bars=lookback, forward_return_days=fwd, match_count=len(matches),
        avg_forward_return_pct=round(avg_fwd, 4),
        win_rate_pct=round(win_rate, 2),
        max_adverse_excursion_pct=round(max_mae, 4),
    ).model_dump()


async def calc_sharpe(symbol: str, daily_returns: list[float]) -> dict:
    """Calculate annualised Sharpe ratio from daily returns.

    Args:
        symbol: Ticker symbol.
        daily_returns: List of daily return percentages.

    Returns:
        dict with 'symbol', 'sharpe_ratio', 'annualised_return_pct', 'annualised_volatility_pct'.
    """
    logger.info("calc_sharpe symbol=%s n_returns=%d", symbol, len(daily_returns))
    import numpy as np  # type: ignore[import]

    arr = np.array(daily_returns)
    avg = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    sharpe = (avg / std * math.sqrt(252)) if std > 1e-10 else 0.0
    return SharpeResponse(
        symbol=symbol, sharpe_ratio=round(sharpe, 4),
        annualised_return_pct=round(avg * 252, 2),
        annualised_volatility_pct=round(std * math.sqrt(252), 2),
        risk_free_rate=0.0,
    ).model_dump()


async def calc_max_drawdown(symbol: str, closes: list[float]) -> dict:
    """Calculate maximum drawdown from close prices.

    Args:
        symbol: Ticker symbol.
        closes: List of close prices.

    Returns:
        dict with 'symbol', 'max_drawdown_pct', 'drawdown_start_bar', 'drawdown_end_bar'.
    """
    logger.info("calc_max_drawdown symbol=%s n_closes=%d", symbol, len(closes))
    import numpy as np  # type: ignore[import]

    arr = np.array(closes)
    peak = arr[0]
    max_dd = 0.0
    start = 0
    trough = 0

    for i, price in enumerate(arr):
        if price > peak:
            peak = price
            start = i
        dd = (peak - price) / peak * 100
        if dd > max_dd:
            max_dd = dd
            trough = i

    return MaxDrawdownResponse(
        symbol=symbol, max_drawdown_pct=round(max_dd, 4),
        drawdown_start_bar=start, drawdown_end_bar=trough, recovery_bars=None,
    ).model_dump()


async def calc_correlation(symbols: list[str], closes_matrix: list[list[float]]) -> dict:
    """Calculate pairwise correlation matrix for a set of symbols.

    Args:
        symbols: List of ticker symbols.
        closes_matrix: 2D list where closes_matrix[i] is the close price list for symbols[i].

    Returns:
        dict with 'symbols' and 'matrix' (2D list of correlation coefficients).
    """
    logger.info("calc_correlation symbols=%s", symbols)
    import numpy as np  # type: ignore[import]

    arr = np.array(closes_matrix)
    corr = np.corrcoef(arr)
    return CorrelationResponse(
        symbols=symbols,
        matrix=[[round(float(v), 4) for v in row] for row in corr],
    ).model_dump()


async def score_technical(symbol: str, strategy: str, rsi_current: float, macd_histogram: float, pct_b: float) -> dict:
    """Compute composite technical score from indicator values.

    Args:
        symbol: Ticker symbol.
        strategy: Active strategy — 'MOMENTUM', 'MEAN_REVERSION', or 'SECTOR_ROTATION'.
        rsi_current: Current RSI value.
        macd_histogram: Current MACD histogram value.
        pct_b: Current Bollinger Band %B (0 = lower band, 1 = upper band).

    Returns:
        dict with 'symbol', 'composite_score' (-1 to +1), and component scores.
    """
    logger.info("score_technical symbol=%s strategy=%s", symbol, strategy)
    rsi_score = (rsi_current - 50) / 50

    # MACD score: normalise by assuming histogram rarely exceeds ±1% of price
    macd_score = max(-1.0, min(1.0, macd_histogram * 100))

    # Bollinger score: mean-reversion vs momentum
    boll_score = (0.5 - pct_b) * 2 if strategy == "MEAN_REVERSION" else (pct_b - 0.5) * 2

    weights = {"MOMENTUM": (0.35, 0.40, 0.25), "MEAN_REVERSION": (0.25, 0.25, 0.50),
               "SECTOR_ROTATION": (0.30, 0.35, 0.35)}.get(strategy, (0.33, 0.33, 0.33))

    composite = rsi_score * weights[0] + macd_score * weights[1] + boll_score * weights[2]
    return TechnicalScoreResponse(
        symbol=symbol, composite_score=round(max(-1.0, min(1.0, composite)), 4),
        rsi_score=round(rsi_score, 4), macd_score=round(macd_score, 4),
        bollinger_score=round(boll_score, 4), strategy=strategy,
    ).model_dump()

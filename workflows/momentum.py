"""Momentum analysis workflow — RSI, MACD, momentum score, 52-week range."""

from __future__ import annotations

from infra.observability import get_logger
from workflows.base import write_analysis_report

logger = get_logger("workflows.momentum")


async def run_momentum_analysis(session_id: str, symbol: str) -> dict:
    """Run the full momentum analysis pipeline for one symbol and write a markdown report.

    Calls existing analysis and market tools directly (no LLM). Writes the report to
    reports/{session_id}/analysis/{symbol}_MOMENTUM_{ts}.md and registers it in
    session_files.

    Args:
        session_id: Active session UUID.
        symbol: ETF ticker symbol to analyse.

    Returns:
        dict with 'report_path', 'symbol', 'strategy'.
    """
    logger.info("run_momentum_analysis symbol=%s session=%s", symbol, session_id)

    from tools.analysis.tools import (
        compute_macd,
        compute_rsi,
        detect_crossover,
        detect_momentum,
        score_technical,
    )
    from tools.market.tools import get_52w_range, get_ohlcv

    # Fetch OHLCV data
    ohlcv = await get_ohlcv(symbol, "1Day", 60)
    bars = ohlcv.get("bars", [])
    closes = [b["close"] for b in bars if b.get("close") is not None]
    volumes = [b["volume"] for b in bars if b.get("volume") is not None]

    sections: list[str] = [f"# Momentum Analysis — {symbol}\n"]

    if len(closes) < 26:
        sections.append("_Insufficient price history for momentum analysis._\n")
        content = "\n".join(sections)
        report_path = write_analysis_report(session_id, symbol, "MOMENTUM", content)
        return {"report_path": report_path, "symbol": symbol, "strategy": "MOMENTUM"}

    # RSI
    rsi = await compute_rsi(symbol, closes, period=14)
    sections.append(
        f"## RSI (14)\n"
        f"- Current: **{rsi.get('current', 'N/A')}**\n"
        f"- Overbought: {rsi.get('is_overbought')}, Oversold: {rsi.get('is_oversold')}\n"
    )

    # MACD
    macd = await compute_macd(symbol, closes)
    sections.append(
        f"## MACD\n"
        f"- MACD: {macd.get('current_macd', 'N/A')}, Signal: {macd.get('current_signal', 'N/A')}\n"
        f"- Histogram: {macd.get('current_histogram', 'N/A')}\n"
    )

    # Crossover
    histogram = macd.get("histogram") or []
    crossover = await detect_crossover(symbol, histogram)
    sections.append(
        f"## Crossover\n"
        f"- Type: {crossover.get('crossover_type', 'none')}, "
        f"Bars since: {crossover.get('bars_since_crossover', 'N/A')}, "
        f"Strength: {crossover.get('strength', 'N/A')}\n"
    )

    # Momentum score
    momentum = await detect_momentum(symbol, closes, volumes[: len(closes)])
    sections.append(
        f"## Momentum Score\n"
        f"- Combined: **{momentum.get('momentum_score', 'N/A')}**\n"
        f"- RSI contribution: {momentum.get('rsi_contribution', 'N/A')}\n"
        f"- MACD contribution: {momentum.get('macd_contribution', 'N/A')}\n"
        f"- Price vs SMA: {momentum.get('price_vs_sma_contribution', 'N/A')}\n"
        f"- Volume trend: {momentum.get('volume_trend_contribution', 'N/A')}\n"
    )

    # Technical composite score
    tech = await score_technical(symbol, closes, strategy="MOMENTUM")
    sections.append(
        f"## Technical Score\n"
        f"- Composite: **{tech.get('composite_score', 'N/A')}**\n"
        f"- RSI: {tech.get('rsi_score', 'N/A')}, MACD: {tech.get('macd_score', 'N/A')}, "
        f"Bollinger: {tech.get('bollinger_score', 'N/A')}\n"
    )

    # 52-week range context
    range_52w = await get_52w_range(symbol)
    sections.append(
        f"## 52-Week Range\n"
        f"- High: {range_52w.get('high_52w', 'N/A')}, Low: {range_52w.get('low_52w', 'N/A')}\n"
        f"- Current: {range_52w.get('current_price', 'N/A')}\n"
        f"- % from high: {range_52w.get('pct_from_high', 'N/A')}, "
        f"% from low: {range_52w.get('pct_from_low', 'N/A')}\n"
    )

    content = "\n".join(sections)
    report_path = write_analysis_report(session_id, symbol, "MOMENTUM", content)
    return {"report_path": report_path, "symbol": symbol, "strategy": "MOMENTUM"}

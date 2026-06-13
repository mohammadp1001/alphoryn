"""Mean-reversion analysis workflow — Bollinger Bands, ATR, support/resistance."""

from __future__ import annotations

from infra.observability import get_logger
from workflows.base import write_analysis_report

logger = get_logger("workflows.mean_reversion")


async def run_mean_reversion_analysis(session_id: str, symbol: str) -> dict:
    """Run the full mean-reversion analysis pipeline for one symbol.

    Writes a markdown report to reports/{session_id}/analysis/{symbol}_MEAN_REVERSION_{ts}.md
    and registers it in session_files.

    Args:
        session_id: Active session UUID.
        symbol: ETF ticker symbol to analyse.

    Returns:
        dict with 'report_path', 'symbol', 'strategy'.
    """
    logger.info("run_mean_reversion_analysis symbol=%s session=%s", symbol, session_id)

    from tools.analysis.tools import (
        compute_atr,
        compute_bollinger,
        detect_support_resistance,
        score_technical,
    )
    from tools.data import get_ohlcv

    ohlcv = await get_ohlcv(symbol, "1Day", 60)
    bars = ohlcv.get("bars", [])
    closes = [b["close"] for b in bars if b.get("close") is not None]
    highs = [b["high"] for b in bars if b.get("high") is not None]
    lows = [b["low"] for b in bars if b.get("low") is not None]

    sections: list[str] = [f"# Mean-Reversion Analysis — {symbol}\n"]

    if len(closes) < 20:
        sections.append("_Insufficient price history for mean-reversion analysis._\n")
        content = "\n".join(sections)
        report_path = write_analysis_report(session_id, symbol, "MEAN_REVERSION", content)
        return {"report_path": report_path, "symbol": symbol, "strategy": "MEAN_REVERSION"}

    # Bollinger Bands
    bb = await compute_bollinger(symbol, closes, period=20)
    sections.append(
        f"## Bollinger Bands (20)\n"
        f"- Upper: {bb.get('current_upper', 'N/A')}, "
        f"Middle: {bb.get('current_middle', 'N/A')}, "
        f"Lower: {bb.get('current_lower', 'N/A')}\n"
        f"- Price: {bb.get('current_price', 'N/A')}, "
        f"%B: **{bb.get('pct_b', 'N/A')}**, Bandwidth: {bb.get('bandwidth', 'N/A')}\n"
    )

    # ATR
    n = min(len(closes), len(highs), len(lows))
    atr = await compute_atr(symbol, closes[:n], highs[:n], lows[:n], period=14)
    sections.append(f"## ATR (14)\n- Current ATR: **{atr.get('current', 'N/A')}**\n")

    # Support / Resistance
    sr = await detect_support_resistance(symbol, closes, highs, lows)
    sections.append(
        f"## Support & Resistance\n"
        f"- Nearest support: {sr.get('nearest_support', 'N/A')}\n"
        f"- Nearest resistance: {sr.get('nearest_resistance', 'N/A')}\n"
        f"- Levels found: {len(sr.get('levels', []))}\n"
    )

    # Technical composite score
    tech = await score_technical(symbol, closes, strategy="MEAN_REVERSION")
    sections.append(
        f"## Technical Score\n"
        f"- Composite: **{tech.get('composite_score', 'N/A')}**\n"
        f"- RSI: {tech.get('rsi_score', 'N/A')}, MACD: {tech.get('macd_score', 'N/A')}, "
        f"Bollinger: {tech.get('bollinger_score', 'N/A')}\n"
    )

    content = "\n".join(sections)
    report_path = write_analysis_report(session_id, symbol, "MEAN_REVERSION", content)
    return {"report_path": report_path, "symbol": symbol, "strategy": "MEAN_REVERSION"}

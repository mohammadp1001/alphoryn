"""Sector-rotation analysis workflow — sector performance, fund flows, expense ratio, beta."""

from __future__ import annotations

from infra.observability import get_logger
from workflows.base import write_analysis_report

logger = get_logger("workflows.sector_rotation")


async def run_sector_rotation_analysis(session_id: str, symbol: str) -> dict:
    """Run the full sector-rotation analysis pipeline for one symbol.

    Writes a markdown report to reports/{session_id}/analysis/{symbol}_SECTOR_ROTATION_{ts}.md
    and registers it in session_files.

    Args:
        session_id: Active session UUID.
        symbol: ETF ticker symbol to analyse.

    Returns:
        dict with 'report_path', 'symbol', 'strategy'.
    """
    logger.info("run_sector_rotation_analysis symbol=%s session=%s", symbol, session_id)

    from tools.analysis.tools import compute_beta
    from tools.data import get_ohlcv
    from tools.fundamentals import get_etf_metrics, get_fund_flows, get_sector_performance

    ohlcv = await get_ohlcv(symbol, "1Day", 60)
    bars = ohlcv.get("bars", [])
    closes = [b["close"] for b in bars if b.get("close") is not None]

    sections: list[str] = [f"# Sector-Rotation Analysis — {symbol}\n"]

    # ETF metrics (AUM, expense ratio, NAV)
    metrics = await get_etf_metrics(symbol)
    sections.append(
        f"## ETF Metrics\n"
        f"- AUM: ${metrics.get('aum_usd', 'N/A'):,}\n"
        f"- Expense ratio: {metrics.get('expense_ratio', 'N/A')}\n"
        f"- NAV: {metrics.get('nav', 'N/A')}\n"
        f"- Shares outstanding: {metrics.get('shares_outstanding', 'N/A')}\n"
    )

    # Fund flows
    flows = await get_fund_flows(symbol)
    sections.append(
        f"## Fund Flows\n"
        f"- Direction: **{flows.get('flow_direction', 'N/A')}**\n"
        f"- Estimated flow (USD): {flows.get('estimated_flow_usd', 'N/A')}\n"
    )

    # Sector performance
    sector_perf = await get_sector_performance(timeframe="1mo", symbols=[symbol])
    returns = sector_perf.get("returns", [])
    if returns:
        sections.append("## Sector Performance (1 month)\n")
        for r in returns:
            sections.append(
                f"- {r.get('symbol', '?')} ({r.get('sector', 'Unknown')}): "
                f"{r.get('return_pct', 'N/A')}%\n"
            )

    # Beta vs SPY
    if len(closes) >= 20:
        spy_ohlcv = await get_ohlcv("SPY", "1Day", 60)
        spy_bars = spy_ohlcv.get("bars", [])
        spy_closes = [b["close"] for b in spy_bars if b.get("close") is not None]
        n = min(len(closes), len(spy_closes))
        if n >= 20:
            beta = await compute_beta(symbol, closes[:n], spy_closes[:n], period_days=n)
            sections.append(
                f"## Beta vs SPY\n"
                f"- Beta: **{beta.get('beta', 'N/A')}**, "
                f"R²: {beta.get('r_squared', 'N/A')}, "
                f"Period: {beta.get('period_days', n)} days\n"
            )

    content = "\n".join(sections)
    report_path = write_analysis_report(session_id, symbol, "SECTOR_ROTATION", content)
    return {"report_path": report_path, "symbol": symbol, "strategy": "SECTOR_ROTATION"}

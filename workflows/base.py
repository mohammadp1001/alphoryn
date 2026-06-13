"""Shared helper for writing analysis markdown reports to disk."""

from __future__ import annotations

from datetime import UTC, datetime

import config
from db.schema import register_session_file
from infra.observability import get_logger

logger = get_logger("workflows.base")


def write_analysis_report(session_id: str, symbol: str, strategy: str, content: str) -> str:
    """Write markdown content to disk and register the path in session_files.

    Args:
        session_id: Active session UUID.
        symbol: ETF ticker symbol.
        strategy: Strategy name (e.g. 'MOMENTUM').
        content: Markdown string to write.

    Returns:
        Absolute path of the written file as a string.
    """
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = config.REPORTS_DIR / session_id / "analysis" / f"{symbol}_{strategy}_{ts}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    register_session_file(
        session_id=session_id,
        path=str(path),
        file_type="analysis",
        symbol=symbol,
    )
    logger.info("wrote analysis report path=%s", path)
    return str(path)

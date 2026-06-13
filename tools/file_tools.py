"""file.* tools — read_file, write_file, register_session_file."""

from __future__ import annotations

import re
from pathlib import Path

from infra.observability import get_logger
from tools.schemas import ReadFileResponse, RegisterFileResponse, WriteFileResponse

logger = get_logger("tools.file")


async def read_file(path: str) -> dict:
    """Read the full content of a file from disk.

    Args:
        path: Absolute or relative path to the file.

    Returns:
        dict with 'path', 'content' (str or null if not found), 'found' (bool).
    """
    logger.info("read_file path=%s", path)
    p = Path(path)
    if not p.exists():
        return ReadFileResponse(path=path, content=None, found=False).model_dump()
    content = p.read_text(encoding="utf-8")
    return ReadFileResponse(path=path, content=content, found=True).model_dump()


async def write_file(path: str, content: str) -> dict:
    """Write text content to a file, creating parent directories as needed.

    Args:
        path: Destination file path (absolute or relative).
        content: Text content to write.

    Returns:
        dict with 'path' and 'written': true.
    """
    logger.info("write_file path=%s bytes=%d", path, len(content))
    p = Path(path)
    # Strip characters that are illegal in Windows filenames (colons, etc.) from the
    # final path component only — directory separators in the parent are intentional.
    safe_name = re.sub(r'[<>:"|?*]', "-", p.name)
    p = p.parent / safe_name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return WriteFileResponse(path=str(p), written=True).model_dump()


async def register_session_file(
    session_id: str,
    path: str,
    file_type: str,
    symbol: str = "",
) -> dict:
    """Register a written file in the session_files SQLite table.

    Args:
        session_id: UUID of the current session.
        path: Path to the file that was written.
        file_type: Category of the file ('research', 'analysis', 'report').
        symbol: Ticker symbol this file relates to, or empty string if none.

    Returns:
        dict with 'file_id' (UUID) and 'registered': true.
    """
    logger.info(
        "register_session_file session_id=%s file_type=%s path=%s", session_id, file_type, path
    )
    from db.schema import register_session_file as _register

    sym = symbol if symbol else None
    file_id = _register(session_id=session_id, path=path, file_type=file_type, symbol=sym)
    return RegisterFileResponse(file_id=file_id, registered=True).model_dump()

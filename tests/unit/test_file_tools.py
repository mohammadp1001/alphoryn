"""Unit tests for tools.file_tools and related db/schema helpers."""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

# ── DB fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "test.db"
    monkeypatch.setattr("config.DB_PATH", db_file)
    from db.schema import init_db
    init_db(db_file)
    return db_file


def _connect_to(db_file: Path):
    @contextmanager
    def _ctx(path=None):
        conn = sqlite3.connect(str(path or db_file), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return _ctx


def _insert_session(db_file: Path, session_id: str) -> None:
    import datetime
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "INSERT INTO sessions (id, started_at, strategy, mode) VALUES (?, ?, ?, ?)",
        (session_id, datetime.datetime.utcnow().isoformat(), "MOMENTUM", "SEMI_AUTO"),
    )
    conn.commit()
    conn.close()


# ── db.schema: session_files table ───────────────────────────────────────────

def test_init_db_creates_session_files_table(tmp_db: Path) -> None:
    conn = sqlite3.connect(str(tmp_db))
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    assert "session_files" in tables


def test_register_session_file_returns_uuid(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-1")
    from db.schema import register_session_file
    file_id = register_session_file("sess-1", "/reports/sess-1/research/SPY.md", "research", "SPY")
    assert isinstance(file_id, str)
    assert len(file_id) == 36  # UUID format


def test_register_session_file_persists_row(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-2")
    from db.schema import register_session_file
    file_id = register_session_file("sess-2", "/reports/sess-2/analysis/SPY_momentum.md", "analysis", "SPY")
    conn = sqlite3.connect(str(tmp_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM session_files WHERE id = ?", (file_id,)).fetchone()
    conn.close()
    assert row is not None
    assert row["session_id"] == "sess-2"
    assert row["symbol"] == "SPY"
    assert row["file_type"] == "analysis"
    assert row["path"] == "/reports/sess-2/analysis/SPY_momentum.md"


def test_register_session_file_null_symbol(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-3")
    from db.schema import register_session_file
    file_id = register_session_file("sess-3", "/reports/sess-3/report.html", "report")
    conn = sqlite3.connect(str(tmp_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM session_files WHERE id = ?", (file_id,)).fetchone()
    conn.close()
    assert row["symbol"] is None


def test_get_session_files_db_no_filters(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-4")
    from db.schema import get_session_files_db, register_session_file
    register_session_file("sess-4", "/a.md", "research", "SPY")
    register_session_file("sess-4", "/b.md", "analysis", "QQQ")
    rows = get_session_files_db("sess-4")
    assert len(rows) == 2


def test_get_session_files_db_filter_by_file_type(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-5")
    from db.schema import get_session_files_db, register_session_file
    register_session_file("sess-5", "/a.md", "research", "SPY")
    register_session_file("sess-5", "/b.md", "analysis", "SPY")
    rows = get_session_files_db("sess-5", file_type="research")
    assert len(rows) == 1
    assert rows[0]["file_type"] == "research"


def test_get_session_files_db_filter_by_symbol(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-6")
    from db.schema import get_session_files_db, register_session_file
    register_session_file("sess-6", "/a.md", "research", "SPY")
    register_session_file("sess-6", "/b.md", "research", "QQQ")
    rows = get_session_files_db("sess-6", symbol="SPY")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SPY"


def test_get_session_files_db_filter_by_both(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-7")
    from db.schema import get_session_files_db, register_session_file
    register_session_file("sess-7", "/a.md", "research", "SPY")
    register_session_file("sess-7", "/b.md", "analysis", "SPY")
    register_session_file("sess-7", "/c.md", "research", "QQQ")
    rows = get_session_files_db("sess-7", file_type="research", symbol="SPY")
    assert len(rows) == 1
    assert rows[0]["path"] == "/a.md"


def test_get_session_files_db_empty_result(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-8")
    from db.schema import get_session_files_db
    rows = get_session_files_db("sess-8")
    assert rows == []


# ── tools.file_tools: read_file ───────────────────────────────────────────────

def test_read_file_exists(tmp_path: Path) -> None:
    f = tmp_path / "report.md"
    f.write_text("# Hello", encoding="utf-8")
    from tools.file_tools import read_file
    result = asyncio.run(read_file(str(f)))
    assert result["found"] is True
    assert result["content"] == "# Hello"
    assert result["path"] == str(f)


def test_read_file_not_found(tmp_path: Path) -> None:
    from tools.file_tools import read_file
    result = asyncio.run(read_file(str(tmp_path / "missing.md")))
    assert result["found"] is False
    assert result["content"] is None


# ── tools.file_tools: write_file ──────────────────────────────────────────────

def test_write_file_creates_file_and_dirs(tmp_path: Path) -> None:
    dest = tmp_path / "deep" / "nested" / "file.html"
    from tools.file_tools import write_file
    result = asyncio.run(write_file(str(dest), "<html/>"))
    assert result["written"] is True
    assert result["path"] == str(dest)
    assert dest.read_text(encoding="utf-8") == "<html/>"


def test_write_file_overwrites_existing(tmp_path: Path) -> None:
    f = tmp_path / "existing.md"
    f.write_text("old content", encoding="utf-8")
    from tools.file_tools import write_file
    asyncio.run(write_file(str(f), "new content"))
    assert f.read_text(encoding="utf-8") == "new content"


# ── tools.file_tools: register_session_file ───────────────────────────────────

def test_register_session_file_tool_with_symbol(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-reg-1")
    from tools.file_tools import register_session_file
    result = asyncio.run(register_session_file("sess-reg-1", "/r.md", "research", "SPY"))
    assert result["registered"] is True
    assert isinstance(result["file_id"], str)


def test_register_session_file_tool_empty_symbol_stores_null(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-reg-2")
    from db.schema import get_session_files_db
    from tools.file_tools import register_session_file
    result = asyncio.run(register_session_file("sess-reg-2", "/report.html", "report", ""))
    assert result["registered"] is True
    rows = get_session_files_db("sess-reg-2")
    assert rows[0]["symbol"] is None


# ── tools.memory.tools: get_session_files ─────────────────────────────────────

def test_get_session_files_tool_no_filters(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-gf-1")
    from db.schema import register_session_file
    register_session_file("sess-gf-1", "/a.md", "research", "SPY")
    register_session_file("sess-gf-1", "/b.md", "analysis", "QQQ")

    from tools.memory.tools import get_session_files
    result = asyncio.run(get_session_files("sess-gf-1"))
    assert result["session_id"] == "sess-gf-1"
    assert len(result["files"]) == 2


def test_get_session_files_tool_filter_file_type(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-gf-2")
    from db.schema import register_session_file
    register_session_file("sess-gf-2", "/a.md", "research", "SPY")
    register_session_file("sess-gf-2", "/b.md", "analysis", "SPY")

    from tools.memory.tools import get_session_files
    result = asyncio.run(get_session_files("sess-gf-2", file_type="analysis"))
    assert len(result["files"]) == 1
    assert result["files"][0]["file_type"] == "analysis"


def test_get_session_files_tool_filter_symbol(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-gf-3")
    from db.schema import register_session_file
    register_session_file("sess-gf-3", "/a.md", "research", "SPY")
    register_session_file("sess-gf-3", "/b.md", "research", "QQQ")

    from tools.memory.tools import get_session_files
    result = asyncio.run(get_session_files("sess-gf-3", symbol="QQQ"))
    assert len(result["files"]) == 1
    assert result["files"][0]["symbol"] == "QQQ"


def test_get_session_files_tool_empty_result(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-gf-4")

    from tools.memory.tools import get_session_files
    result = asyncio.run(get_session_files("sess-gf-4"))
    assert result["session_id"] == "sess-gf-4"
    assert result["files"] == []


def test_get_session_files_tool_empty_strings_act_as_no_filter(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("db.schema._connect", _connect_to(tmp_db))
    _insert_session(tmp_db, "sess-gf-5")
    from db.schema import register_session_file
    register_session_file("sess-gf-5", "/a.md", "research", "SPY")
    register_session_file("sess-gf-5", "/b.md", "analysis", "QQQ")

    from tools.memory.tools import get_session_files
    result = asyncio.run(get_session_files("sess-gf-5", file_type="", symbol=""))
    assert len(result["files"]) == 2


# ── Pydantic schema models ─────────────────────────────────────────────────────

def test_read_file_response_model() -> None:
    from tools.schemas import ReadFileResponse
    r = ReadFileResponse(path="/x.md", content="hello", found=True)
    d = r.model_dump()
    assert d["found"] is True
    assert d["content"] == "hello"


def test_write_file_response_model() -> None:
    from tools.schemas import WriteFileResponse
    r = WriteFileResponse(path="/x.html", written=True)
    d = r.model_dump()
    assert d["written"] is True


def test_register_file_response_model() -> None:
    from tools.schemas import RegisterFileResponse
    r = RegisterFileResponse(file_id="abc-123", registered=True)
    d = r.model_dump()
    assert d["file_id"] == "abc-123"
    assert d["registered"] is True


def test_session_file_entry_model() -> None:
    from tools.schemas import SessionFileEntry
    e = SessionFileEntry(
        id="id-1",
        session_id="sess-x",
        symbol="SPY",
        file_type="research",
        path="/r.md",
        created_at="2026-06-12T00:00:00",
    )
    assert e.symbol == "SPY"


def test_session_files_response_model() -> None:
    from tools.schemas import SessionFileEntry, SessionFilesResponse
    entries = [
        SessionFileEntry(
            id="id-1",
            session_id="sess-x",
            symbol=None,
            file_type="report",
            path="/r.html",
            created_at="2026-06-12T00:00:00",
        )
    ]
    r = SessionFilesResponse(session_id="sess-x", files=entries)
    d = r.model_dump()
    assert len(d["files"]) == 1
    assert d["files"][0]["symbol"] is None

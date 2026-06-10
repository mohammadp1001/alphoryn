"""Unit tests for infra.tool_logger — _serialise, log_io decorator."""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch


# ── _serialise ────────────────────────────────────────────────────────────────

def test_serialise_simple_value():
    from infra.tool_logger import _serialise
    result = _serialise({"symbol": "XLK", "bars": 20})
    assert "XLK" in result


def test_serialise_non_json_falls_back_to_repr():
    from infra.tool_logger import _serialise

    class Obj:
        def __repr__(self):
            return "MyObj()"

    result = _serialise(Obj())
    assert "MyObj()" in result


def test_serialise_long_output_truncated():
    from infra.tool_logger import _MAX_CHARS, _serialise

    big = {"key": "v" * (_MAX_CHARS * 2)}
    result = _serialise(big)
    assert "…(truncated)" in result
    assert len(result) <= _MAX_CHARS + len(" …(truncated)")


def test_serialise_short_output_not_truncated():
    from infra.tool_logger import _serialise
    result = _serialise("short")
    assert "…(truncated)" not in result


# ── log_io decorator ──────────────────────────────────────────────────────────

def test_log_io_returns_result():
    from infra.tool_logger import log_io

    @log_io
    async def my_tool(symbol: str, bars: int) -> dict:
        return {"symbol": symbol, "bars": bars}

    result = asyncio.run(my_tool("XLK", 20))
    assert result == {"symbol": "XLK", "bars": 20}


def test_log_io_preserves_function_name():
    from infra.tool_logger import log_io

    @log_io
    async def my_named_tool() -> dict:
        return {}

    assert my_named_tool.__name__ == "my_named_tool"


def test_log_io_logs_input_at_debug(caplog):
    from infra.tool_logger import log_io

    @log_io
    async def get_quote(symbol: str) -> dict:
        return {"symbol": symbol, "bid": 100.0}

    with caplog.at_level(logging.DEBUG, logger="tools"):
        asyncio.run(get_quote("XLK"))

    assert any("get_quote" in r.message for r in caplog.records)
    assert any("XLK" in r.message for r in caplog.records)


def test_log_io_logs_output_at_debug(caplog):
    from infra.tool_logger import log_io

    @log_io
    async def get_ohlcv(symbol: str) -> dict:
        return {"symbol": symbol, "bars": []}

    with caplog.at_level(logging.DEBUG, logger="tools"):
        asyncio.run(get_ohlcv("SPY"))

    assert any("SPY" in r.message for r in caplog.records)


def test_log_io_reraises_exception(caplog):
    from infra.tool_logger import log_io

    import pytest

    @log_io
    async def broken_tool(symbol: str) -> dict:
        raise ValueError("bad symbol")

    with (
        caplog.at_level(logging.ERROR, logger="tools"),
        pytest.raises(ValueError, match="bad symbol"),
    ):
        asyncio.run(broken_tool("BAD"))

    assert any("broken_tool" in r.message for r in caplog.records)


def test_log_io_logs_error_on_exception(caplog):
    from infra.tool_logger import log_io

    import pytest

    @log_io
    async def fail_tool() -> dict:
        raise RuntimeError("crash")

    with (
        caplog.at_level(logging.ERROR, logger="tools"),
        pytest.raises(RuntimeError),
    ):
        asyncio.run(fail_tool())

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) > 0
    assert any("fail_tool" in r.message for r in error_records)


def test_log_io_handles_kwargs():
    from infra.tool_logger import log_io

    @log_io
    async def kw_tool(*, depth: int = 5) -> dict:
        return {"depth": depth}

    result = asyncio.run(kw_tool(depth=10))
    assert result == {"depth": 10}


def test_log_io_args_serialization_error_falls_back():
    from infra.tool_logger import log_io

    @log_io
    async def tricky_tool(value: object) -> dict:
        return {"ok": True}

    # Call with a non-serializable positional arg — should not raise
    class Weird:
        pass

    result = asyncio.run(tricky_tool(Weird()))
    assert result == {"ok": True}


def test_tool_logger_serialise_str_raises_falls_back_to_repr():
    """Lines 26-27: when json.dumps(default=str) fails because str() raises, repr() is used."""
    from infra.tool_logger import _serialise

    class StrRaises:
        def __str__(self):
            raise ValueError("no str")

        def __repr__(self):
            return "StrRaises()"

    result = _serialise(StrRaises())
    assert "StrRaises()" in result


def test_log_io_sig_bind_exception_falls_back():
    """Lines 46-47: when inspect.signature raises, args_repr falls back to repr."""
    import infra.tool_logger as tl_mod
    from infra.tool_logger import log_io
    from unittest.mock import patch

    @log_io
    async def simple_fn(x: int) -> int:
        return x + 1

    with patch.object(tl_mod.inspect, "signature", side_effect=Exception("sig fail")):
        result = asyncio.run(simple_fn(5))

    assert result == 6

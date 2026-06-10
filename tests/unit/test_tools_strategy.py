"""Unit tests for tools.strategy.tools — list_strategies, get_strategy, describe_tool."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch


def _mock_yaml(data: dict):
    """Return a sys.modules patch that makes yaml.safe_load return data."""
    mock_yaml = MagicMock()
    mock_yaml.safe_load.return_value = data
    return {"yaml": mock_yaml}


# ── _load_yaml ────────────────────────────────────────────────────────────────

def test_load_yaml_reads_file(tmp_path):
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text("name: TEST")

    with patch.dict("sys.modules", _mock_yaml({"name": "TEST"})):
        from tools.strategy.tools import _load_yaml
        result = _load_yaml(yaml_file)

    assert result == {"name": "TEST"}


def test_load_yaml_empty_file_returns_empty_dict(tmp_path):
    yaml_file = tmp_path / "empty.yaml"
    yaml_file.write_text("")

    mock_yaml = MagicMock()
    mock_yaml.safe_load.return_value = None  # yaml.safe_load on empty → None

    with patch.dict("sys.modules", {"yaml": mock_yaml}):
        from tools.strategy.tools import _load_yaml
        result = _load_yaml(yaml_file)

    assert result == {}


# ── list_strategies ───────────────────────────────────────────────────────────

def test_list_strategies_returns_list(tmp_path):
    (tmp_path / "momentum.yaml").write_text("name: MOMENTUM")

    strategy_data = {
        "name": "MOMENTUM",
        "description": "Buy high-momentum ETFs",
        "preferred_regimes": ["BULL_TREND"],
        "asset_classes": ["etf"],
    }

    import tools.strategy.tools as st
    with (
        patch.object(st, "_STRATEGIES_DIR", tmp_path),
        patch.dict("sys.modules", _mock_yaml(strategy_data)),
    ):
        result = asyncio.run(st.list_strategies())

    assert result["count"] == 1
    assert result["strategies"][0]["name"] == "MOMENTUM"
    assert result["strategies"][0]["preferred_regimes"] == ["BULL_TREND"]


def test_list_strategies_empty_dir(tmp_path):
    import tools.strategy.tools as st
    with patch.object(st, "_STRATEGIES_DIR", tmp_path):
        result = asyncio.run(st.list_strategies())

    assert result["count"] == 0
    assert result["strategies"] == []


def test_list_strategies_skips_bad_yaml(tmp_path):
    (tmp_path / "bad.yaml").write_text("invalid: yaml: content")

    mock_yaml = MagicMock()
    mock_yaml.safe_load.side_effect = Exception("parse error")

    import tools.strategy.tools as st
    with (
        patch.object(st, "_STRATEGIES_DIR", tmp_path),
        patch.dict("sys.modules", {"yaml": mock_yaml}),
    ):
        result = asyncio.run(st.list_strategies())

    assert result["count"] == 0  # bad file was skipped


def test_list_strategies_description_truncated_at_200(tmp_path):
    (tmp_path / "long.yaml").write_text("name: LONG")

    long_desc = "x" * 300
    strategy_data = {"name": "LONG", "description": long_desc}

    import tools.strategy.tools as st
    with (
        patch.object(st, "_STRATEGIES_DIR", tmp_path),
        patch.dict("sys.modules", _mock_yaml(strategy_data)),
    ):
        result = asyncio.run(st.list_strategies())

    assert len(result["strategies"][0]["description"]) <= 200


def test_list_strategies_multiple_files(tmp_path):
    (tmp_path / "momentum.yaml").write_text("name: MOMENTUM")
    (tmp_path / "mean_reversion.yaml").write_text("name: MEAN_REVERSION")

    mock_yaml = MagicMock()
    mock_yaml.safe_load.side_effect = [
        {"name": "MEAN_REVERSION", "description": "Revert to mean", "preferred_regimes": [], "asset_classes": []},
        {"name": "MOMENTUM", "description": "Buy momentum", "preferred_regimes": [], "asset_classes": []},
    ]

    import tools.strategy.tools as st
    with (
        patch.object(st, "_STRATEGIES_DIR", tmp_path),
        patch.dict("sys.modules", {"yaml": mock_yaml}),
    ):
        result = asyncio.run(st.list_strategies())

    assert result["count"] == 2


# ── get_strategy ──────────────────────────────────────────────────────────────

def test_get_strategy_found_by_name(tmp_path):
    (tmp_path / "momentum.yaml").write_text("name: MOMENTUM")

    strategy_data = {"name": "MOMENTUM", "description": "Buy high-momentum ETFs"}

    import tools.strategy.tools as st
    with (
        patch.object(st, "_STRATEGIES_DIR", tmp_path),
        patch.dict("sys.modules", _mock_yaml(strategy_data)),
    ):
        result = asyncio.run(st.get_strategy("MOMENTUM"))

    assert result["name"] == "MOMENTUM"


def test_get_strategy_found_case_insensitive(tmp_path):
    (tmp_path / "momentum.yaml").write_text("name: MOMENTUM")

    strategy_data = {"name": "MOMENTUM", "description": "Momentum strategy"}

    import tools.strategy.tools as st
    with (
        patch.object(st, "_STRATEGIES_DIR", tmp_path),
        patch.dict("sys.modules", _mock_yaml(strategy_data)),
    ):
        result = asyncio.run(st.get_strategy("momentum"))

    assert result["name"] == "MOMENTUM"


def test_get_strategy_not_found(tmp_path):
    (tmp_path / "momentum.yaml").write_text("name: MOMENTUM")

    import tools.strategy.tools as st
    with (
        patch.object(st, "_STRATEGIES_DIR", tmp_path),
        patch.dict("sys.modules", _mock_yaml({"name": "MOMENTUM"})),
    ):
        result = asyncio.run(st.get_strategy("NONEXISTENT"))

    assert result["error"] == "not_found"
    assert result["name"] == "NONEXISTENT"


def test_get_strategy_found_by_stem(tmp_path):
    (tmp_path / "sector_rotation.yaml").write_text("name: SECTOR_ROTATION")

    strategy_data = {"name": "SECTOR_ROTATION", "description": "Rotate sectors"}

    import tools.strategy.tools as st
    with (
        patch.object(st, "_STRATEGIES_DIR", tmp_path),
        patch.dict("sys.modules", _mock_yaml(strategy_data)),
    ):
        result = asyncio.run(st.get_strategy("sector_rotation"))

    assert result["name"] == "SECTOR_ROTATION"


def test_get_strategy_skips_bad_yaml_and_returns_not_found(tmp_path):
    (tmp_path / "bad.yaml").write_text("broken:")

    mock_yaml = MagicMock()
    mock_yaml.safe_load.side_effect = Exception("parse error")

    import tools.strategy.tools as st
    with (
        patch.object(st, "_STRATEGIES_DIR", tmp_path),
        patch.dict("sys.modules", {"yaml": mock_yaml}),
    ):
        result = asyncio.run(st.get_strategy("BAD"))

    assert result["error"] == "not_found"


# ── describe_tool ─────────────────────────────────────────────────────────────

def test_describe_tool_not_found():
    import tools.strategy.tools as st
    result = asyncio.run(st.describe_tool("nonexistent__tool_xyz_abc"))
    assert result["error"] == "not_found"
    assert result["tool_name"] == "nonexistent__tool_xyz_abc"


def test_describe_tool_found():
    import tools.strategy.tools as st
    # market__get_ohlcv is a real registered tool
    result = asyncio.run(st.describe_tool("market__get_ohlcv"))
    assert result["tool_name"] == "market__get_ohlcv"
    assert "docstring" in result
    assert isinstance(result["parameters"], list)


def test_describe_tool_has_parameter_info():
    import tools.strategy.tools as st
    result = asyncio.run(st.describe_tool("market__get_ohlcv"))
    # get_ohlcv has parameters: symbol, timeframe, bars
    param_names = [p["name"] for p in result["parameters"]]
    assert "symbol" in param_names


def test_describe_tool_skips_tool_context_param():
    """Line 101: parameters named 'tool_context' or 'self' are filtered out."""
    from unittest.mock import MagicMock, patch

    def fake_tool(x: int, tool_context: object, self: object) -> dict:  # type: ignore[misc]
        return {}

    mock_ft = MagicMock()
    mock_ft.name = "test__fake_tool"
    mock_ft.func = fake_tool
    mock_ft.func.__name__ = "test__fake_tool"

    import tools.strategy.tools as st
    with patch("tools.registry.MARKET_TOOLS", [mock_ft]):
        result = asyncio.run(st.describe_tool("test__fake_tool"))

    param_names = [p["name"] for p in result["parameters"]]
    assert "tool_context" not in param_names
    assert "self" not in param_names
    assert "x" in param_names

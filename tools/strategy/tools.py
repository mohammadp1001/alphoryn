"""strategy.* tools — read trading strategy definitions from strategies/ YAML files."""
from __future__ import annotations

from pathlib import Path

from infra.observability import get_logger

logger = get_logger("tools.strategy")

_STRATEGIES_DIR = Path(__file__).parent.parent.parent / "strategies"


def _load_yaml(path: Path) -> dict:
    import yaml  # type: ignore[import]
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


async def list_strategies() -> dict:
    """List all available trading strategies with their names and one-line descriptions.

    Returns:
        dict with 'strategies' (list of {name, description, preferred_regimes, asset_classes}).
        Call get_strategy(name) to load the full specification for a chosen strategy.
    """
    logger.info("list_strategies dir=%s", _STRATEGIES_DIR)
    results = []
    for path in sorted(_STRATEGIES_DIR.glob("*.yaml")):
        try:
            data = _load_yaml(path)
            results.append({
                "name": data.get("name", path.stem.upper()),
                "description": (data.get("description") or "").strip()[:200],
                "preferred_regimes": data.get("preferred_regimes", []),
                "asset_classes": data.get("asset_classes", []),
            })
        except Exception as exc:
            logger.warning("list_strategies skipping %s: %s", path.name, exc)
    return {"strategies": results, "count": len(results)}


async def get_strategy(name: str) -> dict:
    """Load the full specification for a named trading strategy.

    Args:
        name: Strategy name (case-insensitive), e.g. 'MOMENTUM', 'MEAN_REVERSION'.

    Returns:
        dict with all strategy fields: name, description, preferred_regimes,
        avoid_regimes, asset_classes, entry_rules, exit_rules, order_type,
        position_sizing, scoring_weights.
        Returns {'error': 'not_found', 'name': name} if the strategy does not exist.
    """
    logger.info("get_strategy name=%s", name)
    target = name.strip().lower()
    for path in _STRATEGIES_DIR.glob("*.yaml"):
        try:
            data = _load_yaml(path)
            if data.get("name", "").lower() == target or path.stem.lower() == target:
                return data
        except Exception as exc:
            logger.warning("get_strategy error reading %s: %s", path.name, exc)
    return {"error": "not_found", "name": name, "available": [
        p.stem.upper() for p in sorted(_STRATEGIES_DIR.glob("*.yaml"))
    ]}


async def describe_tool(tool_name: str) -> dict:
    """Return the full description and parameter list for a named tool.

    Use this when you see a tool name with a namespace prefix (e.g. 'market__get_ohlcv')
    and need its full parameter documentation before calling it.

    Args:
        tool_name: The namespaced tool name, e.g. 'analysis__compute_rsi'.

    Returns:
        dict with 'tool_name', 'docstring', 'parameters' (list of {name, type, description}).
        Returns {'error': 'not_found'} if the tool name is not registered.
    """
    logger.info("describe_tool tool_name=%s", tool_name)
    # Import here to avoid circular dependency at module level
    from tools import registry as _reg  # type: ignore[import]

    all_tools = (
        _reg.MARKET_TOOLS
        + _reg.ANALYSIS_TOOLS
        + _reg.RESEARCH_TOOLS
        + _reg.MEMORY_TOOLS
        + _reg.COORDINATOR_TOOLS
        + _reg.STRATEGY_TOOLS
    )
    for ft in all_tools:
        if ft.name == tool_name or getattr(ft.func, "__name__", "") == tool_name:
            fn = ft.func
            import inspect
            sig = inspect.signature(fn)
            params = []
            for pname, param in sig.parameters.items():
                if pname in ("self", "tool_context"):
                    continue
                annotation = (
                    str(param.annotation)
                    if param.annotation is not inspect.Parameter.empty
                    else "any"
                )
                params.append({
                    "name": pname,
                    "type": annotation,
                    "default": (
                        str(param.default)
                        if param.default is not inspect.Parameter.empty
                        else None
                    ),
                })
            return {
                "tool_name": tool_name,
                "docstring": (inspect.getdoc(fn) or "").strip(),
                "parameters": params,
            }
    return {"error": "not_found", "tool_name": tool_name}

import json
from pathlib import Path
from typing import Any

from .models import AlphorynConfig


def load_config(
    config_path: str | Path = "config.json",
    overrides: dict[str, Any] | None = None,
) -> AlphorynConfig:
    """Load AlphorynConfig from a JSON file with optional CLI overrides.

    Resolution order:
    1. Load JSON from ``config_path`` (uses empty dict if file absent).
    2. Apply each entry in ``overrides`` where the value is not ``None``.
    3. Validate the merged dict into an ``AlphorynConfig``.

    Args:
        config_path: Path to JSON config file. Default: ``config.json``.
        overrides:   Dict of CLI option values; only non-``None`` values
                     are applied so that absent CLI flags don't overwrite
                     file values.

    Returns:
        Validated ``AlphorynConfig`` instance.

    Raises:
        pydantic.ValidationError: If the merged config fails field validation.
        json.JSONDecodeError: If the config file exists but is not valid JSON.
    """
    path = Path(config_path)
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    if overrides:
        for key, value in overrides.items():
            if value is not None:
                raw[key] = value

    return AlphorynConfig(**raw)

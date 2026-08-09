import json
from enum import Enum
from pathlib import Path
from typing import Any

from .models import AlphorynConfig


class _Sentinel(Enum):
    """Distinguishes "clear this field" from "the flag was absent" (``None``)."""

    CLEAR = "CLEAR"


CLEAR = _Sentinel.CLEAR


def load_config(
    config_path: str | Path = "config.json",
    overrides: dict[str, Any] | None = None,
) -> AlphorynConfig:
    """Load AlphorynConfig from a JSON file with optional CLI overrides.

    Resolution order:
    1. Load JSON from ``config_path`` (uses empty dict if file absent).
    2. Apply each entry in ``overrides`` where the value is not ``None``.
    3. Validate the merged dict into an ``AlphorynConfig``.

    ``None`` never overrides a file value: an absent CLI flag arrives as
    ``None`` and must leave the file alone. To *clear* a field the caller
    passes ``CLEAR``, which drops the key so the model default applies -
    this is how ``--budget 0`` removes a session money cap.

    Args:
        config_path: Path to JSON config file. Default: ``config.json``.
        overrides:   Dict of CLI option values; ``None`` values are ignored
                     and ``CLEAR`` values reset the field to its default.

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
            if value is CLEAR:
                raw.pop(key, None)
            elif value is not None:
                raw[key] = value

    return AlphorynConfig(**raw)

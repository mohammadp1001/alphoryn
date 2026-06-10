"""Unit tests for infra.secrets — get_secret, get_alpaca_credentials."""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── get_secret ────────────────────────────────────────────────────────────────

def test_get_secret_raises_if_no_project(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    with patch("infra.secrets.acquire_secret_manager", new=AsyncMock()):
        from infra.secrets import get_secret
        with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
            asyncio.run(get_secret("some-secret"))


def _mock_secret_manager_modules(mock_sm: MagicMock) -> dict:
    """Return sys.modules patches needed to mock google.cloud.secretmanager."""
    mock_gcloud = MagicMock()
    mock_gcloud.secretmanager = mock_sm
    return {
        "google.cloud": mock_gcloud,
        "google.cloud.secretmanager": mock_sm,
    }


def test_get_secret_success(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")

    mock_response = MagicMock()
    mock_response.payload.data = b"super-secret-value"

    mock_client = MagicMock()
    mock_client.access_secret_version.return_value = mock_response

    mock_sm = MagicMock()
    mock_sm.SecretManagerServiceClient.return_value = mock_client

    with patch.dict(sys.modules, _mock_secret_manager_modules(mock_sm)):
        with patch("infra.secrets.acquire_secret_manager", new=AsyncMock()):
            import importlib
            import infra.secrets as secrets_mod
            importlib.reload(secrets_mod)
            result = asyncio.run(secrets_mod.get_secret("alpaca-api-key"))

    assert result == "super-secret-value"
    mock_client.access_secret_version.assert_called_once()


def test_get_secret_uses_correct_resource_name(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")

    captured = {}

    mock_response = MagicMock()
    mock_response.payload.data = b"value"

    mock_client = MagicMock()

    def capture_call(request):
        captured["name"] = request["name"]
        return mock_response

    mock_client.access_secret_version.side_effect = capture_call

    mock_sm = MagicMock()
    mock_sm.SecretManagerServiceClient.return_value = mock_client

    with patch.dict(sys.modules, _mock_secret_manager_modules(mock_sm)):
        with patch("infra.secrets.acquire_secret_manager", new=AsyncMock()):
            import importlib
            import infra.secrets as secrets_mod
            importlib.reload(secrets_mod)
            asyncio.run(secrets_mod.get_secret("my-secret", version="3"))

    assert captured["name"] == "projects/my-project/secrets/my-secret/versions/3"


def test_get_secret_default_version_is_latest(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")

    captured = {}

    mock_response = MagicMock()
    mock_response.payload.data = b"v"

    mock_client = MagicMock()

    def capture_call(request):
        captured["name"] = request["name"]
        return mock_response

    mock_client.access_secret_version.side_effect = capture_call

    mock_sm = MagicMock()
    mock_sm.SecretManagerServiceClient.return_value = mock_client

    with patch.dict(sys.modules, _mock_secret_manager_modules(mock_sm)):
        with patch("infra.secrets.acquire_secret_manager", new=AsyncMock()):
            import importlib
            import infra.secrets as secrets_mod
            importlib.reload(secrets_mod)
            asyncio.run(secrets_mod.get_secret("my-secret"))

    assert captured["name"].endswith("/versions/latest")


# ── get_alpaca_credentials ────────────────────────────────────────────────────

def test_get_alpaca_credentials_calls_get_secret_twice():
    with patch("infra.secrets.get_secret", new=AsyncMock(side_effect=["key-123", "secret-456"])):
        from infra.secrets import get_alpaca_credentials
        key, secret = asyncio.run(get_alpaca_credentials())

    assert key == "key-123"
    assert secret == "secret-456"


def test_get_alpaca_credentials_returns_correct_order():
    """Key is returned first, secret second."""
    calls = []

    async def mock_get_secret(secret_id, version="latest"):
        calls.append(secret_id)
        return f"value-{secret_id}"

    with patch("infra.secrets.get_secret", new=mock_get_secret):
        from infra.secrets import get_alpaca_credentials
        key, secret = asyncio.run(get_alpaca_credentials())

    from config import ALPACA_API_KEY_SECRET, ALPACA_API_SECRET_SECRET
    assert calls[0] == ALPACA_API_KEY_SECRET
    assert calls[1] == ALPACA_API_SECRET_SECRET
    assert key == f"value-{ALPACA_API_KEY_SECRET}"
    assert secret == f"value-{ALPACA_API_SECRET_SECRET}"

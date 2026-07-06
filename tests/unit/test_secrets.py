import os
from unittest.mock import MagicMock, patch

import pytest

from alphoryn.secrets.client import (
    SecretsError,
    _fetch_and_inject,
    _make_client,
    load_alpaca_credentials,
)

# ---------------------------------------------------------------------------
# _make_client
# ---------------------------------------------------------------------------


def test_make_client_returns_secret_manager_client() -> None:
    mock_client = MagicMock()
    mock_sm = MagicMock()
    mock_sm.SecretManagerServiceClient.return_value = mock_client
    mock_google_cloud = MagicMock()
    mock_google_cloud.secretmanager = mock_sm

    with patch.dict(
        "sys.modules",
        {
            "google": MagicMock(),
            "google.cloud": mock_google_cloud,
            "google.cloud.secretmanager": mock_sm,
        },
    ):
        result = _make_client()

    assert result is mock_client
    mock_sm.SecretManagerServiceClient.assert_called_once()


def test_make_client_import_failure_raises_secrets_error() -> None:
    # Setting a key to None in sys.modules causes ImportError on import
    with patch.dict(
        "sys.modules",
        {"google": None, "google.cloud": None, "google.cloud.secretmanager": None},
    ):
        with pytest.raises(SecretsError, match="Cannot connect to GCP Secret Manager"):
            _make_client()


# ---------------------------------------------------------------------------
# _fetch_and_inject
# ---------------------------------------------------------------------------


def test_fetch_and_inject_sets_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_TEST_VAR", raising=False)
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.payload.data = b"my-secret-value"
    mock_client.access_secret_version.return_value = mock_response

    _fetch_and_inject(mock_client, "my-project", "my-secret", "MY_TEST_VAR")

    assert os.environ["MY_TEST_VAR"] == "my-secret-value"
    mock_client.access_secret_version.assert_called_once_with(
        request={"name": "projects/my-project/secrets/my-secret/versions/latest"}
    )


def test_fetch_and_inject_client_error_raises_secrets_error() -> None:
    mock_client = MagicMock()
    mock_client.access_secret_version.side_effect = RuntimeError("network error")

    with pytest.raises(SecretsError, match="Failed to fetch secret"):
        _fetch_and_inject(mock_client, "proj", "secret-name", "SOME_VAR")


def test_fetch_and_inject_decode_error_raises_secrets_error() -> None:
    mock_client = MagicMock()
    # payload.data is not bytes — triggers AttributeError during decode()
    mock_client.access_secret_version.return_value.payload.data = None

    with pytest.raises(SecretsError, match="Failed to fetch secret"):
        _fetch_and_inject(mock_client, "proj", "secret-name", "SOME_VAR")


# ---------------------------------------------------------------------------
# load_alpaca_credentials
# ---------------------------------------------------------------------------


def _mock_client_factory(
    api_key_value: str = "test-api-key",
    secret_key_value: str = "test-secret-val",  # noqa: S107
) -> MagicMock:
    """Build a mock Secret Manager client that returns preset secret values."""

    def side_effect(request):  # type: ignore[no-untyped-def]
        name: str = request["name"]
        mock_resp = MagicMock()
        if "alphoryn-alpaca-api-key" in name:
            mock_resp.payload.data = api_key_value.encode()
        elif "alphoryn-alpaca-secret-key" in name:
            mock_resp.payload.data = secret_key_value.encode()
        else:
            raise RuntimeError(f"unexpected secret: {name}")
        return mock_resp

    client = MagicMock()
    client.access_secret_version.side_effect = side_effect
    return client


def test_load_alpaca_credentials_injects_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")

    mock_client = _mock_client_factory()
    with patch("alphoryn.secrets.client._make_client", return_value=mock_client):
        load_alpaca_credentials()

    assert os.environ["ALPACA_API_KEY"] == "test-api-key"
    assert os.environ["ALPACA_SECRET_KEY"] == "test-secret-val"


def test_load_alpaca_credentials_explicit_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    mock_client = _mock_client_factory(api_key_value="key-x", secret_key_value="sec-y")
    with patch("alphoryn.secrets.client._make_client", return_value=mock_client):
        load_alpaca_credentials(project_id="explicit-project")

    assert os.environ["ALPACA_API_KEY"] == "key-x"
    assert os.environ["ALPACA_SECRET_KEY"] == "sec-y"


def test_load_alpaca_credentials_no_project_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    with pytest.raises(SecretsError, match="GCP project ID not set"):
        load_alpaca_credentials()


def test_load_alpaca_credentials_fetch_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")

    bad_client = MagicMock()
    bad_client.access_secret_version.side_effect = RuntimeError("timeout")

    with patch("alphoryn.secrets.client._make_client", return_value=bad_client):
        with pytest.raises(SecretsError, match="Failed to fetch secret"):
            load_alpaca_credentials()


def test_load_alpaca_credentials_make_client_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")

    with patch(
        "alphoryn.secrets.client._make_client",
        side_effect=SecretsError("client init failed"),
    ):
        with pytest.raises(SecretsError, match="client init failed"):
            load_alpaca_credentials()

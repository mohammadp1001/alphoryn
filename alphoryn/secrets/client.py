import logging
import os

_logger = logging.getLogger(__name__)

_SECRET_ENV_MAP: dict[str, str] = {
    "alpaca-api-key": "ALPACA_API_KEY",
    "alpaca-api-secret": "ALPACA_SECRET_KEY",
}


class SecretsError(Exception):
    """Raised when GCP Secret Manager is unreachable or a secret cannot be fetched."""


def load_alpaca_credentials(project_id: str | None = None) -> None:
    """Fetch Alpaca API credentials from GCP Secret Manager.

    Injects ``ALPACA_API_KEY`` and ``ALPACA_SECRET_KEY`` as environment
    variables so the Alpaca MCP server can read them at startup.

    Args:
        project_id: GCP project ID. Reads ``GOOGLE_CLOUD_PROJECT`` env var
                    when not provided.

    Raises:
        SecretsError: If the project ID cannot be determined, the Secret
                      Manager client cannot be created, or any secret fetch
                      fails.
    """
    resolved = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not resolved:
        _logger.error(
            "Cannot load Alpaca credentials: GCP project ID not set. "
            "Pass project_id= or set GOOGLE_CLOUD_PROJECT."
        )
        raise SecretsError(
            "GCP project ID not set. Pass project_id= or set GOOGLE_CLOUD_PROJECT."
        )

    client = _make_client()
    for secret_name, env_var in _SECRET_ENV_MAP.items():
        _fetch_and_inject(client, resolved, secret_name, env_var)


def _make_client() -> object:
    """Create a Secret Manager client.

    Raises:
        SecretsError: If the client cannot be instantiated (e.g. auth failure).
    """
    try:
        from google.cloud import secretmanager
        return secretmanager.SecretManagerServiceClient()
    except Exception as exc:
        _logger.exception("Failed to create Secret Manager client: %s", exc)
        raise SecretsError(f"Cannot connect to GCP Secret Manager: {exc}") from exc


def _fetch_and_inject(
    client: object, project_id: str, secret_name: str, env_var: str
) -> None:
    """Fetch one secret version and write it into ``os.environ``.

    Raises:
        SecretsError: If the secret cannot be fetched or decoded.
    """
    try:
        name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})  # type: ignore[union-attr]
        os.environ[env_var] = response.payload.data.decode("utf-8")
    except Exception as exc:
        _logger.exception("Failed to fetch secret %r into %s: %s", secret_name, env_var, exc)
        raise SecretsError(f"Failed to fetch secret {secret_name!r}: {exc}") from exc

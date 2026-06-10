"""
GCP Secret Manager wrapper.
The coordinator calls this at execution-agent spawn time to fetch the Alpaca execution key.
The value is injected as env vars into the execution agent context — never logged or stored.
"""
from __future__ import annotations

import logging
import os

from infra.rate_limiter import acquire_secret_manager
from infra.retry import with_retry

logger = logging.getLogger(__name__)


@with_retry
async def get_secret(secret_id: str, version: str = "latest") -> str:
    """Fetch a secret value from GCP Secret Manager."""
    await acquire_secret_manager()

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT env var not set")

    from google.cloud import secretmanager  # type: ignore[import]

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


async def get_alpaca_credentials() -> tuple[str, str]:
    """
    Returns (api_key, api_secret) for the Alpaca execution account.
    Called by coordinator harness at execution-agent spawn time only.
    Values must not be logged, stored on PlanState, or passed to other agents.
    """
    from config import ALPACA_API_KEY_SECRET, ALPACA_API_SECRET_SECRET

    api_key = await get_secret(ALPACA_API_KEY_SECRET)
    api_secret = await get_secret(ALPACA_API_SECRET_SECRET)
    return api_key, api_secret

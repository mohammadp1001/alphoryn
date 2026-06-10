"""forex.* tools — coordinator-visible read-only OANDA market data tools.

These tools give the coordinator access to forex account state and pricing so it
can decide whether a forex trade makes sense. Order placement is NOT in this
namespace — the execution BaseAgent handles that directly via _execute_oanda().

Credentials are read from env vars (OANDA_API_TOKEN, OANDA_ACCOUNT_ID) injected
at execution-agent spawn time. The coordinator never sees the token value.

OANDA instrument format: BASE_QUOTE (e.g. "EUR_USD", "GBP_JPY").
"""
from __future__ import annotations

import logging
import os

from infra.observability import api_call_span, get_logger
from infra.rate_limiter import acquire_oanda
from infra.retry import with_retry
from tools.schemas import (
    ForexAccountStatus,
    ForexInstrument,
    ForexInstrumentsResponse,
    ForexPosition,
    ForexPositionSide,
    ForexPositionsResponse,
    ForexPrice,
    ForexPricesResponse,
)

logger = get_logger("tools.forex")

# Major forex pairs available on OANDA practice accounts
_MAJOR_PAIRS: list[str] = [
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF",
    "AUD_USD", "USD_CAD", "NZD_USD", "EUR_GBP",
    "EUR_JPY", "GBP_JPY", "EUR_CHF", "AUD_JPY",
]


def _oanda_client() -> tuple[object, str]:
    """Return (API client, account_id). Reads env vars injected by coordinator harness."""
    import oandapyV20  # type: ignore[import]

    token = os.environ.get("OANDA_API_TOKEN", "")
    account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
    if not token or not account_id:
        raise RuntimeError("OANDA_API_TOKEN / OANDA_ACCOUNT_ID env vars not set")
    client = oandapyV20.API(access_token=token, environment="practice")
    return client, account_id


@with_retry
async def get_forex_account() -> dict:
    """Get OANDA practice account balance, NAV, margin, and open position count.

    Returns:
        dict with 'account_id', 'balance', 'nav', 'unrealized_pl', 'margin_used',
                  'margin_available', 'open_position_count', 'currency', 'is_practice'.
    """
    logger.info("get_forex_account")
    await acquire_oanda()
    with api_call_span("oanda", "get_account"):
        from oandapyV20.endpoints.accounts import AccountDetails  # type: ignore[import]
        client, account_id = _oanda_client()
        r = AccountDetails(account_id)
        client.request(r)
        acc = r.response["account"]

    return ForexAccountStatus(
        account_id=acc["id"],
        balance=float(acc.get("balance", 0)),
        nav=float(acc.get("NAV", 0)),
        unrealized_pl=float(acc.get("unrealizedPL", 0)),
        margin_used=float(acc.get("marginUsed", 0)),
        margin_available=float(acc.get("marginAvailable", 0)),
        open_position_count=int(acc.get("openPositionCount", 0)),
        currency=acc.get("currency", "USD"),
        is_practice=True,
    ).model_dump()


@with_retry
async def get_forex_positions() -> dict:
    """List all open OANDA forex positions with unrealized P&L.

    Returns:
        dict with 'positions' (list of position objects) and 'account_id'.
        Each position has 'instrument', 'net_units', 'unrealized_pl',
        and optional 'long'/'short' side details.
    """
    logger.info("get_forex_positions")
    await acquire_oanda()
    with api_call_span("oanda", "get_positions"):
        from oandapyV20.endpoints.positions import OpenPositions  # type: ignore[import]
        client, account_id = _oanda_client()
        r = OpenPositions(account_id)
        client.request(r)
        raw_positions = r.response.get("positions", [])

    positions: list[ForexPosition] = []
    for p in raw_positions:
        long_data = p.get("long", {})
        short_data = p.get("short", {})

        long_units = int(long_data.get("units", 0))
        short_units = int(short_data.get("units", 0))
        net_units = long_units + short_units

        long_side = (
            ForexPositionSide(
                units=long_units,
                avg_price=float(long_data.get("averagePrice", 0)),
                unrealized_pl=float(long_data.get("unrealizedPL", 0)),
            )
            if long_units != 0
            else None
        )
        short_side = (
            ForexPositionSide(
                units=short_units,
                avg_price=float(short_data.get("averagePrice", 0)),
                unrealized_pl=float(short_data.get("unrealizedPL", 0)),
            )
            if short_units != 0
            else None
        )

        positions.append(
            ForexPosition(
                instrument=p["instrument"],
                long=long_side,
                short=short_side,
                net_units=net_units,
                unrealized_pl=float(p.get("unrealizedPL", 0)),
            )
        )

    return ForexPositionsResponse(positions=positions, account_id=account_id).model_dump()


@with_retry
async def get_forex_prices(instruments: list[str] | None = None) -> dict:
    """Get current bid/ask/mid prices for OANDA forex instruments.

    Args:
        instruments: List of OANDA instrument names (e.g. ['EUR_USD', 'GBP_JPY']).
                     Defaults to all major pairs if omitted.

    Returns:
        dict with 'prices' — list of {instrument, bid, ask, mid, tradeable}.
    """
    pairs = instruments or _MAJOR_PAIRS
    pairs_str = ",".join(pairs)
    logger.info("get_forex_prices instruments=%s", pairs_str)
    await acquire_oanda()
    with api_call_span("oanda", "get_prices"):
        from oandapyV20.endpoints.pricing import PricingInfo  # type: ignore[import]
        client, account_id = _oanda_client()
        r = PricingInfo(account_id, params={"instruments": pairs_str})
        client.request(r)
        raw_prices = r.response.get("prices", [])

    prices: list[ForexPrice] = []
    for p in raw_prices:
        bids = p.get("bids", [])
        asks = p.get("asks", [])
        bid = float(bids[0]["price"]) if bids else None
        ask = float(asks[0]["price"]) if asks else None
        mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        prices.append(
            ForexPrice(
                instrument=p["instrument"],
                bid=bid,
                ask=ask,
                mid=mid,
                tradeable=p.get("tradeable", False),
            )
        )

    return ForexPricesResponse(prices=prices).model_dump()


@with_retry
async def get_forex_instruments() -> dict:
    """List tradeable forex instruments on the OANDA practice account with pip info.

    Returns:
        dict with 'instruments' — list of {name, display_name, pip_location, margin_rate}.
        Useful for discovering available pairs and their margin requirements.
    """
    logger.info("get_forex_instruments")
    await acquire_oanda()
    with api_call_span("oanda", "get_instruments"):
        from oandapyV20.endpoints.accounts import AccountInstruments  # type: ignore[import]
        client, account_id = _oanda_client()
        r = AccountInstruments(account_id, params={"type": "CURRENCY"})
        client.request(r)
        raw = r.response.get("instruments", [])

    instruments: list[ForexInstrument] = [
        ForexInstrument(
            name=i["name"],
            display_name=i.get("displayName", i["name"]),
            pip_location=int(i.get("pipLocation", -4)),
            margin_rate=float(i.get("marginRate", 0.02)),
        )
        for i in raw
    ]

    return ForexInstrumentsResponse(instruments=instruments).model_dump()

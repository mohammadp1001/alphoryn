"""
Alpaca outcome webhook — lightweight Cloud Run HTTP endpoint.

Alpaca sends a POST when an order fills, partially fills, or is cancelled.
We resolve the trade outcome in SQLite so the next session can skip polling
for that order.

Security model:
    Alpaca signs each webhook with HMAC-SHA256 (header: Alpaca-Signature).
    Set ALPACA_WEBHOOK_SECRET in Secret Manager and inject it as an env var
    at Cloud Run deploy time (same single-SA pattern as execution creds).

Deploy:
    gcloud run deploy alphoryn-webhook \
        --source webhook/ \
        --region us-central1 \
        --no-allow-unauthenticated \
        --set-env-vars ALPACA_WEBHOOK_SECRET=<secret>
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from http import HTTPStatus

from flask import Flask, Request, Response, request

from db.schema import get_unresolved_trades, resolve_outcome
from models.memory import DebateWinner

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

_WEBHOOK_SECRET: str | None = os.environ.get("ALPACA_WEBHOOK_SECRET")


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_signature(req: Request, secret: str) -> bool:
    """Return True if the Alpaca-Signature header matches the payload HMAC."""
    sig_header = req.headers.get("Alpaca-Signature", "")
    if not sig_header.startswith("v1="):
        return False
    provided = sig_header[3:]
    body = req.get_data()
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


# ---------------------------------------------------------------------------
# Pnl helpers
# ---------------------------------------------------------------------------

def _compute_pnl_pct(filled_avg_price: float, entry_price: float, side: str) -> float:
    if entry_price == 0:
        return 0.0
    raw = (filled_avg_price - entry_price) / entry_price
    return raw if side == "buy" else -raw


def _debate_winner(pnl_pct: float) -> DebateWinner:
    if pnl_pct < 0:
        return DebateWinner.PESSIMIST
    if pnl_pct >= 0.005:
        return DebateWinner.OPTIMIST
    return DebateWinner.TIE


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@app.route("/webhook/alpaca", methods=["POST"])
def alpaca_webhook() -> Response:
    if _WEBHOOK_SECRET and not _verify_signature(request, _WEBHOOK_SECRET):
        logger.warning("Webhook signature verification failed")
        return Response("Forbidden", status=HTTPStatus.FORBIDDEN)

    try:
        payload = request.get_json(force=True)
    except Exception:
        return Response("Bad Request: invalid JSON", status=HTTPStatus.BAD_REQUEST)

    if not isinstance(payload, dict):
        return Response("Bad Request: expected JSON object", status=HTTPStatus.BAD_REQUEST)

    event_type = payload.get("event")
    if event_type not in {"fill", "partial_fill", "canceled", "expired"}:
        # Not an event we act on; acknowledge and skip
        return Response(json.dumps({"ok": True, "action": "ignored"}), status=HTTPStatus.OK, mimetype="application/json")

    order = payload.get("order", {})
    order_id = order.get("id", "")
    filled_avg_price = float(order.get("filled_avg_price") or 0)
    side = order.get("side", "buy")

    if not order_id:
        return Response("Bad Request: missing order.id", status=HTTPStatus.BAD_REQUEST)

    unresolved = get_unresolved_trades()
    match = next((t for t in unresolved if t.order_id == order_id), None)

    if match is None:
        logger.info("Webhook: order_id=%s not in unresolved trades — skipping", order_id)
        return Response(json.dumps({"ok": True, "action": "not_found"}), status=HTTPStatus.OK, mimetype="application/json")

    if event_type in {"canceled", "expired"}:
        pnl_pct = 0.0
        winner = DebateWinner.TIE
        timed_out = True
    else:
        pnl_pct = _compute_pnl_pct(filled_avg_price, match.entry_price, side)
        winner = _debate_winner(pnl_pct)
        timed_out = False

    resolve_outcome(
        trade_id=match.id,
        actual_pnl_pct=pnl_pct,
        winner=winner,
        timed_out=timed_out,
    )

    logger.info(
        "Resolved trade %s order=%s event=%s pnl=%.4f winner=%s",
        match.id,
        order_id,
        event_type,
        pnl_pct,
        winner.value,
    )

    return Response(
        json.dumps({"ok": True, "trade_id": match.id, "winner": winner.value, "pnl_pct": pnl_pct}),
        status=HTTPStatus.OK,
        mimetype="application/json",
    )


@app.route("/healthz", methods=["GET"])
def healthz() -> Response:
    return Response(json.dumps({"status": "ok"}), status=HTTPStatus.OK, mimetype="application/json")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

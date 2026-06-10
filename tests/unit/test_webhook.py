"""Unit tests for the Alpaca outcome webhook."""
import hashlib
import hmac
import json
from datetime import datetime
from unittest.mock import patch

import pytest

from models.memory import DebateWinner, MarketRegime, Strategy, TradeRecord
from webhook.main import _compute_pnl_pct, _debate_winner, _verify_signature, app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(event: str, order_id: str = "ord-001", filled_avg_price: float = 210.0, side: str = "buy") -> dict:
    return {
        "event": event,
        "order": {
            "id": order_id,
            "side": side,
            "filled_avg_price": str(filled_avg_price),
        },
    }


def _sign(body: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"v1={sig}"


def _make_trade(order_id: str = "ord-001", entry_price: float = 200.0, side: str = "buy") -> TradeRecord:
    return TradeRecord(
        id="trade-001",
        session_id="sess-001",
        order_id=order_id,
        symbol="XLK",
        strategy=Strategy.MOMENTUM,
        market_regime=MarketRegime.BULL_TREND,
        side=side,
        qty=5.0,
        entry_price=entry_price,
        optimist_verdict="LOW",
        pessimist_verdict="LOW",
        risk_level="LOW",
        executed_at=datetime(2026, 6, 9, 10, 0, 0),
    )


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def test_verify_signature_valid():
    secret = "my-secret"
    body = b'{"event": "fill"}'

    class _FakeReq:
        def get_data(self):
            return body
        headers = {"Alpaca-Signature": _sign(body, secret)}

    req = _FakeReq()
    assert _verify_signature(req, secret) is True


def test_verify_signature_wrong_secret():
    body = b'{"event": "fill"}'

    class _FakeReq:
        def get_data(self):
            return body
        headers = {"Alpaca-Signature": _sign(body, "correct")}

    assert _verify_signature(_FakeReq(), "wrong") is False


def test_verify_signature_missing_header():
    class _FakeReq:
        def get_data(self):
            return b"{}"
        headers = {}

    assert _verify_signature(_FakeReq(), "secret") is False


# ---------------------------------------------------------------------------
# P&L helpers
# ---------------------------------------------------------------------------

def test_pnl_buy_profit():
    pnl = _compute_pnl_pct(filled_avg_price=210.0, entry_price=200.0, side="buy")
    assert abs(pnl - 0.05) < 1e-9


def test_pnl_buy_loss():
    pnl = _compute_pnl_pct(filled_avg_price=190.0, entry_price=200.0, side="buy")
    assert abs(pnl - (-0.05)) < 1e-9


def test_pnl_sell_profit():
    pnl = _compute_pnl_pct(filled_avg_price=190.0, entry_price=200.0, side="sell")
    assert abs(pnl - 0.05) < 1e-9


def test_pnl_zero_entry():
    assert _compute_pnl_pct(210.0, 0.0, "buy") == 0.0


def test_debate_winner_optimist():
    assert _debate_winner(0.006) == DebateWinner.OPTIMIST


def test_debate_winner_pessimist():
    assert _debate_winner(-0.01) == DebateWinner.PESSIMIST


def test_debate_winner_tie():
    assert _debate_winner(0.003) == DebateWinner.TIE


def test_debate_winner_exactly_at_threshold():
    assert _debate_winner(0.005) == DebateWinner.OPTIMIST


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_ignored_event(client):
    payload = {"event": "new", "order": {"id": "x"}}
    resp = client.post(
        "/webhook/alpaca",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["action"] == "ignored"


def test_fill_unknown_order(client):
    payload = _make_payload("fill", order_id="unknown-order")
    with patch("webhook.main.get_unresolved_trades", return_value=[]):
        resp = client.post(
            "/webhook/alpaca",
            data=json.dumps(payload),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json()["action"] == "not_found"


def test_fill_resolves_trade(client):
    trade = _make_trade(order_id="ord-fill", entry_price=200.0)
    payload = _make_payload("fill", order_id="ord-fill", filled_avg_price=201.0)

    with patch("webhook.main.get_unresolved_trades", return_value=[trade]), \
         patch("webhook.main.resolve_outcome") as mock_resolve:
        resp = client.post(
            "/webhook/alpaca",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["trade_id"] == "trade-001"
    assert body["winner"] == "optimist"
    mock_resolve.assert_called_once()
    _, _kwargs = mock_resolve.call_args[0], mock_resolve.call_args[1]
    call_kwargs = mock_resolve.call_args.kwargs
    assert call_kwargs["timed_out"] is False


def test_canceled_resolves_as_tie(client):
    trade = _make_trade(order_id="ord-cancel")
    payload = _make_payload("canceled", order_id="ord-cancel")

    with patch("webhook.main.get_unresolved_trades", return_value=[trade]), \
         patch("webhook.main.resolve_outcome") as mock_resolve:
        resp = client.post(
            "/webhook/alpaca",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert resp.status_code == 200
    call_kwargs = mock_resolve.call_args.kwargs
    assert call_kwargs["timed_out"] is True
    assert call_kwargs["winner"] == DebateWinner.TIE


def test_missing_order_id(client):
    payload = {"event": "fill", "order": {}}
    resp = client.post(
        "/webhook/alpaca",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_invalid_json(client):
    resp = client.post(
        "/webhook/alpaca",
        data="not-json",
        content_type="text/plain",
    )
    # Flask force=True parses or returns 400 from our handler
    assert resp.status_code in (200, 400)


def test_signature_failure_returns_403(client):
    """Line 83-84: when _WEBHOOK_SECRET is set and signature is wrong, return 403."""
    import webhook.main as wm
    payload = json.dumps({"event": "fill", "order": {"id": "x"}}).encode()
    with patch.object(wm, "_WEBHOOK_SECRET", "real-secret"):
        # Send with no Alpaca-Signature header — verification fails
        resp = client.post(
            "/webhook/alpaca",
            data=payload,
            content_type="application/json",
        )
    assert resp.status_code == 403


def test_non_dict_payload_returns_400(client):
    """Line 92: when JSON body is a list rather than an object, return 400."""
    resp = client.post(
        "/webhook/alpaca",
        data=json.dumps([{"event": "fill"}]),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_main_entrypoint_calls_app_run(monkeypatch):
    """Lines 152-153: __main__ block starts the Flask app on the correct port."""
    import runpy

    monkeypatch.setenv("PORT", "9999")
    # Patch Flask.run at the class level so it intercepts the newly created app instance
    with patch("flask.Flask.run") as mock_run:
        runpy.run_module("webhook.main", run_name="__main__", alter_sys=False)

    mock_run.assert_called_once_with(host="0.0.0.0", port=9999)

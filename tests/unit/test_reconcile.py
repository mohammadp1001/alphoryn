"""Unit tests for alphoryn/reconcile/positions.py.

Startup reconciliation between what Alpaca holds and what the memory bank
believes. Every Alpaca call is stubbed.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from alphoryn.memory.schema import Position
from alphoryn.reconcile.positions import (
    ORPHAN,
    PHANTOM,
    QUANTITY_DRIFT,
    Discrepancy,
    ReconcileError,
    check_positions,
    fetch_broker_quantities,
    find_discrepancies,
    resolve,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_position(
    *, pos_id: int = 1, ticker: str = "SPY", lot_size: float = 1.0
) -> Position:
    pos = Position()
    pos.id = pos_id
    pos.ticker = ticker
    pos.lot_size = lot_size
    pos.status = "OPEN"
    pos.session_id = "run-1/session-0001"
    pos.entry_price = 100.0
    pos.entry_time = datetime.now(UTC) - timedelta(hours=1)
    pos.evaluation_window_close_at = datetime.now(UTC).replace(tzinfo=None)
    return pos


def _broker_position(symbol: str, qty: str) -> MagicMock:
    p = MagicMock()
    p.symbol = symbol
    p.qty = qty  # Alpaca returns qty as a string
    return p


def _seed_closed_position(bank: object, *, status: str) -> None:
    """Write one run + session + already-closed SPY position into a real bank."""
    from alphoryn.memory.schema import Session as SessionModel

    run_id = bank.start_run('{"tickers": ["SPY"]}', 1)  # type: ignore[attr-defined]
    session = SessionModel()
    session.id = "run-1/session-0001"
    session.run_id = run_id
    session.candle_close_at = datetime.now(UTC) - timedelta(hours=2)
    session.created_at = datetime.now(UTC) - timedelta(hours=2)
    session.status = "COMPLETED"
    bank.write_session(session)  # type: ignore[attr-defined]

    pos = _make_position()
    pos.id = None
    pos.strategy = "MOMENTUM"
    pos.direction = "BUY"
    pos.stop_loss_price = 90.0
    pos.exit_target = '{"type": "price_level", "value": 120.0}'
    pos.evaluation_window_close_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        hours=1
    )
    pos.status = status
    pos.exit_price = 101.0
    pos.exit_time = datetime.now(UTC) - timedelta(hours=1)
    pos.exit_reason = "RECONCILED" if status == "CLOSED_RECONCILED" else "WINDOW_EXPIRY"
    bank.write_position(pos)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# find_discrepancies - pure comparison, no I/O
# ---------------------------------------------------------------------------


def test_matching_state_reports_nothing() -> None:
    positions = [_make_position(ticker="SPY", lot_size=1.0)]
    assert find_discrepancies(positions, {"SPY": 1.0}) == []


def test_both_sides_empty_reports_nothing() -> None:
    assert find_discrepancies([], {}) == []


def test_broker_holds_what_the_bank_does_not_know_is_an_orphan() -> None:
    """The live case: reset wiped local rows, Alpaca kept 113 shares of QQQ."""
    found = find_discrepancies([], {"QQQ": 113.0})
    assert len(found) == 1
    assert found[0].kind == ORPHAN
    assert found[0].ticker == "QQQ"
    assert found[0].broker_qty == 113.0
    assert found[0].bank_qty is None


def test_bank_open_row_the_broker_does_not_hold_is_a_phantom() -> None:
    positions = [_make_position(pos_id=7, ticker="SPY", lot_size=2.0)]
    found = find_discrepancies(positions, {})
    assert len(found) == 1
    assert found[0].kind == PHANTOM
    assert found[0].bank_qty == 2.0
    assert found[0].broker_qty is None
    assert found[0].bank_position_ids == (7,)


def test_differing_quantities_are_drift() -> None:
    positions = [_make_position(ticker="SPY", lot_size=1.0)]
    found = find_discrepancies(positions, {"SPY": 5.0})
    assert len(found) == 1
    assert found[0].kind == QUANTITY_DRIFT
    assert found[0].bank_qty == 1.0
    assert found[0].broker_qty == 5.0


def test_fractional_quantities_within_tolerance_are_not_drift() -> None:
    positions = [_make_position(ticker="SPY", lot_size=0.1 + 0.2)]
    assert find_discrepancies(positions, {"SPY": 0.3}) == []


def test_multiple_bank_rows_for_one_ticker_are_summed() -> None:
    positions = [
        _make_position(pos_id=1, ticker="SPY", lot_size=1.0),
        _make_position(pos_id=2, ticker="SPY", lot_size=2.0),
    ]
    assert find_discrepancies(positions, {"SPY": 3.0}) == []


def test_multiple_bank_rows_carry_every_id() -> None:
    positions = [
        _make_position(pos_id=1, ticker="SPY", lot_size=1.0),
        _make_position(pos_id=2, ticker="SPY", lot_size=2.0),
    ]
    found = find_discrepancies(positions, {})
    assert found[0].bank_position_ids == (1, 2)


def test_discrepancies_are_sorted_by_ticker() -> None:
    found = find_discrepancies([], {"QQQ": 1.0, "AAPL": 2.0, "SPY": 3.0})
    assert [d.ticker for d in found] == ["AAPL", "QQQ", "SPY"]


def test_orphan_and_phantom_can_be_reported_together() -> None:
    positions = [_make_position(ticker="SPY", lot_size=1.0)]
    found = find_discrepancies(positions, {"QQQ": 113.0})
    assert {d.kind for d in found} == {ORPHAN, PHANTOM}


# ---------------------------------------------------------------------------
# Discrepancy.describe - what the operator actually reads
# ---------------------------------------------------------------------------


def test_orphan_description_names_both_sides() -> None:
    text = Discrepancy("QQQ", ORPHAN, None, 113.0, ()).describe()
    assert "QQQ" in text
    assert "113" in text


def test_phantom_description_names_both_sides() -> None:
    text = Discrepancy("SPY", PHANTOM, 2.0, None, (7,)).describe()
    assert "SPY" in text
    assert "2" in text


def test_drift_description_names_both_quantities() -> None:
    text = Discrepancy("SPY", QUANTITY_DRIFT, 1.0, 5.0, (1,)).describe()
    assert "1" in text
    assert "5" in text


# ---------------------------------------------------------------------------
# fetch_broker_quantities
# ---------------------------------------------------------------------------


def test_fetch_broker_quantities_parses_string_quantities() -> None:
    client = MagicMock()
    client.get_all_positions.return_value = [
        _broker_position("SPY", "1"),
        _broker_position("QQQ", "113"),
    ]
    assert fetch_broker_quantities(client) == {"SPY": 1.0, "QQQ": 113.0}


def test_fetch_broker_quantities_wraps_api_failure() -> None:
    client = MagicMock()
    client.get_all_positions.side_effect = RuntimeError("connection refused")
    with pytest.raises(ReconcileError, match="connection refused"):
        fetch_broker_quantities(client)


# ---------------------------------------------------------------------------
# check_positions - the startup entry point
# ---------------------------------------------------------------------------


def test_check_positions_returns_discrepancies() -> None:
    bank = MagicMock()
    bank.load_open_positions.return_value = []
    client = MagicMock()
    client.get_all_positions.return_value = [_broker_position("QQQ", "113")]

    found = check_positions(bank, trading_client=client)

    assert [d.kind for d in found] == [ORPHAN]


def test_check_positions_emits_one_mismatch_event_per_discrepancy() -> None:
    bank = MagicMock()
    bank.load_open_positions.return_value = [_make_position(ticker="SPY")]
    client = MagicMock()
    client.get_all_positions.return_value = [_broker_position("QQQ", "113")]
    logger = MagicMock()

    check_positions(bank, trading_client=client, logger=logger)

    emitted = [c.args[0] for c in logger.emit.call_args_list]
    assert emitted == ["RECONCILE_MISMATCH", "RECONCILE_MISMATCH"]


def test_check_positions_emits_nothing_when_state_agrees() -> None:
    bank = MagicMock()
    bank.load_open_positions.return_value = []
    client = MagicMock()
    client.get_all_positions.return_value = []
    logger = MagicMock()

    assert check_positions(bank, trading_client=client, logger=logger) == []
    logger.emit.assert_not_called()


def test_check_positions_works_without_a_logger() -> None:
    bank = MagicMock()
    bank.load_open_positions.return_value = []
    client = MagicMock()
    client.get_all_positions.return_value = [_broker_position("QQQ", "113")]

    assert len(check_positions(bank, trading_client=client)) == 1


# ---------------------------------------------------------------------------
# resolve - only ever reached via --reconcile
# ---------------------------------------------------------------------------


def test_resolve_closes_an_orphan_at_the_broker() -> None:
    client = MagicMock()
    resolve([Discrepancy("QQQ", ORPHAN, None, 113.0, ())], bank=MagicMock(), trading_client=client)
    client.close_position.assert_called_once_with("QQQ")


def test_resolve_does_not_touch_the_bank_for_an_orphan() -> None:
    """There is no row to close - that is what makes it an orphan."""
    bank = MagicMock()
    resolve([Discrepancy("QQQ", ORPHAN, None, 113.0, ())], bank=bank, trading_client=MagicMock())
    bank.mark_position_reconciled.assert_not_called()


def test_resolve_marks_a_phantom_closed_in_the_bank() -> None:
    bank = MagicMock()
    resolve([Discrepancy("SPY", PHANTOM, 2.0, None, (7,))], bank=bank, trading_client=MagicMock())
    bank.mark_position_reconciled.assert_called_once()
    assert bank.mark_position_reconciled.call_args.args[0] == 7


def test_resolve_does_not_call_the_broker_for_a_phantom() -> None:
    """The broker does not hold it; asking it to close would just error."""
    client = MagicMock()
    resolve([Discrepancy("SPY", PHANTOM, 2.0, None, (7,))], bank=MagicMock(), trading_client=client)
    client.close_position.assert_not_called()


def test_resolve_closes_every_bank_row_of_a_phantom() -> None:
    bank = MagicMock()
    resolve(
        [Discrepancy("SPY", PHANTOM, 3.0, None, (1, 2))],
        bank=bank,
        trading_client=MagicMock(),
    )
    assert bank.mark_position_reconciled.call_count == 2


def test_resolve_flattens_drift_on_both_sides() -> None:
    bank = MagicMock()
    client = MagicMock()
    resolve(
        [Discrepancy("SPY", QUANTITY_DRIFT, 1.0, 5.0, (3,))],
        bank=bank,
        trading_client=client,
    )
    client.close_position.assert_called_once_with("SPY")
    bank.mark_position_reconciled.assert_called_once()


def test_resolve_leaves_the_exit_price_unknown_rather_than_inventing_one() -> None:
    """0.0 would read as a total loss; the entry price as a flat trade."""
    bank = MagicMock()
    resolve(
        [Discrepancy("SPY", PHANTOM, 2.0, None, (7,))],
        bank=bank,
        trading_client=MagicMock(),
    )
    assert "exit_price" not in bank.mark_position_reconciled.call_args.kwargs


def test_resolve_emits_a_resolved_event_per_discrepancy() -> None:
    logger = MagicMock()
    resolve(
        [Discrepancy("QQQ", ORPHAN, None, 113.0, ())],
        bank=MagicMock(),
        trading_client=MagicMock(),
        logger=logger,
    )
    assert [c.args[0] for c in logger.emit.call_args_list] == ["RECONCILE_RESOLVED"]


def test_resolve_reports_a_broker_failure_without_raising() -> None:
    """One ticker failing must not abandon the rest."""
    client = MagicMock()
    client.close_position.side_effect = RuntimeError("market closed")
    logger = MagicMock()

    messages = resolve(
        [Discrepancy("QQQ", ORPHAN, None, 113.0, ())],
        bank=MagicMock(),
        trading_client=client,
        logger=logger,
    )

    assert any("market closed" in m for m in messages)
    assert [c.args[0] for c in logger.emit.call_args_list] == ["RECONCILE_FAILED"]


def test_resolve_continues_past_a_failing_ticker() -> None:
    bank = MagicMock()
    client = MagicMock()
    client.close_position.side_effect = [RuntimeError("nope"), None]

    resolve(
        [
            Discrepancy("AAA", ORPHAN, None, 1.0, ()),
            Discrepancy("BBB", ORPHAN, None, 2.0, ()),
        ],
        bank=bank,
        trading_client=client,
    )

    assert client.close_position.call_count == 2


def test_resolve_leaves_the_bank_alone_when_the_broker_close_fails() -> None:
    """Never record a close the broker refused - that is the drift we are fixing."""
    bank = MagicMock()
    client = MagicMock()
    client.close_position.side_effect = RuntimeError("market closed")

    resolve(
        [Discrepancy("SPY", QUANTITY_DRIFT, 1.0, 5.0, (3,))],
        bank=bank,
        trading_client=client,
    )

    bank.mark_position_reconciled.assert_not_called()


def test_resolve_returns_a_message_per_discrepancy() -> None:
    messages = resolve(
        [
            Discrepancy("QQQ", ORPHAN, None, 113.0, ()),
            Discrepancy("SPY", PHANTOM, 1.0, None, (1,)),
        ],
        bank=MagicMock(),
        trading_client=MagicMock(),
    )
    assert len(messages) == 2


def test_resolve_on_empty_input_does_nothing() -> None:
    bank, client = MagicMock(), MagicMock()
    assert resolve([], bank=bank, trading_client=client) == []
    client.close_position.assert_not_called()
    bank.mark_position_reconciled.assert_not_called()


# ---------------------------------------------------------------------------
# A reconciled position must not distort feedback or ticker gating
# ---------------------------------------------------------------------------


def test_reconciled_position_neither_blocks_its_ticker_nor_awaits_feedback(
    tmp_path: object,
) -> None:
    """CLOSED_RECONCILED must free the ticker and never reach the feedback agent.

    Nobody can judge a thesis whose outcome was never observed: the broker
    state that would have decided it is exactly what went missing.
    """
    from alphoryn.memory.bank import MemoryBank

    bank = MemoryBank(str(tmp_path / "m.db"))  # type: ignore[operator]
    _seed_closed_position(bank, status="CLOSED_RECONCILED")

    assert bank.get_feedback_blocked_tickers() == set()
    assert bank.get_positions_due_for_feedback(datetime.now(UTC)) == []


def test_mark_position_reconciled_writes_status_reason_and_a_null_exit_price(
    tmp_path: object,
) -> None:
    from alphoryn.memory.bank import MemoryBank

    bank = MemoryBank(str(tmp_path / "m.db"))  # type: ignore[operator]
    _seed_closed_position(bank, status="OPEN")
    [position] = bank.load_open_positions()

    at = datetime.now(UTC)
    bank.mark_position_reconciled(position.id, at)

    assert bank.load_open_positions() == []
    reconciled = bank.get_positions_due_for_feedback(datetime.now(UTC))
    assert reconciled == []  # excluded from feedback by status
    assert bank.get_feedback_blocked_tickers() == set()


def test_a_normally_closed_position_still_blocks_and_awaits_feedback(
    tmp_path: object,
) -> None:
    """Control for the test above - proves it is the status doing the work."""
    from alphoryn.memory.bank import MemoryBank

    bank = MemoryBank(str(tmp_path / "m.db"))  # type: ignore[operator]
    _seed_closed_position(bank, status="CLOSED_WINDOW_EXPIRY")

    assert bank.get_feedback_blocked_tickers() == {"SPY"}
    assert len(bank.get_positions_due_for_feedback(datetime.now(UTC))) == 1

"""Startup reconciliation between Alpaca's positions and the memory bank.

The two can drift apart, and nothing used to notice. Recreating the memory
bank (`alphoryn reset --force`, the only way to apply a schema change) wipes
local rows while the broker keeps holding the shares; a crash between placing
an order and writing the row leaves the mirror image. Neither side is
self-correcting: the monitor only ever looks at rows in the bank, so anything
the bank has forgotten has no stop-loss, no window and no owner, and FR-019
cannot gate a ticker it has no record of - the next run will happily open a
second position on top of the first.

This module only ever compares and reports. `alphoryn run` prints what it
finds and carries on; nothing here is destructive unless `--reconcile` is
passed, which routes through `resolve`.

Constitution Principle I: mechanical comparison, zero LLM calls.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import Position
from alphoryn.telemetry.logger import TelemetryLogger

model = None  # Principle I: no LLM calls

ORPHAN = "ORPHAN"
"""The broker holds it; the bank has no OPEN row. Unmonitored exposure."""

PHANTOM = "PHANTOM"
"""The bank holds an OPEN row; the broker holds nothing. Unclosable."""

QUANTITY_DRIFT = "QUANTITY_DRIFT"
"""Both sides hold it, in different sizes."""

# Lot sizes are floats and Alpaca supports fractional shares, so quantities are
# compared with a tolerance rather than for equality.
_QTY_TOLERANCE = 1e-6


class ReconcileError(Exception):
    """Raised when the broker's position list cannot be fetched."""


@dataclass(frozen=True)
class Discrepancy:
    """One ticker on which the broker and the bank disagree."""

    ticker: str
    kind: str
    bank_qty: float | None
    broker_qty: float | None
    bank_position_ids: tuple[int, ...] = field(default=())

    def describe(self) -> str:
        """One line an operator can act on."""
        if self.kind == ORPHAN:
            return (
                f"{self.ticker}: Alpaca holds {self.broker_qty:g}, the memory bank has "
                f"no open position. It is unmonitored - no stop-loss, no exit window."
            )
        if self.kind == PHANTOM:
            return (
                f"{self.ticker}: the memory bank has an open position of "
                f"{self.bank_qty:g}, Alpaca holds nothing. The monitor cannot ever "
                f"close it."
            )
        return (
            f"{self.ticker}: the memory bank has {self.bank_qty:g}, Alpaca holds "
            f"{self.broker_qty:g}."
        )


def fetch_broker_quantities(trading_client: object) -> dict[str, float]:
    """Return ``{ticker: quantity}`` for every position the broker holds.

    Raises:
        ReconcileError: if the broker cannot be reached.
    """
    try:
        broker_positions = trading_client.get_all_positions()  # type: ignore[attr-defined]
    except Exception as exc:
        raise ReconcileError(f"Cannot list Alpaca positions: {exc}") from exc
    return {p.symbol: float(p.qty) for p in broker_positions}


def find_discrepancies(
    open_positions: Sequence[Position],
    broker_quantities: Mapping[str, float],
) -> list[Discrepancy]:
    """Compare bank rows against broker holdings. Pure - no I/O."""
    bank_qty: dict[str, float] = {}
    bank_ids: dict[str, list[int]] = {}
    for pos in open_positions:
        bank_qty[pos.ticker] = bank_qty.get(pos.ticker, 0.0) + float(pos.lot_size)
        bank_ids.setdefault(pos.ticker, []).append(pos.id)

    found: list[Discrepancy] = []
    for ticker in sorted(set(bank_qty) | set(broker_quantities)):
        held = broker_quantities.get(ticker)
        recorded = bank_qty.get(ticker)
        ids = tuple(bank_ids.get(ticker, ()))

        if recorded is None:
            found.append(Discrepancy(ticker, ORPHAN, None, held, ids))
        elif held is None:
            found.append(Discrepancy(ticker, PHANTOM, recorded, None, ids))
        elif not math.isclose(recorded, held, abs_tol=_QTY_TOLERANCE):
            found.append(Discrepancy(ticker, QUANTITY_DRIFT, recorded, held, ids))
    return found


def check_positions(
    bank: MemoryBank,
    *,
    trading_client: object,
    logger: TelemetryLogger | None = None,
) -> list[Discrepancy]:
    """Compare broker and bank at startup, emitting one event per disagreement.

    Raises:
        ReconcileError: if the broker cannot be reached. The caller decides
            what that means for the run.
    """
    broker_quantities = fetch_broker_quantities(trading_client)
    found = find_discrepancies(bank.load_open_positions(), broker_quantities)
    if logger is not None:
        for d in found:
            logger.emit(
                "RECONCILE_MISMATCH",
                "reconcile",
                {
                    "ticker": d.ticker,
                    "kind": d.kind,
                    "bank_qty": d.bank_qty,
                    "broker_qty": d.broker_qty,
                    "detail": d.describe(),
                },
                etf=d.ticker,
            )
    return found


def resolve(
    discrepancies: Iterable[Discrepancy],
    *,
    bank: MemoryBank,
    trading_client: object,
    logger: TelemetryLogger | None = None,
) -> list[str]:
    """Flatten every disagreement so both sides agree that nothing is held.

    Orphans are closed at the broker; phantoms are marked ``CLOSED_RECONCILED``
    in the bank; drift is closed on both sides. One ticker failing does not
    abandon the rest - each is reported and the loop continues.

    A ticker is only ever written to the bank *after* the broker has confirmed
    its close. Recording a close the broker refused would manufacture exactly
    the drift this module exists to catch.

    ``CLOSED_RECONCILED`` is deliberately outside both the feedback-blocking
    and feedback-due status sets: the ticker is freed, and the feedback agent
    never sees the position. Its outcome was never observed, so there is no
    honest judgment to make about the thesis.

    Returns:
        One human-readable line per discrepancy, in input order.
    """
    messages: list[str] = []
    for d in discrepancies:
        try:
            if d.kind in (ORPHAN, QUANTITY_DRIFT):
                trading_client.close_position(d.ticker)  # type: ignore[attr-defined]
            if d.kind in (PHANTOM, QUANTITY_DRIFT):
                for position_id in d.bank_position_ids:
                    bank.mark_position_reconciled(position_id, datetime.now(UTC))
        except Exception as exc:
            message = f"{d.ticker}: could not reconcile - {exc}"
            messages.append(message)
            if logger is not None:
                logger.emit(
                    "RECONCILE_FAILED",
                    "reconcile",
                    {"ticker": d.ticker, "kind": d.kind, "error": str(exc)},
                    etf=d.ticker,
                )
            continue

        message = f"{d.ticker}: reconciled ({d.kind})"
        messages.append(message)
        if logger is not None:
            logger.emit(
                "RECONCILE_RESOLVED",
                "reconcile",
                {"ticker": d.ticker, "kind": d.kind},
                etf=d.ticker,
            )
    return messages

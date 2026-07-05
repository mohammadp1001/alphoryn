from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession

from .schema import (
    FeedbackEvaluation,
    MemoryEntry,
    Position,
    Run,
    Session,
    create_tables,
    get_engine,
)


class MemoryBankError(Exception):
    """Raised when the SQLite memory bank is inaccessible or corrupt.

    Per spec FR-019: the system MUST abort with a clear error when this
    occurs — the run must not proceed in a degraded state.
    """


class MemoryBank:
    """Interface to the SQLite memory bank.

    All reads and writes go through this class. No caller should interact
    with SQLAlchemy sessions directly.
    """

    def __init__(self, db_path: str) -> None:
        """Open the memory bank and create tables if they do not exist.

        Raises:
            MemoryBankError: If the database cannot be opened or tables
                             cannot be created (inaccessible / corrupt).
        """
        try:
            self._engine = get_engine(db_path)
            create_tables(self._engine)
            # Verify connectivity with a lightweight read
            with DBSession(self._engine) as s:
                s.query(Run).limit(1).all()
        except Exception as exc:
            raise MemoryBankError(f"Memory bank inaccessible at {db_path!r}: {exc}") from exc

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def load_open_positions(self) -> list[Position]:
        """Return all OPEN positions across all runs, ordered by entry_time.

        Used at startup to apply carry-over position-blocking rules (FR-019).
        """
        with DBSession(self._engine) as s:
            return (
                s.query(Position)
                .filter(Position.status == "OPEN")
                .order_by(Position.entry_time.asc())
                .all()
            )

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def start_run(self, config_snapshot: str, session_count_planned: int) -> int:
        """Create a Run record and return its ID."""
        with DBSession(self._engine) as s:
            run = Run(
                started_at=datetime.now(timezone.utc),
                config_snapshot=config_snapshot,
                session_count_planned=session_count_planned,
            )
            s.add(run)
            s.commit()
            s.refresh(run)
            return run.id  # type: ignore[return-value]

    def end_run(self, run_id: int) -> None:
        """Mark a Run as ended."""
        with DBSession(self._engine) as s:
            run = s.query(Run).filter(Run.id == run_id).one()
            run.ended_at = datetime.now(timezone.utc)
            s.commit()

    # ------------------------------------------------------------------
    # Session writes
    # ------------------------------------------------------------------

    def write_session(self, session: Session) -> None:
        """Persist a Session record (merge to handle re-writes)."""
        with DBSession(self._engine) as s:
            s.merge(session)
            s.commit()

    # ------------------------------------------------------------------
    # Position writes
    # ------------------------------------------------------------------

    def write_position(self, position: Position) -> int:
        """Persist a new Position and return its assigned ID."""
        with DBSession(self._engine) as s:
            s.add(position)
            s.commit()
            s.refresh(position)
            return position.id  # type: ignore[return-value]

    def update_position_close(
        self,
        position_id: int,
        *,
        exit_price: float,
        exit_time: datetime,
        exit_reason: str,
        status: str,
        trailing_stop_high_watermark: float | None = None,
    ) -> None:
        """Write exit fields when the monitor closes a position."""
        with DBSession(self._engine) as s:
            pos = s.query(Position).filter(Position.id == position_id).one()
            pos.exit_price = exit_price
            pos.exit_time = exit_time
            pos.exit_reason = exit_reason
            pos.status = status
            if trailing_stop_high_watermark is not None:
                pos.trailing_stop_high_watermark = trailing_stop_high_watermark
            s.commit()

    def update_trailing_watermark(self, position_id: int, watermark: float) -> None:
        """Update the trailing stop high-watermark for a Momentum position."""
        with DBSession(self._engine) as s:
            pos = s.query(Position).filter(Position.id == position_id).one()
            pos.trailing_stop_high_watermark = watermark
            s.commit()

    # ------------------------------------------------------------------
    # Feedback evaluation writes
    # ------------------------------------------------------------------

    def write_feedback_evaluation(
        self, evaluation: FeedbackEvaluation, position_status: str
    ) -> None:
        """Persist a FeedbackEvaluation and update the parent Position status."""
        with DBSession(self._engine) as s:
            s.add(evaluation)
            pos = s.query(Position).filter(Position.id == evaluation.position_id).one()
            pos.status = position_status
            s.commit()

    # ------------------------------------------------------------------
    # Memory entry writes
    # ------------------------------------------------------------------

    def write_memory_entry(self, entry: MemoryEntry) -> None:
        """Persist a MemoryEntry record."""
        with DBSession(self._engine) as s:
            s.add(entry)
            s.commit()

    def update_memory_entry_judgment(
        self, session_id: str, etf: str, strategy: str, outcome_judgment: str
    ) -> None:
        """Set outcome_judgment on the MemoryEntry for a given session/ETF/strategy."""
        with DBSession(self._engine) as s:
            entry = (
                s.query(MemoryEntry)
                .filter(
                    MemoryEntry.session_id == session_id,
                    MemoryEntry.etf == etf,
                    MemoryEntry.strategy == strategy,
                )
                .one()
            )
            entry.outcome_judgment = outcome_judgment
            s.commit()

    # ------------------------------------------------------------------
    # Queries for scheduler / feedback trigger
    # ------------------------------------------------------------------

    def get_positions_due_for_feedback(self, current_session_ordinal: int) -> list[Position]:
        """Return closed positions whose evaluation window has arrived."""
        closed_statuses = (
            "CLOSED_STOP_LOSS",
            "CLOSED_PROFIT_TARGET",
            "CLOSED_WINDOW_EXPIRY",
        )
        with DBSession(self._engine) as s:
            candidates = (
                s.query(Position)
                .filter(
                    Position.status.in_(closed_statuses),
                    Position.evaluation_window_session == current_session_ordinal,
                )
                .all()
            )
            return [p for p in candidates if p.feedback_evaluation is None]

    def get_recent_memory_entries(self, etf: str, limit: int = 5) -> list[MemoryEntry]:
        """Return the most recent MemoryEntry records for a given ETF."""
        with DBSession(self._engine) as s:
            return (
                s.query(MemoryEntry)
                .filter(MemoryEntry.etf == etf)
                .order_by(MemoryEntry.created_at.desc())
                .limit(limit)
                .all()
            )

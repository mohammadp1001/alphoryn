from pathlib import Path

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One record per ``alphoryn run`` invocation."""

    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    config_snapshot = Column(Text, nullable=False)  # JSON dump of non-secret fields
    session_count_planned = Column(Integer, nullable=False)

    sessions = relationship("Session", back_populates="run")


class Session(Base):
    """One record per candle close processed. ID: ``run-{N}/session-{seq}``."""

    __tablename__ = "sessions"

    id = Column(String, primary_key=True)  # composite: "run-1/session-a3f7"
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)
    candle_close_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False)
    status = Column(String, nullable=False)
    # Valid statuses: COMPLETED | SKIPPED_TIMEOUT | SKIPPED_MARKET_CLOSED | SKIPPED_DATA_UNAVAILABLE
    html_report_path = Column(String, nullable=True)
    etf1_strategy = Column(String, nullable=True)   # MEAN_REVERSION | MOMENTUM
    etf2_strategy = Column(String, nullable=True)
    etf1_decision = Column(String, nullable=True)   # BUY | SELL | HOLD
    etf2_decision = Column(String, nullable=True)
    etf1_execution_result = Column(String, nullable=True)
    # Valid results: EXECUTED | SKIPPED_BUDGET | SKIPPED_MARKET_CLOSED | SKIPPED_API_ERROR
    etf2_execution_result = Column(String, nullable=True)
    warnings = Column(Text, nullable=True)  # JSON list of warning strings

    run = relationship("Run", back_populates="sessions")
    positions = relationship("Position", back_populates="session")
    memory_entries = relationship("MemoryEntry", back_populates="session")


class Position(Base):
    """One open paper trade on one ETF. Two ETFs are fully independent."""

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    etf = Column(String, nullable=False)
    strategy = Column(String, nullable=False)   # MEAN_REVERSION | MOMENTUM
    direction = Column(String, nullable=False, default="BUY")
    entry_price = Column(Float, nullable=False)
    entry_time = Column(DateTime, nullable=False)
    lot_size = Column(Float, nullable=False)
    stop_loss_price = Column(Float, nullable=False)
    exit_target = Column(Text, nullable=False)  # JSON: {"type": ..., ...}
    trailing_stop_high_watermark = Column(Float, nullable=True)  # Momentum only
    evaluation_window_session = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="OPEN")
    # Valid statuses: OPEN | CLOSED_STOP_LOSS | CLOSED_PROFIT_TARGET |
    #                 CLOSED_WINDOW_EXPIRY | EVALUATED | EVALUATION_FAILED
    exit_price = Column(Float, nullable=True)
    exit_time = Column(DateTime, nullable=True)
    exit_reason = Column(String, nullable=True)  # STOP_LOSS | PROFIT_TARGET | WINDOW_EXPIRY

    session = relationship("Session", back_populates="positions")
    feedback_evaluation = relationship(
        "FeedbackEvaluation", back_populates="position", uselist=False
    )


class FeedbackEvaluation(Base):
    """Written by the feedback agent after comparing entry thesis to outcome."""

    __tablename__ = "feedback_evaluations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False)
    evaluated_at = Column(DateTime, nullable=False)
    evaluation_session_id = Column(String, ForeignKey("sessions.id"), nullable=True)
    candle_close_price = Column(Float, nullable=False)
    thesis_summary = Column(Text, nullable=False)
    outcome_judgment = Column(String, nullable=False)  # CORRECT | INCORRECT | NEUTRAL
    reasoning = Column(Text, nullable=False)
    attempt_count = Column(Integer, nullable=False, default=1)

    position = relationship("Position", back_populates="feedback_evaluation")


class MemoryEntry(Base):
    """Per-ETF per-strategy running performance record. Queryable by main agent."""

    __tablename__ = "memory_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    etf = Column(String, nullable=False)
    strategy = Column(String, nullable=False)   # MEAN_REVERSION | MOMENTUM
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    decision = Column(String, nullable=False)   # BUY | SELL | HOLD
    outcome_judgment = Column(String, nullable=True)  # NULL until feedback evaluation
    regime_context = Column(Text, nullable=False)  # JSON summary of market conditions
    created_at = Column(DateTime, nullable=False)

    session = relationship("Session", back_populates="memory_entries")


def get_engine(db_path: str) -> Engine:
    """Create a SQLAlchemy engine for the given SQLite file path.

    Creates parent directories if they do not exist.
    """
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", echo=False)


def create_tables(engine: Engine) -> None:
    """Create all tables if they do not already exist."""
    Base.metadata.create_all(engine)

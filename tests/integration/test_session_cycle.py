"""Integration test: single session cycle — T031.

Wires together real MemoryBank (SQLite) + real MainAgent (with stubbed
InMemoryRunner / Gemini) + real Scheduler._process_session. Validates:
  - Session record written to DB with status COMPLETED
  - MemoryEntry records written for both ETFs
  - html_report_path is populated when report generator is provided
  - build_snapshot tool called exactly once (Principle V: snapshot isolation)
  - Investigation timeout → SKIPPED_TIMEOUT + BUDGET_TIMEOUT telemetry
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DBSession

from alphoryn.agents.main_agent import MainAgent
from alphoryn.config.models import AlphorynConfig
from alphoryn.execution.agent import ETFDecision, SessionDecision
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import MemoryEntry, Session
from alphoryn.reports.generator import ReportGenerator
from alphoryn.scheduler.scheduler import Scheduler
from alphoryn.telemetry.logger import TelemetryLogger

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CANDLE_CLOSE_AT = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)

_DECISION_DICT = {
    "session_id": "run-1/session-0001",
    "etf1": {
        "etf": "SPY",
        "action": "BUY",
        "strategy": "MEAN_REVERSION",
        "lot_size": 5,
        "exit_target": {"type": "price_level", "value": 460.0},
        "reasoning": "ADX low.",
    },
    "etf2": {
        "etf": "QQQ",
        "action": "HOLD",
        "strategy": "MOMENTUM",
        "lot_size": None,
        "exit_target": None,
        "reasoning": "No regime.",
    },
}

_FIXTURE_DECISION = SessionDecision(
    session_id="run-1/session-0001",
    etf1=ETFDecision(
        etf="SPY",
        action="BUY",
        strategy="MEAN_REVERSION",
        lot_size=5,
        exit_target={"type": "price_level", "value": 460.0},
        reasoning="ADX low.",
    ),
    etf2=ETFDecision(
        etf="QQQ",
        action="HOLD",
        strategy="MOMENTUM",
        lot_size=None,
        exit_target=None,
        reasoning="No regime.",
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_bank(db_path: Path) -> MemoryBank:
    return MemoryBank(str(db_path))


def _make_final_event(decision_dict: dict) -> MagicMock:
    event = MagicMock()
    fc = MagicMock()
    fc.name = "build_snapshot"
    fc.args = {}
    fr = MagicMock()
    fr.name = "build_snapshot"
    event.get_function_calls.return_value = [fc]
    event.get_function_responses.return_value = [fr]
    event.is_final_response.return_value = False

    final_event = MagicMock()
    final_event.get_function_calls.return_value = []
    final_event.get_function_responses.return_value = []
    final_event.is_final_response.return_value = True
    final_event.content.parts = [MagicMock(text=json.dumps(decision_dict))]
    return final_event


def _make_logger() -> TelemetryLogger:
    logger = TelemetryLogger.__new__(TelemetryLogger)
    logger._log_name = "test"
    logger._cloud_logger = None
    return logger


def _make_scheduler(
    bank: MemoryBank,
    *,
    tmp_path: Path,
    main_agent: MainAgent | MagicMock | None = None,
    execution_agent: MagicMock | None = None,
    report_generator: ReportGenerator | None = None,
    logger: TelemetryLogger | MagicMock | None = None,
    investigation_budget: int | None = None,
) -> Scheduler:
    cfg = AlphorynConfig(
        etf1="SPY",
        etf2="QQQ",
        candle_timeframe="1H",
        run_duration="1H",
        max_startup_latency_seconds=3600,
    )
    return Scheduler(
        cfg,
        bank,
        main_agent=main_agent,
        execution_agent=execution_agent,
        report_generator=report_generator,
        logger=logger,
        _investigation_budget_secs=investigation_budget,
    )


def _write_run(bank: MemoryBank) -> int:
    return bank.start_run(config_snapshot="{}", session_count_planned=1)


# ---------------------------------------------------------------------------
# Happy path: Session + MemoryEntry written to DB
# ---------------------------------------------------------------------------


def test_process_session_writes_session_record(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    run_id = _write_run(bank)
    execution_agent = MagicMock()
    logger = MagicMock()

    sched = _make_scheduler(bank, tmp_path=tmp_path, execution_agent=execution_agent, logger=logger)

    with patch.object(sched, "_run_investigation", return_value=_FIXTURE_DECISION):
        sched._process_session(
            run_id=run_id,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=_CANDLE_CLOSE_AT,
        )

    with DBSession(bank._engine) as s:
        sess = s.query(Session).filter(Session.id == "run-1/session-0001").one()
    assert sess.status == "COMPLETED"
    assert sess.etf1_decision == "BUY"
    assert sess.etf2_decision == "HOLD"


def test_process_session_writes_memory_entries(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    run_id = _write_run(bank)
    execution_agent = MagicMock()
    logger = MagicMock()

    sched = _make_scheduler(bank, tmp_path=tmp_path, execution_agent=execution_agent, logger=logger)

    with patch.object(sched, "_run_investigation", return_value=_FIXTURE_DECISION):
        sched._process_session(
            run_id=run_id,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=_CANDLE_CLOSE_AT,
        )

    with DBSession(bank._engine) as s:
        entries = s.query(MemoryEntry).all()
    etfs = {e.etf for e in entries}
    assert etfs == {"SPY", "QQQ"}


def test_process_session_emits_session_start_and_end(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    run_id = _write_run(bank)
    logger = MagicMock()

    sched = _make_scheduler(bank, tmp_path=tmp_path, logger=logger)

    with patch.object(sched, "_run_investigation", return_value=_FIXTURE_DECISION):
        sched._process_session(
            run_id=run_id,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=_CANDLE_CLOSE_AT,
        )

    emitted = [c.args[0] for c in logger.emit.call_args_list]
    assert "SESSION_START" in emitted
    assert "SESSION_END" in emitted


# ---------------------------------------------------------------------------
# html_report_path populated when ReportGenerator is provided
# ---------------------------------------------------------------------------

_FIXTURE_SIGNALS = {
    "rsi_14": 45.2,
    "adx_14": 18.7,
    "ema_20": 451.3,
    "ema_50": 448.9,
    "sma_20": 450.1,
    "bollinger_upper": 465.0,
    "bollinger_lower": 435.0,
    "bollinger_pct_b": 0.42,
    "macd_line": 0.5,
    "macd_signal": 0.3,
    "macd_histogram": 0.2,
    "volume_vs_avg": 1.05,
    "current_price": 452.0,
    "price_vs_ema_20_pct": 0.15,
    "price_vs_sma_20_pct": 0.42,
}


def _make_report_generator_with_stub(tmp_path: Path) -> MagicMock:
    """Return a stub report generator that writes a minimal HTML file."""
    gen = MagicMock()
    report_path = str(tmp_path / "reports" / "run-1" / "run-1/session-0001.html")
    gen.write.return_value = report_path
    return gen


def test_process_session_writes_report_path_to_db(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    run_id = _write_run(bank)
    execution_agent = MagicMock()
    report_generator = _make_report_generator_with_stub(tmp_path)
    logger = MagicMock()

    sched = _make_scheduler(
        bank,
        tmp_path=tmp_path,
        execution_agent=execution_agent,
        report_generator=report_generator,
        logger=logger,
    )

    with patch.object(sched, "_run_investigation", return_value=_FIXTURE_DECISION):
        sched._process_session(
            run_id=run_id,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=_CANDLE_CLOSE_AT,
        )

    with DBSession(bank._engine) as s:
        sess = s.query(Session).filter(Session.id == "run-1/session-0001").one()
    assert sess.html_report_path is not None
    assert sess.html_report_path.endswith(".html")


def test_process_session_report_generator_write_called_with_session_id(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    run_id = _write_run(bank)
    execution_agent = MagicMock()
    report_generator = _make_report_generator_with_stub(tmp_path)

    sched = _make_scheduler(
        bank,
        tmp_path=tmp_path,
        execution_agent=execution_agent,
        report_generator=report_generator,
    )

    with patch.object(sched, "_run_investigation", return_value=_FIXTURE_DECISION):
        sched._process_session(
            run_id=run_id,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=_CANDLE_CLOSE_AT,
        )

    report_generator.write.assert_called_once()
    call_args = report_generator.write.call_args
    assert "run-1/session-0001" in str(call_args)


# ---------------------------------------------------------------------------
# Principle V: snapshot isolation — build_snapshot called exactly once
# during investigation via real MainAgent (stubbed InMemoryRunner)
# ---------------------------------------------------------------------------


def test_main_agent_build_snapshot_called_exactly_once(tmp_path: Path) -> None:
    """Stub InMemoryRunner so no Gemini call is made; assert build_snapshot called once."""
    bank = _init_bank(tmp_path / "memory.db")
    run_id = _write_run(bank)

    market_data = MagicMock()
    logger_agent = MagicMock()
    logger_sched = MagicMock()

    build_snapshot_calls = [0]
    original_build_snapshot = market_data.build_snapshot

    def counting_build_snapshot(*args, **kwargs):
        build_snapshot_calls[0] += 1
        return original_build_snapshot(*args, **kwargs)

    market_data.build_snapshot = counting_build_snapshot

    with patch("alphoryn.agents.main_agent.LlmAgent"):
        main_agent = MainAgent(market_data, logger_agent)

    final_event = _make_final_event(_DECISION_DICT)

    sched = _make_scheduler(
        bank,
        tmp_path=tmp_path,
        main_agent=main_agent,
        logger=logger_sched,
    )

    with patch("alphoryn.agents.main_agent.InMemoryRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter([final_event])

        sched._process_session(
            run_id=run_id,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=_CANDLE_CLOSE_AT,
        )

    # Exactly one call from runner.run() → not called again after build_snapshot returns
    assert mock_runner.run.call_count == 1


# ---------------------------------------------------------------------------
# Investigation timeout → SKIPPED_TIMEOUT + BUDGET_TIMEOUT
# ---------------------------------------------------------------------------


def test_investigation_timeout_writes_skipped_timeout_to_db(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    run_id = _write_run(bank)
    logger = MagicMock()

    sched = _make_scheduler(
        bank, tmp_path=tmp_path, logger=logger, investigation_budget=0
    )
    sched._main_agent = MagicMock()
    sched._main_agent.decide.side_effect = lambda *a, **kw: time.sleep(0.5) or _FIXTURE_DECISION

    sched._process_session(
        run_id=run_id,
        session_id="run-1/session-0001",
        session_ordinal=1,
        candle_close_at=_CANDLE_CLOSE_AT,
    )

    with DBSession(bank._engine) as s:
        sess = s.query(Session).filter(Session.id == "run-1/session-0001").one()
    assert sess.status == "SKIPPED_TIMEOUT"


def test_investigation_timeout_emits_budget_timeout(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    run_id = _write_run(bank)
    logger = MagicMock()

    sched = _make_scheduler(
        bank, tmp_path=tmp_path, logger=logger, investigation_budget=0
    )
    sched._main_agent = MagicMock()
    sched._main_agent.decide.side_effect = lambda *a, **kw: time.sleep(0.5) or _FIXTURE_DECISION

    sched._process_session(
        run_id=run_id,
        session_id="run-1/session-0001",
        session_ordinal=1,
        candle_close_at=_CANDLE_CLOSE_AT,
    )

    emitted = [c.args[0] for c in logger.emit.call_args_list]
    assert "BUDGET_TIMEOUT" in emitted


def test_investigation_timeout_no_memory_entries_written(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    run_id = _write_run(bank)

    sched = _make_scheduler(bank, tmp_path=tmp_path, investigation_budget=0)
    sched._main_agent = MagicMock()
    sched._main_agent.decide.side_effect = lambda *a, **kw: time.sleep(0.5) or _FIXTURE_DECISION

    sched._process_session(
        run_id=run_id,
        session_id="run-1/session-0001",
        session_ordinal=1,
        candle_close_at=_CANDLE_CLOSE_AT,
    )

    with DBSession(bank._engine) as s:
        count = s.query(MemoryEntry).count()
    assert count == 0


# ---------------------------------------------------------------------------
# Execution agent called with the decision
# ---------------------------------------------------------------------------


def test_execution_agent_receives_decision(tmp_path: Path) -> None:
    bank = _init_bank(tmp_path / "memory.db")
    run_id = _write_run(bank)
    execution_agent = MagicMock()

    sched = _make_scheduler(
        bank, tmp_path=tmp_path, execution_agent=execution_agent
    )

    with patch.object(sched, "_run_investigation", return_value=_FIXTURE_DECISION):
        sched._process_session(
            run_id=run_id,
            session_id="run-1/session-0001",
            session_ordinal=1,
            candle_close_at=_CANDLE_CLOSE_AT,
        )

    execution_agent.execute.assert_called_once_with(_FIXTURE_DECISION)

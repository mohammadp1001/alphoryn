"""Integration test: feedback evaluation cycle — T040.

Wires together real MemoryBank (SQLite) + real FeedbackAgent (with stubbed
InMemoryRunner / Gemini). Validates the full learning loop:
  - Closed position + matching evaluation window → FeedbackEvaluation written
  - Position.status set to EVALUATED after successful evaluation
  - MemoryEntry.outcome_judgment populated after evaluation
  - Ticker unblocked (position no longer OPEN) after evaluation
  - 3 consecutive LLM failures → EVALUATION_FAILED, ticker still unblocked
  - MemoryEntry.outcome_judgment NOT set on failure path
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession

from alphoryn.agents.feedback_agent import FeedbackAgent, FeedbackInput
from alphoryn.memory.bank import MemoryBank
from alphoryn.memory.schema import (
    FeedbackEvaluation,
    MemoryEntry,
    Position,
    Run,
    Session,
    create_tables,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
_ENTRY_SESSION_ID = "run-1/session-0001"
_EVAL_SESSION_ID = "run-1/session-0005"
_EVALUATION_WINDOW = 5

_RESULT_DICT = {
    "outcome_judgment": "CORRECT",
    "thesis_summary": "Price expected to mean-revert to SMA_20.",
    "reasoning": "Price rose from entry to exit as predicted by mean-reversion thesis.",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _in_memory_bank() -> MemoryBank:
    bank = MemoryBank.__new__(MemoryBank)
    bank._engine = create_engine("sqlite:///:memory:", echo=False)
    create_tables(bank._engine)
    return bank


def _seed_db(bank: MemoryBank, html_report_path: str = "") -> tuple[int, int]:
    """Seed DB with run, entry session, memory entry, and a closed position.

    Returns (run_id, position_id).
    """
    with DBSession(bank._engine) as s:
        run = Run(
            started_at=_NOW,
            config_snapshot='{"tickers":["SPY","QQQ"]}',
            session_count_planned=6,
        )
        s.add(run)
        s.flush()
        run_id = run.id

        entry_sess = Session(
            id=_ENTRY_SESSION_ID,
            run_id=run_id,
            candle_close_at=_NOW,
            created_at=_NOW,
            status="COMPLETED",
            html_report_path=html_report_path or None,
        )
        s.add(entry_sess)
        s.flush()

        mem_entry = MemoryEntry(
            ticker="SPY",
            strategy="MEAN_REVERSION",
            session_id=_ENTRY_SESSION_ID,
            decision="BUY",
            regime_context="{}",
            created_at=_NOW,
        )
        s.add(mem_entry)
        s.flush()

        pos = Position(
            session_id=_ENTRY_SESSION_ID,
            ticker="SPY",
            strategy="MEAN_REVERSION",
            direction="BUY",
            entry_price=450.0,
            entry_time=_NOW,
            lot_size=5.0,
            stop_loss_price=441.0,
            exit_target='{"type": "price_level", "value": 460.0}',
            evaluation_window_session=_EVALUATION_WINDOW,
            status="CLOSED_PROFIT_TARGET",
            exit_price=460.0,
            exit_time=_NOW,
            exit_reason="PROFIT_TARGET",
        )
        s.add(pos)
        s.commit()
        s.refresh(pos)
        pos_id = pos.id

    return run_id, pos_id


def _make_feedback_agent(bank: MemoryBank) -> tuple[FeedbackAgent, MagicMock, MagicMock]:
    """Return (agent, market_data_mock, logger_mock) with LlmAgent patched."""
    market_data = MagicMock()
    market_data.get_latest_price.return_value = 462.0
    logger = MagicMock()
    with patch("alphoryn.agents.feedback_agent.LlmAgent"):
        agent = FeedbackAgent(market_data, bank, logger)
    return agent, market_data, logger


def _make_event(*, is_final: bool = False, text: str | None = None) -> MagicMock:
    event = MagicMock()
    event.get_function_calls.return_value = []
    event.get_function_responses.return_value = []
    event.is_final_response.return_value = is_final
    if text is not None:
        event.content.parts = [MagicMock(text=text)]
    else:
        event.content = None
    return event


def _make_feedback_input(position_id: int, html_report_path: str = "") -> FeedbackInput:
    return FeedbackInput(
        position_id=position_id,
        session_id=_ENTRY_SESSION_ID,
        ticker="SPY",
        strategy="MEAN_REVERSION",
        html_report_path=html_report_path,
        entry_price=450.0,
        exit_price=460.0,
        exit_reason="PROFIT_TARGET",
    )


# ---------------------------------------------------------------------------
# Happy path — successful evaluation
# ---------------------------------------------------------------------------


def test_evaluate_writes_feedback_evaluation_to_db(tmp_path: Path) -> None:
    bank = _in_memory_bank()
    _, pos_id = _seed_db(bank)
    agent, _, _ = _make_feedback_agent(bank)
    fi = _make_feedback_input(pos_id)

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="mean-revert to SMA"),
    ):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter(
            [_make_event(is_final=True, text=json.dumps(_RESULT_DICT))]
        )
        agent.evaluate(fi, _EVAL_SESSION_ID)

    with DBSession(bank._engine) as s:
        evals = s.query(FeedbackEvaluation).all()
    assert len(evals) == 1
    assert evals[0].position_id == pos_id
    assert evals[0].outcome_judgment == "CORRECT"


def test_evaluate_sets_position_status_evaluated(tmp_path: Path) -> None:
    bank = _in_memory_bank()
    _, pos_id = _seed_db(bank)
    agent, _, _ = _make_feedback_agent(bank)
    fi = _make_feedback_input(pos_id)

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis"),
    ):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter(
            [_make_event(is_final=True, text=json.dumps(_RESULT_DICT))]
        )
        agent.evaluate(fi, _EVAL_SESSION_ID)

    with DBSession(bank._engine) as s:
        pos = s.query(Position).filter(Position.id == pos_id).one()
    assert pos.status == "EVALUATED"


def test_evaluate_populates_memory_entry_judgment() -> None:
    bank = _in_memory_bank()
    _, pos_id = _seed_db(bank)
    agent, _, _ = _make_feedback_agent(bank)
    fi = _make_feedback_input(pos_id)

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis"),
    ):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter(
            [_make_event(is_final=True, text=json.dumps(_RESULT_DICT))]
        )
        agent.evaluate(fi, _EVAL_SESSION_ID)

    with DBSession(bank._engine) as s:
        entry = (
            s.query(MemoryEntry)
            .filter(
                MemoryEntry.session_id == _ENTRY_SESSION_ID,
                MemoryEntry.ticker == "SPY",
            )
            .one()
        )
    assert entry.outcome_judgment == "CORRECT"


def test_evaluate_ticker_unblocked_after_evaluation() -> None:
    """After EVALUATED, position is no longer OPEN → ticker accepts new BUY."""
    bank = _in_memory_bank()
    _, pos_id = _seed_db(bank)
    agent, _, _ = _make_feedback_agent(bank)
    fi = _make_feedback_input(pos_id)

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis"),
    ):
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        mock_runner.run.return_value = iter(
            [_make_event(is_final=True, text=json.dumps(_RESULT_DICT))]
        )
        agent.evaluate(fi, _EVAL_SESSION_ID)

    open_positions = bank.load_open_positions()
    assert all(p.ticker != "SPY" for p in open_positions)


def test_evaluate_extracts_thesis_from_real_html(tmp_path: Path) -> None:
    """_extract_thesis reads investment-thesis section from real HTML file."""
    html = (
        "<html><body>"
        '<section id="investment-thesis"><p>ADX was low; price oversold.</p></section>'
        "</body></html>"
    )
    report = tmp_path / "report.html"
    report.write_text(html, encoding="utf-8")

    bank = _in_memory_bank()
    _, pos_id = _seed_db(bank, html_report_path=str(report))
    agent, _, _ = _make_feedback_agent(bank)
    fi = _make_feedback_input(pos_id, html_report_path=str(report))

    captured_thesis: list[str] = []

    def fake_call_agent(fi_, thesis, price, attempt):
        captured_thesis.append(thesis)
        return json.dumps(_RESULT_DICT)

    with patch.object(agent, "_call_agent", side_effect=fake_call_agent):
        agent.evaluate(fi, _EVAL_SESSION_ID)

    assert len(captured_thesis) == 1
    assert "ADX was low" in captured_thesis[0]


# ---------------------------------------------------------------------------
# 3-failure path — EVALUATION_FAILED
# ---------------------------------------------------------------------------


def test_three_failures_sets_evaluation_failed_status() -> None:
    bank = _in_memory_bank()
    _, pos_id = _seed_db(bank)
    agent, _, _ = _make_feedback_agent(bank)
    fi = _make_feedback_input(pos_id)

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis"),
    ):
        mock_runner_cls.return_value.run.return_value = iter(
            [_make_event(is_final=False)]
        )
        agent.evaluate(fi, _EVAL_SESSION_ID)

    with DBSession(bank._engine) as s:
        pos = s.query(Position).filter(Position.id == pos_id).one()
    assert pos.status == "EVALUATION_FAILED"


def test_three_failures_writes_evaluation_failed_record() -> None:
    bank = _in_memory_bank()
    _, pos_id = _seed_db(bank)
    agent, _, _ = _make_feedback_agent(bank)
    fi = _make_feedback_input(pos_id)

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis"),
    ):
        mock_runner_cls.return_value.run.return_value = iter(
            [_make_event(is_final=False)]
        )
        agent.evaluate(fi, _EVAL_SESSION_ID)

    with DBSession(bank._engine) as s:
        evals = s.query(FeedbackEvaluation).filter(
            FeedbackEvaluation.position_id == pos_id
        ).all()
    assert len(evals) == 1
    assert evals[0].attempt_count == 3


def test_three_failures_ticker_unblocked() -> None:
    """After EVALUATION_FAILED, position is not OPEN → ticker accepts new BUY."""
    bank = _in_memory_bank()
    _, pos_id = _seed_db(bank)
    agent, _, _ = _make_feedback_agent(bank)
    fi = _make_feedback_input(pos_id)

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis"),
    ):
        mock_runner_cls.return_value.run.return_value = iter(
            [_make_event(is_final=False)]
        )
        agent.evaluate(fi, _EVAL_SESSION_ID)

    open_positions = bank.load_open_positions()
    assert all(p.ticker != "SPY" for p in open_positions)


def test_three_failures_memory_entry_judgment_not_set() -> None:
    bank = _in_memory_bank()
    _, pos_id = _seed_db(bank)
    agent, _, _ = _make_feedback_agent(bank)
    fi = _make_feedback_input(pos_id)

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis"),
    ):
        mock_runner_cls.return_value.run.return_value = iter(
            [_make_event(is_final=False)]
        )
        agent.evaluate(fi, _EVAL_SESSION_ID)

    with DBSession(bank._engine) as s:
        entry = (
            s.query(MemoryEntry)
            .filter(
                MemoryEntry.session_id == _ENTRY_SESSION_ID,
                MemoryEntry.ticker == "SPY",
            )
            .one()
        )
    assert entry.outcome_judgment is None


def test_three_failures_emits_evaluation_failed_telemetry() -> None:
    bank = _in_memory_bank()
    _, pos_id = _seed_db(bank)
    agent, _, logger = _make_feedback_agent(bank)
    fi = _make_feedback_input(pos_id)

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner") as mock_runner_cls,
        patch.object(agent, "_extract_thesis", return_value="thesis"),
    ):
        mock_runner_cls.return_value.run.return_value = iter(
            [_make_event(is_final=False)]
        )
        agent.evaluate(fi, _EVAL_SESSION_ID)

    emitted = [c.args[0] for c in logger.emit.call_args_list]
    assert "EVALUATION_FAILED" in emitted


# ---------------------------------------------------------------------------
# Retry succeeds on 3rd attempt
# ---------------------------------------------------------------------------


def test_retry_succeeds_on_third_attempt_writes_evaluated() -> None:
    bank = _in_memory_bank()
    _, pos_id = _seed_db(bank)
    agent, _, _ = _make_feedback_agent(bank)
    fi = _make_feedback_input(pos_id)

    call_count = [0]

    def make_runner(**kwargs):
        m = MagicMock()

        def run_side(*a, **kw):
            call_count[0] += 1
            if call_count[0] < 3:
                return iter([_make_event(is_final=False)])
            return iter([_make_event(is_final=True, text=json.dumps(_RESULT_DICT))])

        m.run.side_effect = run_side
        return m

    with (
        patch("alphoryn.agents.feedback_agent.InMemoryRunner", side_effect=make_runner),
        patch.object(agent, "_extract_thesis", return_value="thesis"),
    ):
        agent.evaluate(fi, _EVAL_SESSION_ID)

    with DBSession(bank._engine) as s:
        pos = s.query(Position).filter(Position.id == pos_id).one()
    assert pos.status == "EVALUATED"
    assert call_count[0] == 3

"""Unit tests for alphoryn/usage/tokens.py."""

from types import SimpleNamespace

from alphoryn.usage import TokenUsage, estimated_usd, format_summary, usage_from_event
from alphoryn.usage.tokens import _as_int


def _meta(**kwargs) -> SimpleNamespace:
    defaults = {
        "prompt_token_count": 0,
        "total_token_count": 0,
        "cached_content_token_count": 0,
        "thoughts_token_count": 0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# from_usage_metadata
# ---------------------------------------------------------------------------


def test_output_is_everything_that_is_not_prompt() -> None:
    """Derived as total - prompt, so it cannot drift with candidates_token_count."""
    usage = TokenUsage.from_usage_metadata(_meta(prompt_token_count=100, total_token_count=350))
    assert usage.input_tokens == 100
    assert usage.output_tokens == 250
    assert usage.calls == 1


def test_reasoning_is_reported_but_not_added_to_output() -> None:
    """Reasoning is a subset of output. Adding them would double-count the bill."""
    usage = TokenUsage.from_usage_metadata(
        _meta(prompt_token_count=100, total_token_count=350, thoughts_token_count=240)
    )
    assert usage.output_tokens == 250
    assert usage.reasoning_tokens == 240


def test_cached_input_is_read_separately() -> None:
    usage = TokenUsage.from_usage_metadata(
        _meta(prompt_token_count=1000, total_token_count=1000, cached_content_token_count=800)
    )
    assert usage.input_tokens == 1000
    assert usage.cached_input_tokens == 800


def test_a_total_below_the_prompt_count_does_not_go_negative() -> None:
    usage = TokenUsage.from_usage_metadata(_meta(prompt_token_count=500, total_token_count=100))
    assert usage.output_tokens == 0


def test_unset_counts_read_as_zero() -> None:
    """Gemini leaves these unset rather than zero when they do not apply."""
    usage = TokenUsage.from_usage_metadata(SimpleNamespace())
    assert usage == TokenUsage(calls=1)


def test_as_int_rejects_non_numbers_and_bools() -> None:
    assert _as_int(None) == 0
    assert _as_int("42") == 0
    assert _as_int(True) == 0
    assert _as_int(7.9) == 7


# ---------------------------------------------------------------------------
# Addition
# ---------------------------------------------------------------------------


def test_usages_add_field_by_field() -> None:
    a = TokenUsage(1, 10, 2, 30, 20)
    b = TokenUsage(1, 5, 1, 7, 3)
    assert a + b == TokenUsage(2, 15, 3, 37, 23)


def test_adding_an_empty_usage_changes_nothing() -> None:
    a = TokenUsage(3, 10, 2, 30, 20)
    assert a + TokenUsage() == a


# ---------------------------------------------------------------------------
# usage_from_event
# ---------------------------------------------------------------------------


def test_event_without_usage_contributes_nothing() -> None:
    """Tool-call events carry no usage. That is the common case, not an error."""
    assert usage_from_event(SimpleNamespace(usage_metadata=None)) == TokenUsage()
    assert usage_from_event(SimpleNamespace()) == TokenUsage()


def test_event_with_usage_is_read() -> None:
    event = SimpleNamespace(
        usage_metadata=_meta(prompt_token_count=10, total_token_count=25)
    )
    assert usage_from_event(event) == TokenUsage(calls=1, input_tokens=10, output_tokens=15)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def test_cost_splits_cached_input_from_fresh_input() -> None:
    """1M fresh in, 1M cached in, 1M out on 2.5-pro = 1.25 + 0.3125 + 10.00."""
    usage = TokenUsage(
        calls=1,
        input_tokens=2_000_000,
        cached_input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert estimated_usd(usage, "gemini-2.5-pro") == 1.25 + 0.3125 + 10.00


def test_flash_lite_is_cheaper_than_pro() -> None:
    usage = TokenUsage(calls=1, input_tokens=1_000_000, output_tokens=1_000_000)
    assert estimated_usd(usage, "gemini-2.5-flash-lite") < estimated_usd(usage, "gemini-2.5-pro")


def test_an_unpriced_model_yields_no_estimate_rather_than_a_wrong_one() -> None:
    usage = TokenUsage(calls=1, input_tokens=1_000_000)
    assert estimated_usd(usage, "gemini-9-imaginary") is None


def test_estimated_usd_is_reachable_from_the_usage_itself() -> None:
    usage = TokenUsage(calls=1, output_tokens=1_000_000)
    assert usage.estimated_usd("gemini-2.5-pro") == 10.00


def test_cached_tokens_exceeding_input_do_not_produce_a_negative_charge() -> None:
    usage = TokenUsage(calls=1, input_tokens=10, cached_input_tokens=99)
    assert estimated_usd(usage, "gemini-2.5-pro") > 0


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------


def test_summary_reports_calls_tokens_and_cost() -> None:
    usage = TokenUsage(
        calls=116,
        input_tokens=988_405,
        cached_input_tokens=576_558,
        output_tokens=219_587,
        reasoning_tokens=205_698,
    )
    line = format_summary(usage, 2.9012)
    assert "116 calls" in line
    assert "988,405 in (576,558 cached)" in line
    assert "219,587 out" in line
    assert "93% reasoning" in line
    assert "~$2.90" in line


def test_summary_says_so_when_the_cost_is_unknown() -> None:
    assert "cost unknown" in format_summary(TokenUsage(calls=1), None)


def test_summary_omits_the_reasoning_share_when_there_is_no_output() -> None:
    """Guards the division: a run that only ever failed has zero output tokens."""
    assert "reasoning" not in format_summary(TokenUsage(calls=1, input_tokens=5), 0.0)

"""What a run spent on the model, in tokens and in dollars.

Nothing in Alphoryn used to report this. Establishing what the 2026-08-13 run
cost meant querying Cloud Logging by hand, and the answer was uncomfortable: the
run spent about $2.90 on the model while the entire trading P&L moved $0.59. A
number nobody can see is a number nobody manages, so the run now prints it.

The surprise that search turned up was the split: 94% of output tokens were
reasoning tokens. Reasoning bills at the output rate, which is 8x the input rate,
so thinking *is* the cost. Note that turning off ``include_thoughts`` would not
help - see ``alphoryn.agents.thinking``, the model reasons either way and you
would only lose the trace. The levers are a thinking budget or a cheaper model.
"""

from dataclasses import dataclass
from typing import Any

# USD per million tokens, Vertex AI list prices for prompts under 200k tokens.
# Cached input is the implicit-caching read rate (25% of the input rate).
# A model missing from this table yields no estimate rather than a wrong one.
_PRICES_USD_PER_MTOK: dict[str, tuple[float, float, float]] = {
    # model: (input, cached_input, output)
    "gemini-2.5-pro": (1.25, 0.3125, 10.00),
    "gemini-2.5-flash": (0.30, 0.075, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.025, 0.40),
}


@dataclass(frozen=True)
class TokenUsage:
    """Tokens consumed across one or more model calls.

    ``output_tokens`` is everything billed at the output rate, reasoning
    included. ``reasoning_tokens`` is the reasoning *subset* of that, reported
    separately because it dominates the bill and is the only part you can act
    on. Adding the two would double-count.

    ``cached_input_tokens`` is likewise a subset of ``input_tokens``, billed at
    the cheaper cache-read rate.
    """

    calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            calls=self.calls + other.calls,
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )

    @classmethod
    def from_usage_metadata(cls, meta: Any) -> "TokenUsage":
        """Read one call's usage off a genai ``usage_metadata``.

        Output is derived as ``total - prompt`` rather than read from
        ``candidates_token_count``, because whether that field includes the
        thought tokens has changed between API versions. The subtraction cannot
        drift: everything that is not prompt is billed at the output rate.
        """
        prompt = _as_int(getattr(meta, "prompt_token_count", 0))
        total = _as_int(getattr(meta, "total_token_count", 0))
        return cls(
            calls=1,
            input_tokens=prompt,
            cached_input_tokens=_as_int(getattr(meta, "cached_content_token_count", 0)),
            output_tokens=max(0, total - prompt),
            reasoning_tokens=_as_int(getattr(meta, "thoughts_token_count", 0)),
        )

    def estimated_usd(self, model: str) -> float | None:
        """Estimated cost of this usage on *model*, or None if it is unpriced."""
        return estimated_usd(self, model)


def usage_from_event(event: Any) -> TokenUsage:
    """Read one ADK event's token usage, or an empty usage if it carries none.

    Every agent that streams ADK events needs exactly this, so it lives here
    once. The last time this kind of response-reading logic was written twice it
    drifted, and the feedback agent spent a month unable to parse a reply
    (#178); ``alphoryn.agents.responses`` exists for the same reason.

    Only some events in a run carry usage - tool-call events do not - so the
    empty return is the common case, not an error.
    """
    meta = getattr(event, "usage_metadata", None)
    if meta is None:
        return TokenUsage()
    return TokenUsage.from_usage_metadata(meta)


def _as_int(value: Any) -> int:
    """Coerce a token count to int, treating None and non-numerics as zero.

    Gemini leaves these fields unset rather than zero when they do not apply,
    and a MagicMock in a test would otherwise arrive here as a non-number.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return int(value)


def estimated_usd(usage: TokenUsage, model: str) -> float | None:
    """Estimated USD for *usage* on *model*, or None when the model is unpriced.

    Returning None for an unknown model is deliberate: a silently wrong cost is
    worse than an absent one, because it would be believed.
    """
    price = _PRICES_USD_PER_MTOK.get(model)
    if price is None:
        return None
    input_rate, cached_rate, output_rate = price
    fresh_input = max(0, usage.input_tokens - usage.cached_input_tokens)
    return (
        fresh_input * input_rate
        + usage.cached_input_tokens * cached_rate
        + usage.output_tokens * output_rate
    ) / 1_000_000


def format_summary(usage: TokenUsage, cost_usd: float | None) -> str:
    """One-line human summary of *usage*, for the end of a run.

    Takes the cost rather than the model so a total spanning two differently
    priced models can be summed by the caller and still print honestly. Pricing
    a mixed total at one model's rate is how a cost report starts lying.
    """
    cost_str = f"~${cost_usd:.2f}" if cost_usd is not None else "cost unknown"
    reasoning_pct = (
        f", {usage.reasoning_tokens * 100 // usage.output_tokens}% reasoning"
        if usage.output_tokens
        else ""
    )
    return (
        f"Model usage: {usage.calls} calls, "
        f"{usage.input_tokens:,} in ({usage.cached_input_tokens:,} cached) / "
        f"{usage.output_tokens:,} out{reasoning_pct}  ->  {cost_str}"
    )

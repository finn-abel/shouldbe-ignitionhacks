"""Scoring seam tests (doc 3 step 3).

Deliberately narrow, per the light testing stance: the stub's exact wording is not
pinned, but two things are. The **seam** must honour SHOULDBE_USE_STUB, and the
**defensive parser** must never let a bad model answer crash the pipeline — that is a
demo-day promise, not framework behaviour.
"""

import json
import re
from decimal import Decimal

import pytest

from app.services import scoring
from app.services.scoring import build_prompt, score_meeting

STANDUP = dict(
    title="Weekly Engineering Standup",
    description="Round the room on what everyone did.",
    duration_minutes=30,
    attendee_count=8,
    is_recurring=True,
    recurrence_freq="WEEKLY",
    cost=Decimal("800.00"),
)
DECISION = dict(
    title="Pricing decision: Q4 enterprise tier",
    description="We need to agree the floor before Friday.",
    duration_minutes=60,
    attendee_count=4,
    is_recurring=False,
    recurrence_freq=None,
    cost=Decimal("585.00"),
)


def _assert_shape(result):
    assert set(result) == {"score", "verdict", "reasoning", "alternative_email"}
    assert isinstance(result["score"], int) and 1 <= result["score"] <= 10
    assert result["verdict"] in {"keep", "email"}
    assert isinstance(result["reasoning"], str) and result["reasoning"].strip()
    assert result["alternative_email"] is None or isinstance(result["alternative_email"], str)
    # §4.4: a drafted email exists exactly when the verdict says the meeting is avoidable.
    assert (result["alternative_email"] is None) == (result["verdict"] == "keep")


# ------------------------------------------------------------------ the stub


def test_standup_is_flagged_as_avoidable(monkeypatch):
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")

    result = score_meeting(**STANDUP)

    _assert_shape(result)
    assert result["verdict"] == "email"
    assert result["score"] == 3  # doc 1's demo arc: recurring standup at 3/10


def test_decision_meeting_is_defended(monkeypatch):
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")

    result = score_meeting(**DECISION)

    _assert_shape(result)
    assert result["verdict"] == "keep"


def test_unrecognised_meeting_is_ambiguous_but_kept(monkeypatch):
    # The rubric defends necessary meetings; no signal must not mean "flag it".
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")

    result = score_meeting(**{**DECISION, "title": "Thursday", "description": ""})

    _assert_shape(result)
    assert result["verdict"] == "keep"
    assert result["score"] == scoring.SCORE_AMBIGUOUS


def test_stub_is_deterministic(monkeypatch):
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")

    assert score_meeting(**STANDUP) == score_meeting(**STANDUP)


def test_async_keyword_does_not_fire_on_a_substring(monkeypatch):
    # "sync" is a signal; "asynchronous" must not trip it.
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")

    result = score_meeting(**{**DECISION, "title": "Asynchronous handoff design"})

    assert result["verdict"] == "keep"


def test_drafted_email_never_mentions_money(monkeypatch):
    # Doc 1 §61: the alternative email is about the topic, never the price.
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")

    draft = score_meeting(**{**STANDUP, "cost": Decimal("12345.67")})["alternative_email"]

    assert draft is not None
    assert "$" not in draft
    assert not re.search(r"\b(cost|budget|salary|rate|spend|12345)\b", draft, re.I)


# ------------------------------------------------------------------- the seam


def test_stub_is_on_by_default(monkeypatch):
    # The app must run with no key and no configuration at all.
    monkeypatch.delenv("SHOULDBE_USE_STUB", raising=False)

    _assert_shape(score_meeting(**STANDUP))


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_switching_the_stub_off_reaches_the_real_provider(monkeypatch, value):
    monkeypatch.setenv("SHOULDBE_USE_STUB", value)
    calls = []
    monkeypatch.setattr(
        scoring,
        "_call_llm",
        lambda prompt: calls.append(prompt)
        or json.dumps(
            {
                "score": 2,
                "verdict": "email",
                "reasoning": "Status only.",
                "alternative_email": "Subject: written update",
            }
        ),
    )

    result = score_meeting(**STANDUP)

    assert len(calls) == 1 and STANDUP["title"] in calls[0]
    _assert_shape(result)
    assert result["score"] == 2 and result["verdict"] == "email"


def test_the_real_branch_is_never_reached_while_the_stub_is_on(monkeypatch):
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")
    monkeypatch.setattr(
        scoring, "_call_llm", lambda prompt: pytest.fail("The stub must not call out.")
    )

    _assert_shape(score_meeting(**STANDUP))


def test_a_missing_key_with_the_stub_off_says_so_plainly(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SHOULDBE_USE_STUB"):
        scoring._call_llm("anything")


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("no key configured"),
        ConnectionError("network is down"),
        Exception("rate limited"),
    ],
)
def test_a_failing_provider_never_breaks_the_pipeline(monkeypatch, failure):
    # A meeting must still be costed and recorded when scoring falls over mid-demo.
    monkeypatch.setenv("SHOULDBE_USE_STUB", "0")

    def explode(prompt):
        raise failure

    monkeypatch.setattr(scoring, "_call_llm", explode)

    result = score_meeting(**STANDUP)

    _assert_shape(result)
    assert result["verdict"] == "keep"
    assert result["score"] == scoring.SCORE_NEUTRAL_FALLBACK
    assert "could not be completed" in result["reasoning"]


def test_a_refusal_is_treated_as_an_unusable_answer(monkeypatch):
    # _call_llm returns "" on stop_reason == "refusal".
    monkeypatch.setenv("SHOULDBE_USE_STUB", "0")
    monkeypatch.setattr(scoring, "_call_llm", lambda prompt: "")

    result = score_meeting(**STANDUP)

    _assert_shape(result)
    assert result["verdict"] == "keep"


def test_prompt_carries_the_rubric_the_facts_and_the_cost():
    prompt = build_prompt(**STANDUP)

    assert "COULD BE AN EMAIL" in prompt and "STAYS A MEETING" in prompt
    assert STANDUP["title"] in prompt
    assert "800.00" in prompt
    assert "WEEKLY" in prompt
    # The model is told the cost, but told to keep it out of the email it drafts.
    assert "must NOT mention cost" in prompt


# ------------------------------------------------- defensive parsing (never crash)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "I'm sorry, I can't help with that.",
        "{",
        "[1, 2, 3]",
        '"just a string"',
        "null",
        '{"score": 3}',                                        # no verdict
        '{"verdict": "email"}',                                # no score
        '{"score": "three", "verdict": "keep", "reasoning": "x"}',
        '{"score": 3, "verdict": "maybe", "reasoning": "x"}',   # not a real verdict
        '{"score": 3, "verdict": "keep", "reasoning": ""}',     # empty reasoning
        '{"score": 3, "verdict": "email", "reasoning": "x"}',   # flagged, nothing to send
    ],
)
def test_unusable_answers_fall_back_to_a_neutral_keep(raw):
    result = scoring._parse_analysis(raw)

    _assert_shape(result)
    assert result["verdict"] == "keep"
    assert result["score"] == scoring.SCORE_NEUTRAL_FALLBACK


def test_none_does_not_crash_the_parser():
    _assert_shape(scoring._parse_analysis(None))


@pytest.mark.parametrize("fence", ["```json\n{body}\n```", "```\n{body}\n```", "```JSON\n{body}```"])
def test_code_fences_are_stripped(fence):
    body = json.dumps(
        {"score": 2, "verdict": "email", "reasoning": "Status only.", "alternative_email": "Subject: x"}
    )

    result = scoring._parse_analysis(fence.format(body=body))

    _assert_shape(result)
    assert result["verdict"] == "email"
    assert result["score"] == 2


@pytest.mark.parametrize(("given", "expected"), [(0, 1), (-4, 1), (11, 10), (999, 10)])
def test_out_of_range_scores_are_clamped(given, expected):
    raw = json.dumps({"score": given, "verdict": "keep", "reasoning": "Needs debate."})

    assert scoring._parse_analysis(raw)["score"] == expected


def test_a_keep_verdict_never_carries_a_drafted_email():
    raw = json.dumps(
        {"score": 9, "verdict": "keep", "reasoning": "Live debate.", "alternative_email": "Subject: oops"}
    )

    result = scoring._parse_analysis(raw)

    _assert_shape(result)
    assert result["alternative_email"] is None


def test_verdict_casing_and_padding_are_tolerated():
    raw = json.dumps(
        {"score": 3, "verdict": " EMAIL ", "reasoning": "Status.", "alternative_email": "Subject: x"}
    )

    assert scoring._parse_analysis(raw)["verdict"] == "email"

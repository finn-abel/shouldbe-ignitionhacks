"""Pipeline smoke test.

One end-to-end pass plus the invariants that hold the analysis record together. The cost
math and the scoring seam have their own thorough suites; this asserts they are wired up
correctly, not that they are individually right.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.enums import Status, Tier, Verdict
from app.schemas.invite import ManualMeetingInput, ParsedInvite
from app.services.pipeline import analyze


def test_recurring_standup_is_costed_scored_and_given_a_replacement(monkeypatch):
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")
    invite = ParsedInvite(
        title="Weekly Engineering Standup",
        description="Round the room on what everyone is working on.",
        duration_minutes=30,
        attendee_tiers=[Tier.IC] * 8 + [Tier.MANAGER],
        organizer_email="pm@acme.com",
        is_recurring=True,
        recurrence_freq="WEEKLY",
    )

    result = analyze(invite)

    assert result.cost == Decimal("229.24")
    assert result.annualized_cost == Decimal("11920.48")  # x 52
    assert result.verdict is Verdict.EMAIL
    assert result.alternative_email  # the meeting has something to be replaced by
    assert result.reasoning
    assert 1 <= result.score <= 10
    assert result.status is Status.ANALYZED
    assert result.reclaimed_savings == Decimal("0.00")


def test_a_kept_meeting_carries_no_drafted_email(monkeypatch):
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")
    invite = ParsedInvite(
        title="Pricing decision: Q4 enterprise tier",
        duration_minutes=60,
        attendee_tiers=[Tier.SENIOR, Tier.SENIOR, Tier.EXEC],
    )

    result = analyze(invite)

    assert result.verdict is Verdict.KEEP
    assert result.alternative_email is None
    assert result.cost == Decimal("212.81")


def test_a_one_off_meeting_has_no_annualized_cost(monkeypatch):
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")

    result = analyze(ParsedInvite(title="Kickoff", attendee_tiers=[Tier.IC]))

    assert result.is_recurring is False
    assert result.annualized_cost is None


def test_per_user_tier_rates_flow_through(monkeypatch):
    # A user can edit their rates; the pipeline must honour them.
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")
    invite = ParsedInvite(title="Kickoff", duration_minutes=60, attendee_tiers=[Tier.IC])

    assert analyze(invite).cost == Decimal("48.96")
    assert analyze(invite, {Tier.IC: Decimal("200")}).cost == Decimal("200.00")


def test_manual_form_expands_head_counts_into_attendees():
    form = ManualMeetingInput(
        title="Weekly Engineering Standup",
        duration_minutes=30,
        attendees={Tier.IC: 8, Tier.MANAGER: 1},
        is_recurring=True,
        recurrence_freq="weekly",
    )

    invite = form.to_parsed_invite()

    assert invite.attendee_count == 9
    assert invite.attendee_tiers.count(Tier.IC) == 8
    assert invite.recurrence_freq == "WEEKLY"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"is_recurring": True},                                # recurring, no frequency
        {"is_recurring": True, "recurrence_freq": "FORTNIGHTLY"},  # unreadable frequency
    ],
)
def test_unusable_recurrence_is_rejected_at_the_request_boundary(kwargs):
    # Must fail as request validation (422), not inside the cost math (500).
    with pytest.raises(ValidationError):
        ManualMeetingInput(title="Sync", attendees={Tier.IC: 2}, **kwargs)


def test_a_one_off_meeting_drops_a_stray_frequency():
    form = ManualMeetingInput(
        title="One off", attendees={Tier.IC: 1}, is_recurring=False, recurrence_freq="WEEKLY"
    )

    assert form.to_parsed_invite().recurrence_freq is None


def test_a_meeting_with_no_attendees_costs_nothing(monkeypatch):
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")

    result = analyze(ManualMeetingInput(title="Empty hold", attendees={}).to_parsed_invite())

    assert result.cost == Decimal("0.00")
    assert result.attendee_count == 0

"""`analyze()` — the one pipeline every door feeds (doc 2 §1, §5).

Door A (emailed .ics), Door B (manual form) and Door C (saved .ics) all reduce to a
`ParsedInvite` before they get here, so this function is byte-for-byte the same code on
every path. It is pure: no HTTP, no database.
"""

from decimal import Decimal

from app.enums import Status, Tier, Verdict
from app.schemas.api import MeetingAnalysis
from app.schemas.invite import ParsedInvite
from app.services.costing import annualized_cost, meeting_cost
from app.services.scoring import score_meeting

NOTHING_RECLAIMED = Decimal("0.00")


def analyze(
    invite: ParsedInvite,
    tier_rates: dict[Tier, Decimal] | None = None,
) -> MeetingAnalysis:
    """Cost the meeting, score it, and assemble the analysis record."""
    cost = meeting_cost(invite.attendee_tiers, invite.duration_minutes, tier_rates)
    yearly = annualized_cost(cost, invite.is_recurring, invite.recurrence_freq)

    assessment = score_meeting(
        title=invite.title,
        description=invite.description,
        duration_minutes=invite.duration_minutes,
        attendee_count=invite.attendee_count,
        is_recurring=invite.is_recurring,
        recurrence_freq=invite.recurrence_freq,
        cost=cost,
    )

    verdict = Verdict(assessment["verdict"])

    return MeetingAnalysis(
        title=invite.title,
        description=invite.description,
        start=invite.start,
        duration_minutes=invite.duration_minutes,
        attendee_count=invite.attendee_count,
        attendee_tiers=invite.attendee_tiers,
        organizer_email=invite.organizer_email,
        is_recurring=invite.is_recurring,
        recurrence_freq=invite.recurrence_freq,
        cost=cost,
        annualized_cost=yearly,
        score=assessment["score"],
        verdict=verdict,
        reasoning=assessment["reasoning"],
        # A drafted replacement exists only for a meeting we are saying to replace (§4.4).
        alternative_email=assessment["alternative_email"] if verdict is Verdict.EMAIL else None,
        analysis_notice=assessment.get("analysis_notice"),
        analysis_error_code=assessment.get("analysis_error_code"),
        status=Status.ANALYZED,
        reclaimed_savings=NOTHING_RECLAIMED,
    )

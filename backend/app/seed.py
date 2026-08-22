"""Seed the shared guest user with curated demo data (doc 2 §7).

Run from /backend:  PYTHONPATH=. python -m app.seed

Rewritable and idempotent: it clears the guest's meetings and re-creates them, so it can
be re-run before a demo to reset numbers that have drifted from people using the shared
guest. Meetings are produced by the real `analyze()` pipeline rather than hand-written, so
the seeded costs, verdicts and reasoning are internally consistent with the live engine.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete

from app.data.db import SessionLocal, init_db
from app.data.meetings import save_analysis
from app.data.models import Meeting
from app.data.tiers import get_tier_rates
from app.data.users import get_or_create_guest
from app.enums import Status, Tier
from app.schemas.invite import ParsedInvite
from app.services.pipeline import analyze

# The seeded spend meaningfully exceeds this, so the dashboard opens "over budget" (§7).
# Sized against the curated federal-rate set below so this month's spend is still roughly
# 34% over budget.
GUEST_BUDGET = Decimal("4021.86")

ORGANIZER = "ops@northwind.example"

# (invite, days ago, final status). Titles are chosen so the scoring rubric reaches the
# intended verdict on its own — nothing here overrides the engine.
CURATED = [
    # The demo drill-down: 18 people for half an hour against federal reference rates,
    # recurring weekly.
    (ParsedInvite(
        title="All-hands engineering standup",
        description="Every team reads out what they did yesterday and what they will do today.",
        duration_minutes=30,
        attendee_tiers=[Tier.IC] * 12 + [Tier.SENIOR] * 5 + [Tier.MANAGER],
        organizer_email=ORGANIZER,
        is_recurring=True,
        recurrence_freq="WEEKLY",
    ), 1, Status.ANALYZED),

    (ParsedInvite(
        title="Q4 enterprise pricing decision",
        description="We need to agree the floor before the board meets on Friday.",
        duration_minutes=60,
        attendee_tiers=[Tier.SENIOR, Tier.SENIOR, Tier.MANAGER, Tier.EXEC, Tier.EXEC],
        organizer_email=ORGANIZER,
    ), 2, Status.ANALYZED),

    (ParsedInvite(
        title="Incident postmortem: payments outage",
        description="What broke, why it took 40 minutes to notice, and what we change.",
        duration_minutes=90,
        attendee_tiers=[Tier.IC] * 4 + [Tier.SENIOR] * 3 + [Tier.MANAGER, Tier.EXEC],
        organizer_email=ORGANIZER,
    ), 3, Status.ANALYZED),

    (ParsedInvite(
        title="Cross-team sync",
        description="Everyone shares where their piece is at.",
        duration_minutes=45,
        attendee_tiers=[Tier.IC] * 10 + [Tier.SENIOR] * 3 + [Tier.MANAGER] * 2,
        organizer_email=ORGANIZER,
        is_recurring=True,
        recurrence_freq="BIWEEKLY",
    ), 5, Status.ANALYZED),

    (ParsedInvite(
        title="Architecture review: billing rewrite",
        description="Walk the proposal and argue the trade-offs before anyone writes code.",
        duration_minutes=90,
        attendee_tiers=[Tier.IC] * 4 + [Tier.SENIOR] * 3 + [Tier.MANAGER],
        organizer_email=ORGANIZER,
    ), 6, Status.ANALYZED),

    (ParsedInvite(
        title="Board prep dry run",
        description="Run the deck end to end and cut what does not land.",
        duration_minutes=60,
        attendee_tiers=[Tier.MANAGER] * 2 + [Tier.EXEC] * 3,
        organizer_email=ORGANIZER,
    ), 8, Status.ANALYZED),

    (ParsedInvite(
        title="Weekly ops sync",
        description="FYI on open tickets and anything blocked.",
        duration_minutes=30,
        attendee_tiers=[Tier.IC] * 6 + [Tier.MANAGER] * 2,
        organizer_email=ORGANIZER,
        is_recurring=True,
        recurrence_freq="WEEKLY",
    ), 9, Status.HELD),

    (ParsedInvite(
        title="Design critique: onboarding flow",
        description="Walk the prototype together and argue about the second screen.",
        duration_minutes=60,
        attendee_tiers=[Tier.IC] * 3 + [Tier.SENIOR] * 2 + [Tier.MANAGER],
        organizer_email=ORGANIZER,
    ), 11, Status.ANALYZED),

    (ParsedInvite(
        title="Weekly project status update",
        description="Each workstream posts where it got to.",
        duration_minutes=30,
        attendee_tiers=[Tier.IC] * 8 + [Tier.SENIOR] * 2,
        organizer_email=ORGANIZER,
        is_recurring=True,
        recurrence_freq="WEEKLY",
    ), 12, Status.HELD),

    (ParsedInvite(
        title="Candidate debrief: staff engineer",
        description="Compare notes and make a call.",
        duration_minutes=45,
        attendee_tiers=[Tier.SENIOR] * 3 + [Tier.MANAGER],
        organizer_email=ORGANIZER,
    ), 14, Status.ANALYZED),

    (ParsedInvite(
        title="Skip-level 1:1",
        description="Career conversation, no agenda.",
        duration_minutes=30,
        attendee_tiers=[Tier.IC, Tier.EXEC],
        organizer_email=ORGANIZER,
    ), 15, Status.ANALYZED),

    # Already converted — these are the reclaimed savings the counter opens on.
    (ParsedInvite(
        title="Sprint status update",
        description="Read-out of what shipped this sprint.",
        duration_minutes=45,
        attendee_tiers=[Tier.IC] * 9 + [Tier.SENIOR] * 2,
        organizer_email=ORGANIZER,
    ), 16, Status.CONVERTED),

    (ParsedInvite(
        title="Monthly roadmap status update",
        description="Each lead presents their slide. No decisions on the agenda.",
        duration_minutes=60,
        attendee_tiers=[Tier.MANAGER] * 6 + [Tier.EXEC] * 2,
        organizer_email=ORGANIZER,
        is_recurring=True,
        recurrence_freq="MONTHLY",
    ), 18, Status.CONVERTED),
]


def _placed_within_this_month(days_ago: int, now: datetime) -> datetime:
    """Keep every seeded meeting inside the current calendar month.

    The headline compares *this month's* spend against the budget, so a meeting
    backdated across the 1st would silently vanish from it — which on the 2nd of a month
    would leave the demo opening on an empty dashboard.
    """
    return now - timedelta(days=min(days_ago, max(now.day - 1, 0)))


def seed():
    init_db()
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        guest = get_or_create_guest(session)

        session.execute(delete(Meeting).where(Meeting.user_id == guest.id))
        guest.budget.monthly_amount = GUEST_BUDGET
        session.commit()

        rates = get_tier_rates(session, guest.id)

        for invite, days_ago, status in CURATED:
            meeting = save_analysis(session, guest.id, analyze(invite, rates))
            meeting.created_at = _placed_within_this_month(days_ago, now)
            if status is Status.CONVERTED:
                meeting.status = Status.CONVERTED
                meeting.reclaimed_savings = meeting.cost
            elif status is Status.HELD:
                meeting.status = Status.HELD
        session.commit()

        return guest.id


if __name__ == "__main__":
    guest_id = seed()
    print(f"Seeded the guest user (id={guest_id}) with {len(CURATED)} curated meetings.")

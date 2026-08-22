"""Seed the shared guest user with curated demo data (doc 2 §7).

Run from /backend:  PYTHONPATH=. python -m app.seed

Rewritable and idempotent: it clears the guest's meetings and re-creates them, so it can
be re-run before a demo to reset numbers that have drifted from people using the shared
guest. Meetings are produced by the real `analyze()` pipeline rather than hand-written, so
the seeded costs, verdicts and reasoning are internally consistent with the live engine.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.data.db import SessionLocal, init_db
from app.data.meetings import save_analysis
from app.data.models import EmailOutbox, Meeting, MeetingAttendee, Person
from app.data.people import tier_map, upsert_person
from app.data.tiers import get_tier_rates
from app.data.inbound_routes import set_domain
from app.data.users import get_or_create_guest
from app.enums import Status, Tier
from app.schemas.invite import ParsedInvite
from app.services.directory import resolved_invite
from app.services.pipeline import analyze

# The seeded spend meaningfully exceeds this, so the dashboard opens "over budget" (§7).
# Sized against the curated federal-rate set below so this month's spend is still roughly
# 34% over budget.
GUEST_BUDGET = Decimal("4021.86")

ORGANIZER = "ops@northwind.example"

# The guest owns the demo company's domain, so a demo invite sent from any northwind
# address lands on the seeded ledger rather than falling through to the guest by accident.
# It also means the domain-claim feature is visibly exercised on a fresh database.
GUEST_DOMAIN = "northwind.example"

# The demo's cast, in the order they sit in the standup. Named addresses rather than head
# counts because the standup is the drill-down, and the point of the drill-down is now
# *who* is in the room — an emailed invite carries addresses, and the directory is what
# turns them into a cost.
STANDUP_ROOM = (
    [(f"{name}@northwind.example", Tier.IC)
     for name in ("ada", "bo", "cy", "dee", "eli", "fay", "gus", "hal", "ivy", "jon", "kai", "lee")]
    + [(f"{name}@northwind.example", Tier.SENIOR)
       for name in ("mia", "noor", "omar", "pia", "quinn")]
    + [("rae@northwind.example", Tier.MANAGER)]
)

# Four of the standup's ICs are deliberately left out of the directory, so a fresh demo
# opens with a real worklist: four addresses ShouldBe has seen and cannot price properly.
# They are all ICs, so the seeded figures are exactly what they were before the directory
# existed — identifying them is what moves the number, and it moves it live.
UNPLACED = frozenset(
    f"{name}@northwind.example" for name in ("ivy", "jon", "kai", "lee")
)

# What the guest knows. Everyone in the standup except the four above, plus the guest's
# own role — the one entry every user can answer, and the one that makes their own
# meetings price correctly.
SEEDED_DIRECTORY = {
    email: tier for email, tier in STANDUP_ROOM if email not in UNPLACED
} | {"guest@shouldbe.local": Tier.MANAGER}

# (invite, days ago, final status). Titles are chosen so the scoring rubric reaches the
# intended verdict on its own — nothing here overrides the engine.
CURATED = [
    # The demo drill-down: 18 people for half an hour against federal reference rates,
    # recurring weekly.
    (ParsedInvite(
        title="All-hands engineering standup",
        description="Every team reads out what they did yesterday and what they will do today.",
        duration_minutes=30,
        attendee_tiers=[tier for _, tier in STANDUP_ROOM],
        attendee_emails=[email for email, _ in STANDUP_ROOM],
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

        # Outbox rows reference meetings, so they go first — otherwise re-seeding a
        # database that has taken real invites trips the foreign key.
        stale = select(Meeting.id).where(Meeting.user_id == guest.id)
        session.execute(delete(EmailOutbox).where(EmailOutbox.meeting_id.in_(stale)))
        session.execute(delete(MeetingAttendee).where(MeetingAttendee.meeting_id.in_(stale)))
        session.execute(delete(Meeting).where(Meeting.user_id == guest.id))
        # The directory is re-seeded too, so a reset puts the four unplaced people back on
        # the worklist. Otherwise the second demo of the day opens with nothing to identify.
        session.execute(delete(Person).where(Person.user_id == guest.id))
        guest.budget.monthly_amount = GUEST_BUDGET
        session.commit()

        set_domain(session, guest.id, GUEST_DOMAIN)

        for email, tier in SEEDED_DIRECTORY.items():
            upsert_person(session, guest.id, email, tier, commit=False)
        session.commit()

        rates = get_tier_rates(session, guest.id)
        known = tier_map(session, guest.id)

        for invite, days_ago, status in CURATED:
            # Through the directory, exactly as an emailed invite goes. The curated tiers
            # and the seeded roles agree by construction, so this changes no figure — it
            # is what makes the four unplaced seats *recorded* as the guesses they are.
            resolved = resolved_invite(invite, known)
            meeting = save_analysis(
                session,
                guest.id,
                analyze(resolved, rates),
                tier_rates=rates,
                known_people=known,
            )
            meeting.created_at = _placed_within_this_month(days_ago, now)
            if status is Status.CONVERTED:
                meeting.status = Status.CONVERTED
                meeting.reclaimed_savings = meeting.cost
            elif status is Status.HELD:
                meeting.status = Status.HELD
        session.commit()

        return guest.id


def seed_if_empty():
    """Seed only when the guest's ledger is empty. Returns the guest id, or None.

    A brand-new Render Postgres is empty, and an empty dashboard is not a demo. This runs
    on boot so the deployed app is populated without anyone shelling into the service —
    but it refuses to run over an existing ledger, because a web service restarts for
    reasons nobody chose (a deploy, a spin-down wake, an OOM) and wiping a judge's
    just-analyzed meeting mid-demo would be worse than an empty dashboard ever was.

    Use `python -m app.seed` for the deliberate, destructive reset.
    """
    init_db()

    with SessionLocal() as session:
        guest = get_or_create_guest(session)
        already = session.execute(
            select(Meeting.id).where(Meeting.user_id == guest.id).limit(1)
        ).first()
        if already:
            return None

    return seed()


if __name__ == "__main__":
    guest_id = seed()
    print(f"Seeded the guest user (id={guest_id}) with {len(CURATED)} curated meetings.")

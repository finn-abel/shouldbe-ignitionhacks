"""Meeting ledger persistence.

Every read is scoped by `user_id`. The ledger records **all** analyzed meetings, `keep`
verdicts included — it is total meeting spend, and the verdict is an attribute of the
transaction rather than a filter on what gets written.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.data.models import Meeting, MeetingAttendee
from app.data.outbox import enqueue_with_meeting
from app.enums import Status, Tier, Verdict
from app.schemas.api import MeetingAnalysis
from app.services.costing import annualized_cost, cost_from_rates, rate_for
from app.services.directory import person_key
from app.services.money import reclaimed_by_converting


def _seat_rows(
    analysis: MeetingAnalysis,
    known: dict[str, Tier],
    tier_rates: dict[Tier, Decimal] | None,
) -> list[MeetingAttendee]:
    """One durable row per seat, at the tier and rate the meeting was actually priced at.

    The tier comes from the analysis rather than from a fresh directory lookup: the seat
    must record what it *was billed as*, not what the directory says a moment later. The
    directory is consulted only to answer "was this a guess?".
    """
    emails = list(analysis.attendee_emails)
    emails += [""] * (len(analysis.attendee_tiers) - len(emails))

    rows = []
    for position, (tier, email) in enumerate(zip(analysis.attendee_tiers, emails)):
        key = person_key(email)
        rows.append(
            MeetingAttendee(
                position=position,
                email=key,
                tier=tier,
                hourly_rate=rate_for(tier, tier_rates),
                # A seat with no address is not unidentified — manual-form head counts are
                # anonymous by design and their tiers came from the user directly.
                is_assumed=bool(key) and key not in known,
            )
        )
    return rows


def save_analysis(
    session: Session,
    user_id: int,
    analysis: MeetingAnalysis,
    source_key: str | None = None,
    reply: tuple[str, str, str] | None = None,
    tier_rates: dict[Tier, Decimal] | None = None,
    known_people: dict[str, Tier] | None = None,
) -> Meeting:
    """Write one analysis to the ledger as a costed transaction.

    `source_key` identifies the invite a meeting came from, so a redelivered inbound
    email cannot land twice. It is None for the manual form, which has no such notion.

    `reply` is an optional `(to_email, subject, text_body)` for inbound email, queued in this
    same commit. Committing it separately would mean a meeting could be on the books with
    its reply lost in between — which is the exact failure the outbox exists to remove. If
    the unique constraint rejects the meeting on a redelivery, the reply rolls back with it.
    """
    meeting = Meeting(
        user_id=user_id,
        source_key=source_key,
        title=analysis.title,
        description=analysis.description,
        start=analysis.start,
        duration_minutes=analysis.duration_minutes,
        attendee_count=analysis.attendee_count,
        # The column is JSON, so store the tiers in their serialisable form.
        attendee_tiers=[tier.value for tier in analysis.attendee_tiers],
        organizer_email=analysis.organizer_email,
        is_recurring=analysis.is_recurring,
        recurrence_freq=analysis.recurrence_freq,
        budget_scope_type=analysis.budget_scope_type,
        budget_scope_name=analysis.budget_scope_name,
        cost=analysis.cost,
        annualized_cost=analysis.annualized_cost,
        score=analysis.score,
        verdict=analysis.verdict,
        reasoning=analysis.reasoning,
        alternative_email=analysis.alternative_email,
        status=analysis.status,
        reclaimed_savings=analysis.reclaimed_savings,
    )
    # Written in the same commit as the meeting: a ledger row whose seats went missing
    # would be permanently un-correctable, and there would be no way to tell that from a
    # meeting that genuinely had nobody to identify.
    meeting.attendees = _seat_rows(
        analysis,
        known_people if known_people is not None else {},
        tier_rates,
    )
    session.add(meeting)

    if reply is not None:
        to_email, subject, text_body = reply
        enqueue_with_meeting(session, meeting, to_email, subject, text_body)

    session.commit()
    session.refresh(meeting)
    meeting.analysis_notice = analysis.analysis_notice
    meeting.analysis_error_code = analysis.analysis_error_code
    return meeting


def find_by_source_key(session: Session, user_id: int, source_key: str) -> Meeting | None:
    """The meeting already recorded for this invite, if any."""
    return session.scalar(
        select(Meeting).where(
            Meeting.user_id == user_id, Meeting.source_key == source_key
        )
    )


# The guest user is shared and writable, so its ledger grows with every person who tries
# the demo. Every stats request reads the whole ledger, so leave it unbounded and the
# dashboard degrades quietly as the day goes on.
MAX_LEDGER_ROWS = 500


def list_meetings(
    session: Session, user_id: int, limit: int = MAX_LEDGER_ROWS
) -> list[Meeting]:
    """The acting user's ledger, newest first, most recent `limit` rows."""
    return list(
        session.scalars(
            select(Meeting)
            # `MeetingRead` reads the seat list for its unidentified count, so load it
            # here: lazily, 500 ledger rows would be 500 extra queries per dashboard load.
            .options(selectinload(Meeting.attendees))
            .where(Meeting.user_id == user_id)
            .order_by(Meeting.created_at.desc(), Meeting.id.desc())
            .limit(limit)
        )
    )


def get_meeting(session: Session, user_id: int, meeting_id: int) -> Meeting | None:
    """One meeting, or None if it does not exist *or* belongs to someone else."""
    return session.scalar(
        select(Meeting)
        .options(selectinload(Meeting.attendees))
        .where(Meeting.id == meeting_id, Meeting.user_id == user_id)
    )


@dataclass(frozen=True)
class Repricing:
    """What identifying one person changed. Aggregate figures only, as everywhere else."""

    meetings_repriced: int
    seats_corrected: int
    cost_before: Decimal
    cost_after: Decimal

    @property
    def cost_delta(self) -> Decimal:
        """Positive means the ledger was understating this spend, which is the usual case."""
        return self.cost_after - self.cost_before


def _reprice(meeting: Meeting) -> None:
    """Recompute one meeting's money from its seats. Assumes every seat is present."""
    meeting.cost = cost_from_rates([seat.hourly_rate for seat in meeting.attendees],
                                   meeting.duration_minutes)
    meeting.annualized_cost = annualized_cost(
        meeting.cost, meeting.is_recurring, meeting.recurrence_freq
    )
    meeting.attendee_tiers = [seat.tier.value for seat in meeting.attendees]
    # Savings are defined as the cost of the meeting that did not happen, so a corrected
    # cost is a corrected saving. Leaving this alone would let a converted meeting claim
    # a reclaimed figure that no longer matches anything on the row.
    if meeting.status is Status.CONVERTED:
        meeting.reclaimed_savings = reclaimed_by_converting(meeting.cost)


def identify_people(
    session: Session,
    user_id: int,
    placements: dict[str, Tier],
    tier_rates: dict[Tier, Decimal] | None = None,
) -> Repricing:
    """Place previously-unknown attendees, and correct every meeting that guessed at them.

    This is the one place the ledger is allowed to change what a past meeting cost, and it
    is narrow on purpose:

    - Only seats flagged `is_assumed` move. A seat whose tier was known when the meeting
      was priced keeps its rate forever, which is why changing a *rate* still never
      re-prices history — that path touches no assumed flag.
    - Only the corrected seats take a new rate. Every other seat in the same meeting is
      re-summed at the rate stored on it, so a correction cannot quietly re-price the
      rest of the room at today's rates.

    The result is arithmetic, not a rewrite: the meeting was always this expensive, the
    ledger just did not know it yet.

    Every placement is applied in one pass rather than one call each, because two people
    are routinely in the same meeting — placing them separately would count that meeting
    twice and report a correction roughly double the one that happened.
    """
    by_key = {}
    for email, tier in placements.items():
        key = person_key(email)
        if not key:
            raise ValueError(f"{email!r} is not an email address.")
        by_key[key] = tier

    nothing = Repricing(0, 0, Decimal("0.00"), Decimal("0.00"))
    if not by_key:
        return nothing

    seats = list(
        session.scalars(
            select(MeetingAttendee)
            .join(Meeting, Meeting.id == MeetingAttendee.meeting_id)
            .options(selectinload(MeetingAttendee.meeting).selectinload(Meeting.attendees))
            .where(
                Meeting.user_id == user_id,
                MeetingAttendee.email.in_(list(by_key)),
                MeetingAttendee.is_assumed.is_(True),
            )
        )
    )
    if not seats:
        return nothing

    touched: dict[int, Meeting] = {}
    corrected = 0
    before = Decimal("0.00")

    for seat in seats:
        meeting = seat.meeting
        # A meeting recorded before seats were stored has none, and re-summing an empty
        # list would silently zero its cost. It cannot reach here — the seat we are
        # holding belongs to it — but the guard is cheap and the failure is a wiped
        # ledger row.
        if len(meeting.attendees) != meeting.attendee_count:
            continue
        if meeting.id not in touched:
            touched[meeting.id] = meeting
            before += meeting.cost

        seat.tier = by_key[seat.email]
        seat.hourly_rate = rate_for(seat.tier, tier_rates)
        seat.is_assumed = False
        corrected += 1

    for meeting in touched.values():
        _reprice(meeting)

    session.commit()

    after = sum((meeting.cost for meeting in touched.values()), Decimal("0.00"))
    return Repricing(
        meetings_repriced=len(touched),
        seats_corrected=corrected,
        cost_before=before,
        cost_after=after,
    )


def identify_person(
    session: Session,
    user_id: int,
    email: str,
    tier: Tier,
    tier_rates: dict[Tier, Decimal] | None = None,
) -> Repricing:
    """Place one person. The single-name case of `identify_people`."""
    return identify_people(session, user_id, {email: tier}, tier_rates)


class NotConvertible(Exception):
    """Raised when a meeting cannot be swapped for an email."""


def convert_meeting(session: Session, user_id: int, meeting_id: int) -> Meeting | None:
    """Swap a flagged meeting for its drafted email.

    Returns None if the meeting does not exist or belongs to someone else. Converting an
    already-converted meeting is a no-op, so a double click cannot inflate savings.
    """
    meeting = get_meeting(session, user_id, meeting_id)
    if meeting is None:
        return None

    if meeting.verdict is not Verdict.EMAIL:
        raise NotConvertible(
            "Only meetings flagged as avoidable can be converted to an email."
        )

    meeting.status = Status.CONVERTED
    meeting.reclaimed_savings = reclaimed_by_converting(meeting.cost)
    session.commit()
    session.refresh(meeting)
    return meeting

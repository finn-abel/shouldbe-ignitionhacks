"""Meeting ledger persistence (doc 2 §3.1: `data/` is ORM models + DB access).

Every read is scoped by `user_id`. The ledger records **all** analyzed meetings, `keep`
verdicts included — it is total meeting spend, and the verdict is an attribute of the
transaction rather than a filter on what gets written (doc 2 §4.4, §6).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Meeting
from app.data.outbox import enqueue_with_meeting
from app.enums import Status, Verdict
from app.schemas.api import MeetingAnalysis
from app.services.money import reclaimed_by_converting


def save_analysis(
    session: Session,
    user_id: int,
    analysis: MeetingAnalysis,
    source_key: str | None = None,
    reply: tuple[str, str, str] | None = None,
) -> Meeting:
    """Write one analysis to the ledger as a costed transaction.

    `source_key` identifies the invite a meeting came from, so a redelivered inbound
    email cannot land twice. It is None for the manual form, which has no such notion.

    `reply` is an optional `(to_email, subject, text_body)` for Door A, queued in this
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
            .where(Meeting.user_id == user_id)
            .order_by(Meeting.created_at.desc(), Meeting.id.desc())
            .limit(limit)
        )
    )


def get_meeting(session: Session, user_id: int, meeting_id: int) -> Meeting | None:
    """One meeting, or None if it does not exist *or* belongs to someone else."""
    return session.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.user_id == user_id)
    )


class NotConvertible(Exception):
    """Raised when a meeting cannot be swapped for an email."""


def convert_meeting(session: Session, user_id: int, meeting_id: int) -> Meeting | None:
    """Swap a flagged meeting for its drafted email (doc 2 §5.4).

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

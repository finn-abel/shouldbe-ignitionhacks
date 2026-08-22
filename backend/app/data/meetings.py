"""Meeting ledger persistence (doc 2 §3.1: `data/` is ORM models + DB access).

Every read is scoped by `user_id`. The ledger records **all** analyzed meetings, `keep`
verdicts included — it is total meeting spend, and the verdict is an attribute of the
transaction rather than a filter on what gets written (doc 2 §4.4, §6).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Meeting
from app.schemas.api import MeetingAnalysis


def save_analysis(session: Session, user_id: int, analysis: MeetingAnalysis) -> Meeting:
    """Write one analysis to the ledger as a costed transaction."""
    meeting = Meeting(
        user_id=user_id,
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
    session.commit()
    session.refresh(meeting)
    return meeting


def list_meetings(session: Session, user_id: int) -> list[Meeting]:
    """The acting user's ledger, newest first."""
    return list(
        session.scalars(
            select(Meeting)
            .where(Meeting.user_id == user_id)
            .order_by(Meeting.created_at.desc(), Meeting.id.desc())
        )
    )


def get_meeting(session: Session, user_id: int, meeting_id: int) -> Meeting | None:
    """One meeting, or None if it does not exist *or* belongs to someone else."""
    return session.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.user_id == user_id)
    )

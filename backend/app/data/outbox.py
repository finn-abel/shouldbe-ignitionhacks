"""Outbound reply persistence — the transactional outbox.

The important call is `enqueue_with_meeting`: the reply row is written in the *same*
commit as its meeting. Anything less reintroduces the failure this table exists to remove,
where a meeting is on the books but its reply was lost between two commits.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import EmailOutbox, Meeting
from app.enums import OutboxStatus

# After this many failed attempts a row stops being retried and is marked FAILED. Postmark
# retries are cheap, but a permanently bad address should not be tried forever.
MAX_ATTEMPTS = 8


def enqueue_with_meeting(
    session: Session,
    meeting: Meeting,
    to_email: str,
    subject: str,
    text_body: str,
) -> EmailOutbox:
    """Add the reply to the pending session so it commits with the meeting.

    Deliberately does NOT commit: the caller owns the transaction, and the whole point is
    that this row and the `Meeting` land together or not at all.
    """
    reply = EmailOutbox(
        meeting=meeting,
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        status=OutboxStatus.QUEUED,
        attempts=0,
    )
    session.add(reply)
    return reply


def claim_queued(session: Session, limit: int) -> list[EmailOutbox]:
    """The oldest queued replies, in the order they were created."""
    return list(
        session.scalars(
            select(EmailOutbox)
            .where(EmailOutbox.status == OutboxStatus.QUEUED)
            .order_by(EmailOutbox.created_at, EmailOutbox.id)
            .limit(limit)
        )
    )


def mark_sent(session: Session, reply: EmailOutbox) -> None:
    reply.status = OutboxStatus.SENT
    reply.attempts += 1
    reply.last_error = None
    reply.sent_at = datetime.now(timezone.utc)
    session.commit()


def mark_attempt_failed(
    session: Session, reply: EmailOutbox, error: str, permanent: bool
) -> None:
    """Record a failed attempt.

    `permanent` is the whole distinction the outbox turns on. A malformed recipient is
    FAILED and never tried again. Everything else — no API key yet, an unverified sending
    domain, a rate limit, a provider outage — leaves the row QUEUED, because those resolve
    on their own and the reply should send itself when they do. Erring toward permanent
    buries a message that was going to deliver minutes later.
    """
    reply.attempts += 1
    reply.last_error = error[:2000]
    if permanent or reply.attempts >= MAX_ATTEMPTS:
        reply.status = OutboxStatus.FAILED
    session.commit()


def list_for_user(session: Session, user_id: int, limit: int = 50) -> list[EmailOutbox]:
    """This user's replies, newest first — what `GET /api/outbox` returns."""
    return list(
        session.scalars(
            select(EmailOutbox)
            .join(Meeting, EmailOutbox.meeting_id == Meeting.id)
            .where(Meeting.user_id == user_id)
            .order_by(EmailOutbox.created_at.desc(), EmailOutbox.id.desc())
            .limit(limit)
        )
    )

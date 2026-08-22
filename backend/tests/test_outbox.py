"""The reply must survive a failed send.

Before the outbox, a reply was a `BackgroundTasks` call: if Postmark was unreachable the
send was logged and lost, and because a redelivered invite hits the idempotency guard and
returns early, nothing ever tried again. These tests pin the two properties that fixes:
the reply is committed with its meeting, and a temporary failure stays queued.

The last one is not hypothetical — a new Postmark account refuses every recipient outside
your own verified domains until it is manually approved.
"""

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data.db import Base
from app.data.meetings import save_analysis
from app.data.models import EmailOutbox, Meeting, User
from app.data.outbox import MAX_ATTEMPTS, list_for_user
from app.enums import OutboxStatus, Tier
from app.schemas.invite import ParsedInvite
from app.services import email as email_service
from app.services.email import drain_outbox
from app.services.pipeline import analyze

REPLY = ("dana@northwind.example", "Sync — could be an email (3/10)", "body text")

# Every email-related variable these tests care about. `app.main` and `app.data.db` call
# `load_dotenv()` at import, so a developer's real .env would otherwise leak in and quietly
# decide what these tests are actually exercising — a developer with RESEND_API_KEY set would
# otherwise silently exercise a different provider than the one a test means to pin.
EMAIL_ENV_VARS = (
    "EMAIL_PROVIDER",
    "POSTMARK_TOKEN",
    "POSTMARK_FROM",
    "POSTMARK_STREAM",
    "RESEND_API_KEY",
    "RESEND_FROM",
)


@pytest.fixture(autouse=True)
def isolated_email_env(monkeypatch):
    """No ambient email config. Each test opts in to exactly what it needs."""
    for name in EMAIL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        s.add(User(email="dana@northwind.example", display_name="Dana"))
        s.commit()
        yield s


@pytest.fixture
def user(session):
    return session.query(User).one()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("POSTMARK_TOKEN", "test-token")
    monkeypatch.setenv("POSTMARK_FROM", "shouldbe@invite.example.com")


def an_analysis():
    return analyze(
        ParsedInvite(
            title="Sync",
            organizer_email="dana@northwind.example",
            attendee_tiers=[Tier.IC, Tier.IC],
            duration_minutes=30,
        )
    )


def fake_postmark(monkeypatch, status_code=200, body=None, raises=None):
    """Stand in for the one `httpx.post` in `email.py`. Records what it was called with."""
    calls = []

    def _post(url, **kwargs):
        calls.append(kwargs.get("json"))
        if raises is not None:
            raise raises
        return httpx.Response(
            status_code, json=body if body is not None else {"ErrorCode": 0}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(email_service.httpx, "post", _post)
    return calls


# ------------------------------------------------- committed with the meeting


def test_the_reply_is_written_in_the_same_commit_as_the_meeting(session, user):
    meeting = save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)

    reply = session.query(EmailOutbox).one()
    assert reply.meeting_id == meeting.id
    assert reply.status is OutboxStatus.QUEUED
    assert reply.to_email == "dana@northwind.example"
    assert reply.attempts == 0


def test_a_rejected_redelivery_leaves_no_orphan_reply(session, user):
    """The meeting and its reply roll back together, or the ledger grows a ghost email."""
    save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)
    session.rollback()

    assert session.query(Meeting).count() == 1
    assert session.query(EmailOutbox).count() == 1


def test_the_manual_form_queues_nothing(session, user):
    # Door B has no organizer to reply to.
    save_analysis(session, user.id, an_analysis())

    assert session.query(EmailOutbox).count() == 0


# ------------------------------------------------------------------ draining


def test_a_successful_drain_marks_the_reply_sent(session, user, configured, monkeypatch):
    calls = fake_postmark(monkeypatch)
    save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)

    assert drain_outbox(session) == 1

    reply = session.query(EmailOutbox).one()
    assert reply.status is OutboxStatus.SENT
    assert reply.sent_at is not None
    assert reply.last_error is None
    assert calls[0]["To"] == "dana@northwind.example"


def test_a_sent_reply_is_never_sent_twice(session, user, configured, monkeypatch):
    fake_postmark(monkeypatch)
    save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)
    drain_outbox(session)

    assert drain_outbox(session) == 0


def test_postmark_not_configured_leaves_the_reply_queued(session, user, monkeypatch):
    """Unconfigured is a setup state, not a delivery failure. The reply waits."""
    monkeypatch.delenv("POSTMARK_TOKEN", raising=False)
    monkeypatch.delenv("POSTMARK_FROM", raising=False)
    save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)

    assert drain_outbox(session) == 0

    reply = session.query(EmailOutbox).one()
    assert reply.status is OutboxStatus.QUEUED
    assert reply.attempts == 1
    assert "not configured" in reply.last_error


def test_a_reply_queued_while_unconfigured_sends_once_postmark_arrives(
    session, user, monkeypatch
):
    """The whole reason the outbox exists: nothing has to be re-entered by hand."""
    monkeypatch.delenv("POSTMARK_TOKEN", raising=False)
    monkeypatch.delenv("POSTMARK_FROM", raising=False)
    save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)
    drain_outbox(session)

    monkeypatch.setenv("POSTMARK_TOKEN", "test-token")
    monkeypatch.setenv("POSTMARK_FROM", "shouldbe@invite.example.com")
    fake_postmark(monkeypatch)

    assert drain_outbox(session) == 1
    assert session.query(EmailOutbox).one().status is OutboxStatus.SENT


def test_pending_account_approval_keeps_the_reply_queued(
    session, user, configured, monkeypatch
):
    """A new Postmark account 422s every recipient outside your verified domains until it
    is approved. That resolves on its own, so the reply must not be buried."""
    fake_postmark(monkeypatch, status_code=422, body={"ErrorCode": 412, "Message": "Account pending approval."})
    save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)

    drain_outbox(session)

    reply = session.query(EmailOutbox).one()
    assert reply.status is OutboxStatus.QUEUED
    assert "pending approval" in reply.last_error


def test_a_bad_recipient_fails_permanently(session, user, configured, monkeypatch):
    fake_postmark(monkeypatch, status_code=422, body={"ErrorCode": 300, "Message": "Invalid 'To' address."})
    save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)

    drain_outbox(session)

    assert session.query(EmailOutbox).one().status is OutboxStatus.FAILED


def test_a_network_error_is_retried_not_buried(session, user, configured, monkeypatch):
    fake_postmark(monkeypatch, raises=httpx.ConnectError("no route to host"))
    save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)

    drain_outbox(session)

    assert session.query(EmailOutbox).one().status is OutboxStatus.QUEUED


def test_a_reply_gives_up_after_max_attempts(session, user, configured, monkeypatch):
    fake_postmark(monkeypatch, raises=httpx.ConnectError("no route to host"))
    save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)

    for _ in range(MAX_ATTEMPTS):
        drain_outbox(session)

    reply = session.query(EmailOutbox).one()
    assert reply.status is OutboxStatus.FAILED
    assert reply.attempts == MAX_ATTEMPTS


def test_the_outbox_is_scoped_to_its_owner(session, user, configured, monkeypatch):
    other = User(email="raj@contoso.example", display_name="Raj")
    session.add(other)
    session.commit()
    save_analysis(session, user.id, an_analysis(), "ics:uid-1", reply=REPLY)

    assert len(list_for_user(session, user.id)) == 1
    assert list_for_user(session, other.id) == []

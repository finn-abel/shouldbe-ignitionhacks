"""Door A must survive redelivery (doc 3 step 13 hardening).

Postmark redelivers an inbound message up to six times over ~51 minutes — on a non-2xx,
on a network failure, and on a timeout where the endpoint did the work but answered too
slowly. Without a dedup key that is six ledger rows and six emails to the organizer, so
these are correctness tests, not CRUD tests.
"""

import base64
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data.db import Base
from app.data.meetings import find_by_source_key, list_meetings, save_analysis
from app.data.models import User
from app.enums import Tier
from app.schemas.invite import ParsedInvite
from app.services.ics_adapter import source_key_for
from app.services.pipeline import analyze

UID = "abc123@google.com"


def invite_text(uid=UID):
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//T//EN", "BEGIN:VEVENT",
        "DTSTART:20260824T150000Z", "DTEND:20260824T153000Z",
        "SUMMARY:Weekly Engineering Standup", "ORGANIZER:mailto:p@x.com",
        "ATTENDEE;CN=A:mailto:a@x.com", "ATTENDEE;CN=B:mailto:b@x.com",
    ]
    if uid:
        lines.append(f"UID:{uid}")
    return "\r\n".join(lines + ["END:VEVENT", "END:VCALENDAR"])


def postmark_payload(message_id="msg-1", uid=UID):
    return {
        "MessageID": message_id,
        "From": "p@x.com",
        "Attachments": [
            {
                "Name": "invite.ics",
                "ContentType": "text/calendar",
                "Content": base64.b64encode(invite_text(uid).encode()).decode(),
            }
        ],
    }


@pytest.fixture
def session():
    """A throwaway in-memory database, so the constraint under test is a real one."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        s.add(User(email="guest@shouldbe.local", display_name="Guest", is_guest=True))
        s.commit()
        yield s


@pytest.fixture
def guest(session):
    return session.query(User).one()


# ------------------------------------------------------------------ the key


def test_the_event_uid_is_preferred_over_the_message_id():
    # A forwarded copy of the same invite gets a fresh MessageID but keeps its UID.
    first = source_key_for(postmark_payload("msg-1"), invite_text())
    forwarded = source_key_for(postmark_payload("msg-999"), invite_text())

    assert first == forwarded == f"ics:{UID}"


def test_an_invite_with_no_uid_falls_back_to_the_message_id():
    assert source_key_for(postmark_payload("msg-7", uid=None), invite_text(uid=None)) == (
        "postmark:msg-7"
    )


def test_an_invite_with_neither_has_no_key():
    assert source_key_for({}, invite_text(uid=None)) is None


def test_two_different_invites_get_different_keys():
    a = source_key_for(postmark_payload(), invite_text("one@x"))
    b = source_key_for(postmark_payload(), invite_text("two@x"))

    assert a != b


# ------------------------------------------------------- the ledger guarantee


def _record(session, guest, key):
    invite = ParsedInvite(
        title="Weekly Engineering Standup",
        duration_minutes=30,
        attendee_tiers=[Tier.IC, Tier.IC],
        organizer_email="p@x.com",
    )
    return save_analysis(session, guest.id, analyze(invite), key)


def test_the_same_invite_cannot_be_recorded_twice(session, guest):
    from sqlalchemy.exc import IntegrityError

    key = source_key_for(postmark_payload(), invite_text())
    first = _record(session, guest, key)

    with pytest.raises(IntegrityError):
        _record(session, guest, key)
    session.rollback()

    assert len(list_meetings(session, guest.id)) == 1
    assert find_by_source_key(session, guest.id, key).id == first.id


def test_a_recorded_invite_is_found_before_any_second_analysis(session, guest):
    # The fast path the webhook takes, so a retry never even reaches the LLM.
    key = source_key_for(postmark_payload(), invite_text())
    _record(session, guest, key)

    assert find_by_source_key(session, guest.id, key) is not None


def test_manual_form_meetings_are_unconstrained(session, guest):
    # source_key is NULL for Door B, and SQL treats every NULL as distinct — two
    # identical typed-in meetings are two real meetings.
    _record(session, guest, None)
    _record(session, guest, None)

    assert len(list_meetings(session, guest.id)) == 2


def test_different_invites_both_land(session, guest):
    _record(session, guest, "ics:one@x")
    _record(session, guest, "ics:two@x")

    assert len(list_meetings(session, guest.id)) == 2


def test_the_same_invite_to_two_users_is_two_meetings(session, guest):
    # The constraint is per user, not global.
    other = User(email="other@x.com", display_name="Other")
    session.add(other)
    session.commit()

    key = "ics:shared@x"
    _record(session, guest, key)
    _record(session, other, key)

    assert len(list_meetings(session, guest.id)) == 1
    assert len(list_meetings(session, other.id)) == 1


def test_a_redelivered_invite_does_not_change_the_money(session, guest):
    key = source_key_for(postmark_payload(), invite_text())
    _record(session, guest, key)

    from app.schemas.api import MeetingRead
    from app.services.money import total_spend

    before = total_spend([MeetingRead.model_validate(m) for m in list_meetings(session, guest.id)])

    with pytest.raises(Exception):
        _record(session, guest, key)
    session.rollback()

    after = total_spend([MeetingRead.model_validate(m) for m in list_meetings(session, guest.id)])
    assert before == after == Decimal("48.96")


# ------------------------------------------------------- the shared guest's ledger


def test_the_ledger_read_is_bounded(session, guest):
    # The guest is shared and writable, so its ledger grows all day. Every stats request
    # reads the whole thing.
    from app.data.meetings import MAX_LEDGER_ROWS

    for n in range(MAX_LEDGER_ROWS + 25):
        _record(session, guest, f"ics:{n}@x")

    rows = list_meetings(session, guest.id)

    assert len(rows) == MAX_LEDGER_ROWS
    # Newest first, so the cap drops the oldest rows rather than the current ones.
    assert rows[0].id > rows[-1].id


def test_a_smaller_limit_can_be_asked_for(session, guest):
    for n in range(5):
        _record(session, guest, f"ics:{n}@x")

    assert len(list_meetings(session, guest.id, limit=2)) == 2

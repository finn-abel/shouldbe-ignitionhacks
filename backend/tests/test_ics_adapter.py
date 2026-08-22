"""Door A / Door C adapter tests (doc 3 step 13).

Two things here are money logic, not parsing trivia, and both are tested as such: which
attendees get billed, and how an RRULE becomes an annualized figure. The reply's privacy
guarantees are asserted too — they are a product promise from doc 1 §59-61.
"""

import base64
from decimal import Decimal

import pytest

from app.enums import Tier, Verdict
from app.services.email import compose_reply
from app.services.ics_adapter import (
    DEFAULT_ATTENDEE_TIER,
    NoInviteFound,
    find_ics_text,
    parse_ics,
    recurrence_from_rrule,
)
from app.services.pipeline import analyze

SHOULDBE = "shouldbe@example.com"


def invite_text(*, rrule=None, attendees=(SHOULDBE, "a@x.com", "b@x.com"), end="20260824T153000Z"):
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Test//EN", "METHOD:REQUEST",
        "BEGIN:VEVENT",
        "DTSTART:20260824T150000Z", f"DTEND:{end}",
        "ORGANIZER;CN=Priya:mailto:priya@x.com",
        "SUMMARY:Weekly Engineering Standup",
        "DESCRIPTION:Round the room on progress.",
    ]
    if rrule:
        lines.append(f"RRULE:{rrule}")
    lines += [f"ATTENDEE;CN=P:mailto:{a}" for a in attendees]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines)


# ------------------------------------------------------- who actually gets billed


def test_shouldbes_own_address_is_not_billed_as_an_attendee():
    # Billing the tool would inflate every meeting it is ever invited to.
    invite = parse_ics(invite_text(), (SHOULDBE,))

    assert SHOULDBE not in invite.attendee_emails
    # a@x.com, b@x.com, and Priya, who organized it — three people, one of whom is not
    # in the ATTENDEE list. 3 IT-02 references x 30 minutes.
    assert invite.attendee_count == 3
    assert analyze(invite).cost == Decimal("73.44")


def test_without_the_exclusion_the_tool_would_be_billed():
    # Guards the guard: proves the exclusion is doing work.
    assert parse_ics(invite_text()).attendee_count == 4


def test_the_exclusion_is_case_insensitive():
    assert parse_ics(invite_text(), ("ShouldBe@Example.COM",)).attendee_count == 3


def test_the_organizer_is_counted_even_when_the_client_omits_them_from_attendee():
    """The reported bug: a two-person meeting priced as one.

    Whether the organizer also appears in ATTENDEE is a fact about the sending client —
    Google repeats them there, Outlook does not — and never a fact about who is in the
    room. Counting only ATTENDEE understated every invite from the second kind of client
    by exactly one person, in the direction nobody checks.
    """
    outlook = parse_ics(invite_text(attendees=(SHOULDBE, "a@x.com")), (SHOULDBE,))
    google = parse_ics(invite_text(attendees=(SHOULDBE, "a@x.com", "priya@x.com")), (SHOULDBE,))

    assert outlook.attendee_count == 2, "the organizer is in the room"
    assert "priya@x.com" in outlook.attendee_emails
    # The same two people either way: the organizer is seated once, never twice.
    assert outlook.attendee_emails == google.attendee_emails
    assert analyze(outlook).cost == analyze(google).cost


def test_attendees_are_priced_at_the_lowest_tier():
    # An .ics carries no roles, so understate rather than overstate someone's time.
    invite = parse_ics(invite_text(), (SHOULDBE,))

    assert set(invite.attendee_tiers) == {DEFAULT_ATTENDEE_TIER}
    assert DEFAULT_ATTENDEE_TIER is Tier.IC


def test_a_meeting_with_no_attendees_but_shouldbe_costs_nothing():
    """Nobody left in the room means no meeting — not a room of one.

    The organizer is otherwise seated, so this is the case that decides whether a private
    calendar block lands on the ledger. It does not: an invite whose only other attendee
    is ShouldBe is a hold on one person's own time, not meeting spend.
    """
    invite = parse_ics(invite_text(attendees=(SHOULDBE,)), (SHOULDBE,))

    assert invite.attendee_count == 0
    assert analyze(invite).cost == Decimal("0.00")


# ------------------------------------------------- RRULE becomes an annual figure


@pytest.mark.parametrize(
    ("rrule", "expected"),
    [
        ("FREQ=DAILY", "DAILY"),
        ("FREQ=WEEKLY;BYDAY=MO", "WEEKLY"),
        ("FREQ=WEEKLY;INTERVAL=2", "BIWEEKLY"),  # RRULE never says "BIWEEKLY"
        ("FREQ=MONTHLY;BYMONTHDAY=1", "MONTHLY"),
        ("FREQ=YEARLY", "YEARLY"),
    ],
)
def test_rrule_maps_to_a_frequency_the_cost_math_knows(rrule, expected):
    assert recurrence_from_rrule(rrule) == expected


@pytest.mark.parametrize(
    ("rrule", "expected"),
    [
        ("FREQ=WEEKLY;INTERVAL=3", "MONTHLY"),   # not weekly — that would treble the year
        ("FREQ=DAILY;INTERVAL=4", "WEEKLY"),
        ("FREQ=MONTHLY;INTERVAL=6", "YEARLY"),
    ],
)
def test_an_interval_with_no_exact_bucket_rounds_DOWN_in_cost(rrule, expected):
    assert recurrence_from_rrule(rrule) == expected


def test_no_rrule_means_a_one_off_with_no_annual_cost():
    invite = parse_ics(invite_text(), (SHOULDBE,))

    assert invite.is_recurring is False
    assert analyze(invite).annualized_cost is None


def test_a_weekly_invite_annualizes_at_fifty_two_occurrences():
    invite = parse_ics(invite_text(rrule="FREQ=WEEKLY"), (SHOULDBE,))

    assert analyze(invite).annualized_cost == Decimal("3818.88")  # 73.44 x 52


def test_an_unreadable_rrule_is_treated_as_non_recurring():
    assert recurrence_from_rrule("GARBAGE") is None
    assert recurrence_from_rrule("") is None
    assert recurrence_from_rrule(None) is None


def test_an_invite_with_no_end_time_falls_back_to_an_hour():
    text = invite_text().replace("DTEND:20260824T153000Z\r\n", "")

    assert parse_ics(text, (SHOULDBE,)).duration_minutes == 60


# ------------------------------------------------------ pulling the .ics out of email


def test_a_base64_calendar_attachment_is_found():
    payload = {
        "Attachments": [
            {"Name": "not-it.pdf", "ContentType": "application/pdf", "Content": "eA=="},
            {
                "Name": "invite.ics",
                "ContentType": 'text/calendar; method=REQUEST; charset="UTF-8"',
                "Content": base64.b64encode(invite_text().encode()).decode(),
            },
        ]
    }

    assert "BEGIN:VCALENDAR" in find_ics_text(payload)


def test_an_invite_pasted_into_the_body_is_found():
    payload = {"TextBody": f"see below\n{invite_text()}\nthanks"}

    assert find_ics_text(payload).startswith("BEGIN:VCALENDAR")


@pytest.mark.parametrize("payload", [{}, {"TextBody": "just a note"}, {"Attachments": []}])
def test_an_email_with_no_invite_says_so_rather_than_crashing(payload):
    with pytest.raises(NoInviteFound):
        find_ics_text(payload)


def test_unreadable_calendar_text_is_reported_not_raised_raw():
    with pytest.raises(NoInviteFound):
        parse_ics("this is not a calendar")


# ------------------------------------------------- what leaves in the organizer reply


def test_the_reply_carries_the_score_the_cost_and_the_draft():
    analysis = analyze(parse_ics(invite_text(rrule="FREQ=WEEKLY"), (SHOULDBE,)))

    subject, body = compose_reply(analysis)

    assert str(analysis.score) in subject
    assert "$73.44" in body
    assert "$3,818.88 a year" in body
    assert analysis.alternative_email in body


def test_the_reply_never_names_an_attendee_or_a_rate():
    # Doc 1 §59-60: aggregate only. No individual, no role rate, ever.
    analysis = analyze(parse_ics(invite_text(rrule="FREQ=WEEKLY"), (SHOULDBE,)))

    _, body = compose_reply(analysis)

    for address in ("a@x.com", "b@x.com"):
        assert address not in body
    for rate in ("48.96/hr", "$48.96/hr", "per person", "each"):
        assert rate not in body
    assert "No individual's rate or salary" in body


def test_a_kept_meeting_reply_offers_no_replacement_email():
    analysis = analyze(
        parse_ics(invite_text().replace("SUMMARY:Weekly Engineering Standup",
                                        "SUMMARY:Q4 pricing decision"), (SHOULDBE,))
    )

    subject, body = compose_reply(analysis)

    assert analysis.verdict is Verdict.KEEP
    # Asserted through the shared label rather than a copy of the string: the wording is
    # said on the dashboard, in the ledger, and here, and a test holding its own copy is
    # how those three drift apart without anything going red.
    assert Verdict.KEEP.label in subject
    assert "could replace it" not in body


def test_an_invite_missing_PRODID_is_still_read():
    # The ics library rejects the whole calendar without it; dropping a real meeting
    # over a header nobody reads would be the worse failure.
    text = invite_text().replace("PRODID:-//Test//EN\r\n", "")

    invite = parse_ics(text, (SHOULDBE,))

    assert invite.title == "Weekly Engineering Standup"
    assert invite.attendee_count == 3

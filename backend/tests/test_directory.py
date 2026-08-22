"""Identifying the people in a meeting, and what that does to the ledger.

The bug these exist for is quiet and systematic: an .ics carries addresses and no roles,
so every emailed meeting was priced as if the whole room were the lowest tier. A room of
directors read the same as a room of juniors, and nothing anywhere said "this is a guess".

So the tests come in two halves. The first is that a guess is *recorded as* a guess. The
second is the correction: identifying someone re-prices the meetings that guessed at them
and — just as importantly — leaves alone the ones that did not.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data.db import Base
from app.data.meetings import identify_person, list_meetings, save_analysis
from app.data.models import User
from app.data.people import (
    delete_person,
    list_people,
    tier_map,
    unidentified_addresses,
    upsert_person,
)
from app.enums import Status, Tier
from app.schemas.api import MeetingRead
from app.schemas.invite import ManualMeetingInput, ParsedInvite
from app.services.costing import DEFAULT_TIER_RATES
from app.services.directory import person_key, resolved_invite, seats_for, unidentified
from app.services.ics_adapter import parse_ics
from app.services.pipeline import analyze

RATES = DEFAULT_TIER_RATES


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        s.add(User(email="dana@northwind.example", display_name="Dana"))
        s.commit()
        yield s


@pytest.fixture
def dana(session):
    return session.query(User).one()


ICS = """BEGIN:VCALENDAR
PRODID:-//Test//EN
VERSION:2.0
BEGIN:VEVENT
UID:roles-1
SUMMARY:Quarterly planning
DTSTART:20260401T150000Z
DURATION:PT1H
ORGANIZER:mailto:Ada@Northwind.Example
ATTENDEE:mailto:Ada@Northwind.Example
ATTENDEE:mailto:bo@northwind.example
ATTENDEE:mailto:cy@northwind.example
END:VEVENT
END:VCALENDAR
"""


def record(session, user, invite, known=None, status=None):
    """Analyze and save one invite the way a door does, directory and all."""
    known = tier_map(session, user.id) if known is None else known
    resolved = resolved_invite(invite, known)
    analysis = analyze(resolved, RATES)
    if status is not None:
        analysis = analysis.model_copy(update={"status": status})
    return save_analysis(session, user.id, analysis, tier_rates=RATES, known_people=known)


# ------------------------------------------------- the addresses survive the parse


def test_the_ics_adapter_keeps_the_addresses_it_counts():
    """It used to count the attendees and throw the addresses away.

    That single line was what made every emailed meeting permanently un-correctable:
    the head count survived, the identities did not, and nothing could be looked up
    afterwards.
    """
    invite = parse_ics(ICS)

    assert invite.attendee_count == 3
    assert invite.attendee_emails == [
        "ada@northwind.example",
        "bo@northwind.example",
        "cy@northwind.example",
    ]


def test_addresses_are_normalized_so_one_person_is_one_person():
    assert person_key("  Ada@Northwind.Example ") == "ada@northwind.example"
    assert person_key("Ada Lovelace <ada@northwind.example>") == "ada@northwind.example"
    assert person_key("mailto:ada@northwind.example") == "ada@northwind.example"
    assert person_key("not-an-address") == ""


def test_an_email_list_shorter_than_the_room_does_not_shift_the_seats():
    """Misalignment would attribute seat 3's person to seat 2's tier, silently."""
    invite = ParsedInvite(
        title="Sync",
        attendee_tiers=[Tier.IC, Tier.EXEC, Tier.EXEC],
        attendee_emails=["ada@northwind.example"],
    )

    assert invite.attendee_emails == ["ada@northwind.example", "", ""]


# --------------------------------------------------------- a guess says it is one


def test_an_unknown_attendee_is_priced_but_flagged(session, dana):
    meeting = record(session, dana, parse_ics(ICS))

    assert meeting.cost > 0, "an unknown room still has to land on the ledger"
    assert meeting.unidentified_count == 3
    assert [seat.tier for seat in meeting.attendees] == [Tier.IC] * 3
    assert all(seat.is_assumed for seat in meeting.attendees)


def test_a_known_attendee_is_priced_at_their_real_tier(session, dana):
    upsert_person(session, dana.id, "ada@northwind.example", Tier.EXEC)

    meeting = record(session, dana, parse_ics(ICS))

    assert [seat.tier for seat in meeting.attendees] == [Tier.EXEC, Tier.IC, Tier.IC]
    assert meeting.unidentified_count == 2, "only the two nobody has placed"


def test_manual_form_seats_are_known_not_unidentified(session, dana):
    """Door B asks for head counts per tier, so its seats came from the user directly.

    Anonymous is not the same as unidentified: there is nobody here to go and look up,
    and putting these on the worklist would make it permanently non-empty.
    """
    form = ManualMeetingInput(title="Sprint planning", attendees={Tier.IC: 2, Tier.EXEC: 1})

    meeting = record(session, dana, form.to_parsed_invite())

    assert meeting.attendee_count == 3, "resolving an address-less invite must not empty it"
    assert meeting.cost > 0
    assert meeting.unidentified_count == 0
    assert unidentified_addresses(session, dana.id) == {}


def test_the_worklist_is_the_addresses_nobody_has_placed(session, dana):
    record(session, dana, parse_ics(ICS))
    record(session, dana, parse_ics(ICS.replace("roles-1", "roles-2")))

    assert unidentified_addresses(session, dana.id) == {
        "ada@northwind.example": 2,
        "bo@northwind.example": 2,
        "cy@northwind.example": 2,
    }


# ---------------------------------------------------- identifying someone re-prices


def test_identifying_someone_corrects_every_meeting_that_guessed(session, dana):
    first = record(session, dana, parse_ics(ICS))
    second = record(session, dana, parse_ics(ICS.replace("roles-1", "roles-2")))
    before = first.cost

    result = identify_person(session, dana.id, "ada@northwind.example", Tier.EXEC, RATES)

    assert result.meetings_repriced == 2
    assert result.seats_corrected == 2
    assert result.cost_delta > 0, "the ledger was understating this spend"

    session.refresh(first)
    session.refresh(second)
    # One hour, one seat moving from the IC rate to the EXEC rate.
    assert first.cost - before == RATES[Tier.EXEC] - RATES[Tier.IC]
    assert first.unidentified_count == 2
    assert second.cost == first.cost


def test_only_the_corrected_seat_moves(session, dana):
    """The rest of the room keeps the rate it was recorded at, not today's rate.

    This is the difference between correcting a guess and re-pricing history. Every seat
    stores what it was billed, so identifying one person cannot quietly re-rate the other
    seventeen.
    """
    meeting = record(session, dana, parse_ics(ICS))
    others = [seat.hourly_rate for seat in meeting.attendees[1:]]

    identify_person(session, dana.id, "ada@northwind.example", Tier.MANAGER, RATES)

    session.refresh(meeting)
    assert meeting.attendees[0].hourly_rate == RATES[Tier.MANAGER]
    assert [seat.hourly_rate for seat in meeting.attendees[1:]] == others


def test_a_seat_that_was_never_a_guess_is_never_re_priced(session, dana):
    """The ledger invariant, kept: a known tier is what happened, and stays.

    Without this, correcting a typo in someone's role would silently re-price months of
    meetings that were already right — the same reason editing a *rate* does not reach
    backwards.
    """
    upsert_person(session, dana.id, "ada@northwind.example", Tier.SENIOR)
    meeting = record(session, dana, parse_ics(ICS))
    priced_at = meeting.cost

    upsert_person(session, dana.id, "ada@northwind.example", Tier.EXEC)
    result = identify_person(session, dana.id, "ada@northwind.example", Tier.EXEC, RATES)

    assert result.meetings_repriced == 0
    session.refresh(meeting)
    assert meeting.cost == priced_at


def test_a_repriced_recurring_meeting_re_annualizes(session, dana):
    recurring = ICS.replace("END:VEVENT", "RRULE:FREQ=WEEKLY\r\nEND:VEVENT")
    meeting = record(session, dana, parse_ics(recurring))
    before = meeting.annualized_cost

    identify_person(session, dana.id, "ada@northwind.example", Tier.EXEC, RATES)

    session.refresh(meeting)
    assert meeting.annualized_cost == meeting.cost * 52
    assert meeting.annualized_cost > before


def test_a_converted_meeting_reclaims_the_corrected_amount(session, dana):
    """Savings are the cost of the meeting that did not happen, so they move with it.

    Leaving this alone would leave a converted row claiming a reclaimed figure that no
    longer matches its own cost.
    """
    meeting = record(session, dana, parse_ics(ICS), status=Status.CONVERTED)
    meeting.reclaimed_savings = meeting.cost
    session.commit()

    identify_person(session, dana.id, "ada@northwind.example", Tier.EXEC, RATES)

    session.refresh(meeting)
    assert meeting.reclaimed_savings == meeting.cost


def test_identifying_a_stranger_changes_nothing(session, dana):
    record(session, dana, parse_ics(ICS))

    result = identify_person(session, dana.id, "nobody@elsewhere.example", Tier.EXEC, RATES)

    assert result.meetings_repriced == 0
    assert result.cost_delta == Decimal("0.00")


def test_one_users_directory_never_prices_anothers_meeting(session, dana):
    """A directory is one account's view of its colleagues, not a shared address book."""
    raj = User(email="raj@contoso.example", display_name="Raj")
    session.add(raj)
    session.commit()

    upsert_person(session, raj.id, "ada@northwind.example", Tier.EXEC)
    meeting = record(session, dana, parse_ics(ICS))

    assert meeting.unidentified_count == 3, "Raj placing Ada must not touch Dana's ledger"

    result = identify_person(session, raj.id, "ada@northwind.example", Tier.EXEC, RATES)
    assert result.meetings_repriced == 0


def test_placing_a_person_again_updates_rather_than_duplicates(session, dana):
    upsert_person(session, dana.id, "ada@northwind.example", Tier.IC)
    upsert_person(session, dana.id, "ADA@northwind.example", Tier.EXEC)

    people = list_people(session, dana.id)
    assert len(people) == 1
    assert people[0].tier is Tier.EXEC


def test_forgetting_a_person_leaves_the_ledger_alone(session, dana):
    """Un-knowing something is not new information about what a meeting cost."""
    person = upsert_person(session, dana.id, "ada@northwind.example", Tier.EXEC)
    meeting = record(session, dana, parse_ics(ICS))
    priced_at = meeting.cost

    assert delete_person(session, dana.id, person.id)

    session.refresh(meeting)
    assert meeting.cost == priced_at
    assert not meeting.attendees[0].is_assumed, "the seat was known when it was priced"
    assert meeting.unidentified_count == 2, "only the two who were never placed"


# ------------------------------------------------------------- what the API returns


def test_the_ledger_row_reports_how_much_of_it_is_a_guess(session, dana):
    record(session, dana, parse_ics(ICS))

    row = MeetingRead.model_validate(list_meetings(session, dana.id)[0])

    assert row.unidentified_count == 3
    assert row.attendee_emails == [
        "ada@northwind.example",
        "bo@northwind.example",
        "cy@northwind.example",
    ]


def test_a_meeting_recorded_before_seats_existed_still_reads(session, dana):
    """Existing production rows have no seats. They must read as "nothing to identify"."""
    analysis = analyze(ParsedInvite(title="Old meeting", attendee_tiers=[Tier.IC]), RATES)
    meeting = save_analysis(session, dana.id, analysis)
    meeting.attendees = []
    session.commit()

    row = MeetingRead.model_validate(meeting)

    assert row.unidentified_count == 0
    assert row.attendee_emails == []


def test_unidentified_lists_each_address_once(session, dana):
    seats = seats_for(
        ["ada@northwind.example", "ada@northwind.example", "bo@northwind.example"], {}
    )

    assert unidentified(seats) == ["ada@northwind.example", "bo@northwind.example"]


# ------------------------------------------------------------- through the API


def _api(monkeypatch):
    """A real app on a throwaway database, entered as the guest."""
    from tests.test_security import FRONTEND, _build_client

    return FRONTEND, _build_client(monkeypatch)


@pytest.fixture
def api(monkeypatch):
    from fastapi.testclient import TestClient

    frontend, app = _api(monkeypatch)
    with TestClient(app) as client:
        client.cookies.clear()
        client.headers.update({"Origin": frontend})
        assert client.post("/api/auth/guest").status_code == 200
        yield client


def _invite_payload(uid):
    import base64

    return {
        "MessageID": uid,
        "From": "ops@northwind.example",
        "Attachments": [
            {
                "Name": "invite.ics",
                "ContentType": "text/calendar",
                "Content": base64.b64encode(ICS.replace("roles-1", uid).encode()).decode(),
            }
        ],
    }


def test_an_emailed_invite_puts_its_strangers_on_the_worklist(api):
    assert api.post("/webhook/inbound-email", json=_invite_payload("api-1")).json()[
        "status"
    ] == "analyzed"

    directory = api.get("/api/people").json()

    assert directory["people"] == []
    assert [row["email"] for row in directory["unidentified"]] == [
        "ada@northwind.example",
        "bo@northwind.example",
        "cy@northwind.example",
    ]


def test_placing_people_re_prices_the_ledger_in_the_same_request(api):
    api.post("/webhook/inbound-email", json=_invite_payload("api-2"))
    before = api.get("/api/stats?period=all").json()["total_spend"]

    saved = api.put(
        "/api/people",
        json={
            "people": [
                {"email": "ada@northwind.example", "tier": "exec", "display_name": "Ada"},
                {"email": "bo@northwind.example", "tier": "manager"},
            ]
        },
    ).json()

    assert saved["repricing"]["meetings_repriced"] == 1
    assert saved["repricing"]["seats_corrected"] == 2
    assert Decimal(saved["repricing"]["cost_delta"]) > 0
    assert [row["email"] for row in saved["directory"]["unidentified"]] == [
        "cy@northwind.example"
    ]

    after = api.get("/api/stats?period=all").json()["total_spend"]
    assert Decimal(after) > Decimal(before), "the dashboard has to move with the ledger"


def test_your_own_role_is_the_entry_for_your_own_address(api):
    me = api.get("/api/auth/me").json()

    saved = api.put(
        "/api/people", json={"people": [{"email": me["email"], "tier": "manager"}]}
    ).json()

    assert saved["directory"]["me"]["tier"] == "manager"
    assert saved["directory"]["me"]["is_self"] is True
    assert saved["directory"]["self_email"] == me["email"]


def test_an_unreadable_address_is_refused_rather_than_stored(api):
    response = api.put("/api/people", json={"people": [{"email": "not-an-address", "tier": "ic"}]})

    assert response.status_code == 422
    assert api.get("/api/people").json()["people"] == []


def test_forgetting_someone_elses_entry_is_a_404(api):
    assert api.delete("/api/people/9999").status_code == 404


def test_resolving_an_invite_with_no_addresses_leaves_the_room_intact():
    """The regression the seed caught: Door B has head counts and no addresses.

    Resolving `[]` into seats replaced a room of fifteen with a room of nobody, so every
    count-only meeting silently cost zero and the ledger totals collapsed. Nothing raised
    — the figures were simply wrong.
    """
    invite = ParsedInvite(title="Sprint planning", attendee_tiers=[Tier.IC, Tier.EXEC])

    resolved = resolved_invite(invite, {"ada@northwind.example": Tier.MANAGER})

    assert resolved.attendee_tiers == [Tier.IC, Tier.EXEC]
    assert resolved.attendee_count == 2

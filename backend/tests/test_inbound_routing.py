"""Whose ledger does an emailed invite land on?

Door A used to put every invite on the shared guest. Getting attribution wrong is not a
cosmetic bug — it puts one person's meeting spend on another person's budget — so these
are correctness tests. The freemail case is the sharpest: without it, a user who claims
`gmail.com` captures every gmail organizer's invites.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data.db import Base
from app.data.inbound_routes import get_or_create_route, invite_address_for, set_domain
from app.data.models import User
from app.schemas.invite import ParsedInvite
from app.services.ics_adapter import parse_ics
from app.services.inbound_routing import (
    DomainNotClaimable,
    claimable_domain,
    domain_of,
    normalize_address,
    resolve_owner,
    strip_subaddress,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        s.add(User(email="guest@shouldbe.local", display_name="Guest", is_guest=True))
        s.add(User(email="dana@northwind.example", display_name="Dana"))
        s.add(User(email="raj@contoso.example", display_name="Raj"))
        s.commit()
        yield s


def user_named(session, name):
    return session.query(User).filter(User.display_name == name).one()


def invite_from(organizer):
    return ParsedInvite(title="Sync", organizer_email=organizer)


# ------------------------------------------------------- address normalization


def test_normalize_strips_mailto_case_and_display_names():
    assert normalize_address("MAILTO:Dana@Northwind.Example") == "dana@northwind.example"
    assert normalize_address("Dana <dana@northwind.example>") == "dana@northwind.example"
    assert normalize_address("not-an-address") == ""
    assert normalize_address(None) == ""


def test_strip_subaddress_removes_the_routing_tag():
    assert strip_subaddress("ledger+ab12cd@invite.example") == "ledger@invite.example"
    assert strip_subaddress("ledger@invite.example") == "ledger@invite.example"


def test_domain_of_reads_the_host():
    assert domain_of("dana@northwind.example") == "northwind.example"
    assert domain_of("garbage") == ""


# ------------------------------------------------------------ domain claiming


def test_a_public_mailbox_provider_cannot_be_claimed():
    # The whole point of the guard: claiming gmail.com would capture every gmail
    # organizer's invites for whoever claimed it first.
    for provider in ("gmail.com", "outlook.com", "yahoo.com", "icloud.com", "proton.me"):
        with pytest.raises(DomainNotClaimable):
            claimable_domain(provider)


def test_a_company_domain_is_claimable_and_normalized():
    assert claimable_domain("  NorthWind.Example  ") == "northwind.example"
    assert claimable_domain("@northwind.example") == "northwind.example"
    # Pasting a whole address into the field is a reasonable thing to do.
    assert claimable_domain("dana@northwind.example") == "northwind.example"


def test_nonsense_is_refused():
    for bad in ("", "   ", "northwind", "north wind.example"):
        with pytest.raises(DomainNotClaimable):
            claimable_domain(bad)


def test_a_domain_cannot_be_claimed_twice(session):
    dana = user_named(session, "Dana")
    raj = user_named(session, "Raj")
    set_domain(session, dana.id, "northwind.example")

    with pytest.raises(ValueError):
        set_domain(session, raj.id, "northwind.example")


# ---------------------------------------------------- the four routing layers


def test_layer_1_the_routing_token_wins(session):
    dana = user_named(session, "Dana")
    raj = user_named(session, "Raj")
    token = get_or_create_route(session, dana.id).token

    # Organizer is Raj, but the invite went to Dana's tagged address. The explicit signal
    # is the deliberate one, so it wins.
    owner = resolve_owner(session, {"MailboxHash": token}, invite_from(raj.email))

    assert owner.id == dana.id


def test_layer_2_the_organizer_address_matches_a_user(session):
    dana = user_named(session, "Dana")

    owner = resolve_owner(session, {}, invite_from("DANA@northwind.example"))

    assert owner.id == dana.id


def test_layer_3_a_claimed_domain_catches_a_colleague(session):
    dana = user_named(session, "Dana")
    set_domain(session, dana.id, "northwind.example")

    # Nobody has ever signed in as this person; the domain claim is what attributes them.
    owner = resolve_owner(session, {}, invite_from("stranger@northwind.example"))

    assert owner.id == dana.id


def test_layer_4_an_unknown_organizer_falls_back_to_guest(session):
    owner = resolve_owner(session, {}, invite_from("nobody@unrelated.example"))

    assert owner.is_guest is True


def test_an_unknown_token_does_not_strand_the_invite(session):
    # A stale or mistyped tag must not lose the meeting; it falls through to the next layer.
    dana = user_named(session, "Dana")

    owner = resolve_owner(session, {"MailboxHash": "deadbeef"}, invite_from(dana.email))

    assert owner.id == dana.id


def test_an_invite_with_no_organizer_falls_back_to_guest(session):
    assert resolve_owner(session, {}, invite_from("")).is_guest is True


# ------------------------------------------------------------ the invite address


def test_the_invite_address_carries_the_token(monkeypatch):
    monkeypatch.setenv("SHOULDBE_INBOX", "ledger@invite.example.com")

    assert invite_address_for("ab12cd") == "ledger+ab12cd@invite.example.com"


def test_an_already_tagged_inbox_is_not_double_tagged(monkeypatch):
    monkeypatch.setenv("SHOULDBE_INBOX", "ledger+ignoreme@invite.example.com")

    assert invite_address_for("ab12cd") == "ledger+ab12cd@invite.example.com"


# ------------------------------------------- regression: ShouldBe billing itself


def test_the_plus_addressed_shouldbe_inbox_is_not_billed_as_an_attendee():
    """The bug plus-addressing would otherwise introduce.

    The inbox is excluded from attendee costs by comparing addresses. Once invites arrive
    tagged, an exact comparison stops matching, and ShouldBe silently bills itself as an
    attendee on every meeting it is invited to — inflating every Door A cost.
    """
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//T//EN", "BEGIN:VEVENT",
        "UID:tagged-1",
        "DTSTART:20260901T150000Z", "DTEND:20260901T160000Z",
        "SUMMARY:Tagged invite",
        "ORGANIZER:mailto:dana@northwind.example",
        "ATTENDEE:mailto:dana@northwind.example",
        "ATTENDEE:mailto:sam@northwind.example",
        "ATTENDEE:mailto:ledger+ab12cd@invite.example.com",
        "END:VEVENT", "END:VCALENDAR",
    ])

    invite = parse_ics(ics, ("ledger@invite.example.com",))

    assert len(invite.attendee_tiers) == 2

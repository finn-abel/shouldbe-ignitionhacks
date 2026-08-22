"""Whose ledger does an emailed invite land on? (doc 2 §5.2's known edge.)

Door A used to attribute every invite to the shared guest, because an inbound email
carries no session cookie. This module resolves an owner instead, trying four signals in
descending order of how deliberate they are:

1. **Routing token** — the organizer invited `ledger+ab12cd@…`, so Postmark hands us
   `ab12cd` in `MailboxHash`. Explicit: someone went and copied their address.
2. **Exact organizer match** — the invite's ORGANIZER *is* a ShouldBe user's sign-in
   address. This is the one that needs no setup at all: a Google user's email already is
   their work address, so inviting ShouldBe from their own calendar just works.
3. **Claimed domain** — the organizer's domain has been claimed by a user. Zero-effort for
   everyone else at that company, and the reason `PUBLIC_EMAIL_DOMAINS` exists below.
4. **Guest** — the shared demo ledger, unchanged. Never let an invite fall on the floor.

Nothing here is a security boundary: a From address is spoofable and so is a `+tag` anyone
has seen. It is attribution for a demo ledger, not authorization.
"""

import logging

from sqlalchemy.orm import Session

from app.data.inbound_routes import find_by_domain, find_by_token
from app.data.models import User
from app.data.users import get_or_create_guest
from app.schemas.invite import ParsedInvite

logger = logging.getLogger(__name__)

# A domain claim says "invites from anyone here are mine". That is only ever true of a
# domain one organisation actually controls. Letting someone claim `gmail.com` would hand
# them every gmail organizer's invites, so these are refused outright.
PUBLIC_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "yahoo.co.uk",
        "ymail.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "aol.com",
        "gmx.com",
        "gmx.net",
        "mail.com",
        "zoho.com",
        "proton.me",
        "protonmail.com",
        "pm.me",
        "yandex.com",
        "fastmail.com",
        "hey.com",
    }
)


class DomainNotClaimable(Exception):
    """The domain is a public mailbox provider, malformed, or already spoken for."""


def normalize_address(address: str | None) -> str:
    """Lowercase, `mailto:`-free, whitespace-free. `""` for anything unusable."""
    if not address:
        return ""
    cleaned = address.strip().lower()
    if cleaned.startswith("mailto:"):
        cleaned = cleaned[len("mailto:") :]
    # Some clients send `Display Name <addr@host>`.
    if "<" in cleaned and ">" in cleaned:
        cleaned = cleaned[cleaned.index("<") + 1 : cleaned.index(">")].strip()
    return cleaned if "@" in cleaned else ""


def strip_subaddress(address: str) -> str:
    """`ledger+ab12cd@host` -> `ledger@host`.

    Door A's own inbox is excluded from attendee billing by comparing addresses. Once
    invites arrive plus-addressed, an exact comparison stops matching and ShouldBe starts
    billing *itself* as an attendee on every meeting it is invited to — silently inflating
    every Door A cost. This is what keeps that comparison honest.
    """
    normalized = normalize_address(address)
    if not normalized:
        return ""
    local, _, host = normalized.partition("@")
    local, _, _tag = local.partition("+")
    return f"{local}@{host}" if local else ""


def domain_of(address: str | None) -> str:
    """The host part of an address, lowercased. `""` when there isn't one."""
    normalized = normalize_address(address)
    return normalized.rpartition("@")[2] if normalized else ""


def claimable_domain(raw: str) -> str:
    """Validate and normalize a domain a user wants to claim.

    Raises `DomainNotClaimable` rather than returning a sentinel: refusing a claim is a
    422 the user needs to read, not a silent no-op.
    """
    candidate = (raw or "").strip().lower().lstrip("@")
    # Tolerate someone pasting their whole email address into the field.
    if "@" in candidate:
        candidate = candidate.rpartition("@")[2]
    candidate = candidate.rstrip(".")

    if not candidate or "." not in candidate or " " in candidate:
        raise DomainNotClaimable(f"{raw!r} is not a domain.")

    if candidate in PUBLIC_EMAIL_DOMAINS:
        raise DomainNotClaimable(
            f"{candidate} is a public email provider, so it cannot belong to one team. "
            "Use your company domain, or use your personal invite address instead."
        )

    return candidate


def resolve_owner(session: Session, payload: dict, invite: ParsedInvite) -> User:
    """The user an inbound invite belongs to. Always returns someone."""
    token = (payload.get("MailboxHash") or "").strip().lower()
    if token:
        route = find_by_token(session, token)
        if route is not None:
            logger.info("Invite routed to user %s by token.", route.user_id)
            return route.user

    organizer = normalize_address(invite.organizer_email)
    if organizer:
        user = session.query(User).filter(User.email == organizer).one_or_none()
        if user is not None:
            logger.info("Invite routed to user %s by organizer address.", user.id)
            return user

        route = find_by_domain(session, domain_of(organizer))
        if route is not None:
            logger.info("Invite routed to user %s by claimed domain.", route.user_id)
            return route.user

    logger.info("Invite from %r matched no user; attributing to guest.", organizer)
    return get_or_create_guest(session)

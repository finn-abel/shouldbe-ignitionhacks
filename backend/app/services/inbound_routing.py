"""Whose ledger does an emailed invite land on?

Inbound invites used to land on the shared guest, because an inbound email
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
from typing import NamedTuple

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


class DomainNotOwned(Exception):
    """The claimant has not shown they belong to the domain they are claiming."""


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

    ShouldBe's own inbox is excluded from attendee billing by comparing addresses. Once
    invites arrive plus-addressed, an exact comparison stops matching and ShouldBe starts
    billing *itself* as an attendee on every meeting it is invited to — silently inflating
    every inbound-invite cost. This is what keeps that comparison honest.
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


def assert_claimant_owns(user: User, domain: str) -> None:
    """Refuse a domain claim from someone who has not shown they belong to it.

    Claiming a domain routes every invite organized from it onto the claimant's ledger, so
    an unverified claim is a cross-tenant read: `acme.com` would hand the claimant Acme's
    meeting titles, organizer addresses and head counts. `claimable_domain` only rules out
    public mailbox providers, which stops the worst case and nothing else — it was still
    first-come-first-served on every company domain in existence.

    The bar is the claimant's own sign-in address, which Google verified before it ever
    reached us. That is not as strong as a DNS TXT record (a proper domain-verification
    flow is the real answer), but it is the difference between "prove you have an address
    here" and "type any domain you like".
    """
    if user.is_guest:
        # The guest row is shared by every visitor, so a claim on it is a claim by nobody.
        # The seeded demo domain is set server-side in seed.py, which does not come here.
        raise DomainNotOwned(
            "The shared guest account cannot claim a domain. Sign in with Google to "
            "claim your company domain, or use your personal invite address instead."
        )

    own_domain = domain_of(user.email)
    if not own_domain or own_domain != domain:
        raise DomainNotOwned(
            f"You can only claim the domain of your own sign-in address. Sign in with an "
            f"address at {domain} to claim it."
        )


# How an invite was attributed. The webhook needs this and not just the user, because
# whether ShouldBe may *reply* depends on which signal matched — see `reply_recipient`.
TOKEN_MATCH = "token"
ORGANIZER_MATCH = "organizer"
DOMAIN_MATCH = "claimed-domain"
NO_MATCH = "guest-fallback"


class Attribution(NamedTuple):
    """Who the invite belongs to, and which of the four layers said so."""

    user: User
    how: str
    # Set only for DOMAIN_MATCH: the domain that was actually claimed. Carried rather than
    # re-derived, because the claimed domain and the claimant's email domain are not always
    # the same row — seed.py sets one server-side without going through the claim endpoint.
    matched_domain: str = ""

    @property
    def is_identified(self) -> bool:
        """True when a real signal matched, as opposed to falling through to the guest."""
        return self.how != NO_MATCH


def resolve_attribution(session: Session, payload: dict, invite: ParsedInvite) -> Attribution:
    """The user an inbound invite belongs to, and how that was decided."""
    token = (payload.get("MailboxHash") or "").strip().lower()
    if token:
        route = find_by_token(session, token)
        if route is not None:
            logger.info("Invite routed to user %s by token.", route.user_id)
            return Attribution(route.user, TOKEN_MATCH)

    organizer = normalize_address(invite.organizer_email)
    if organizer:
        user = session.query(User).filter(User.email == organizer).one_or_none()
        if user is not None:
            logger.info("Invite routed to user %s by organizer address.", user.id)
            return Attribution(user, ORGANIZER_MATCH)

        route = find_by_domain(session, domain_of(organizer))
        if route is not None:
            logger.info("Invite routed to user %s by claimed domain.", route.user_id)
            return Attribution(route.user, DOMAIN_MATCH, route.domain or "")

    logger.info("Invite from %r matched no user; attributing to guest.", organizer)
    return Attribution(get_or_create_guest(session), NO_MATCH)


def resolve_owner(session: Session, payload: dict, invite: ParsedInvite) -> User:
    """The user an inbound invite belongs to. Always returns someone."""
    return resolve_attribution(session, payload, invite).user


def reply_recipient(attribution: Attribution, invite: ParsedInvite) -> str:
    """Where the reply may be sent, or "" for "do not reply at all".

    The reply used to go to whatever address the .ics named as ORGANIZER. That field is
    written by whoever sent the invite and is not checked against anything, so anyone who
    could email ShouldBe's public inbox could make it send mail to a third party of their
    choosing, from a domain ShouldBe has verified, with a subject line they controlled.
    The inbox address is handed to every visitor by `GET /api/inbound-route`, so "could
    email it" means anyone. That is an open relay wearing the sender's own reputation.

    So the recipient is no longer taken from the invite. It is one of exactly two things:

    - a registered user's own sign-in address, which Google verified; or
    - an address on a domain a registered user has proven they hold (see
      `assert_claimant_owns`), which is the only case where replying to someone who is
      not themselves a user is something a user actually asked for.

    An invite that matched nothing is still costed and recorded on the guest ledger. It
    just does not get an email, because there is nobody it could safely be sent to.
    """
    if not attribution.is_identified:
        return ""

    if attribution.how in (TOKEN_MATCH, ORGANIZER_MATCH):
        # The account this landed on. Never an address supplied by the invite.
        return normalize_address(attribution.user.email)

    # DOMAIN_MATCH: the organizer, but only inside the domain that was actually claimed.
    organizer = normalize_address(invite.organizer_email)
    allowed = (attribution.matched_domain or "").strip().lower()
    if organizer and allowed and domain_of(organizer) == allowed:
        return organizer

    logger.warning("Declining to reply: organizer %r is outside the claimed domain.", organizer)
    return ""

"""Inbound route persistence — one row per user (see `app.services.inbound_routing`).

Rows are created lazily rather than in `_with_starting_config`, so a database that already
has users gains routing without the `rm shouldbe.db` re-seed a new *column* would force.
`create_all` adds missing tables; it does not add missing columns.
"""

import os
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data.models import InboundRoute, User

# 16 hex characters (64 bits). This was 8, which is 32 bits — enumerable in hours by
# anything that can reach the webhook, and the webhook is only as closed as its shared
# secret. Still short enough to read off a slide, and existing shorter tokens keep working
# because lookup is by value.
TOKEN_BYTES = 8

DEFAULT_INBOX = "ledger@example.invalid"


def _new_token() -> str:
    return secrets.token_hex(TOKEN_BYTES)


def get_or_create_route(session: Session, user_id: int) -> InboundRoute:
    """This user's route, minting the token on first use."""
    route = session.scalar(select(InboundRoute).where(InboundRoute.user_id == user_id))
    if route is not None:
        return route

    route = InboundRoute(user_id=user_id, token=_new_token())
    session.add(route)
    try:
        session.commit()
    except IntegrityError:
        # Two requests for the same brand-new user, or an astronomically unlucky token
        # collision. Either way the winner's row is the answer.
        session.rollback()
        existing = session.scalar(select(InboundRoute).where(InboundRoute.user_id == user_id))
        if existing is None:
            raise
        return existing

    session.refresh(route)
    return route


def find_by_token(session: Session, token: str) -> InboundRoute | None:
    if not token:
        return None
    return session.scalar(select(InboundRoute).where(InboundRoute.token == token.lower()))


def find_by_domain(session: Session, domain: str) -> InboundRoute | None:
    if not domain:
        return None
    return session.scalar(select(InboundRoute).where(InboundRoute.domain == domain.lower()))


def set_domain(session: Session, user_id: int, domain: str | None) -> InboundRoute:
    """Claim (or clear, with None) this user's domain.

    Raises `ValueError` when another user already holds it — the unique constraint is the
    real guarantee, the pre-check is only there to give a better message.
    """
    route = get_or_create_route(session, user_id)

    if domain is not None:
        holder = find_by_domain(session, domain)
        if holder is not None and holder.user_id != user_id:
            raise ValueError(f"{domain} has already been claimed by another account.")

    route.domain = domain
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ValueError(f"{domain} has already been claimed by another account.") from None

    session.refresh(route)
    return route


def invite_address_for(token: str) -> str:
    """The plus-addressed address to hand the user, e.g. `ledger+ab12cd@invite.example`.

    Falls back to a clearly invalid placeholder when `SHOULDBE_INBOX` is unset, so the UI
    can say "email is not configured yet" rather than showing a plausible-looking address
    that silently goes nowhere.
    """
    inbox = (os.getenv("SHOULDBE_INBOX") or "").strip().lower() or DEFAULT_INBOX
    local, _, host = inbox.partition("@")
    if not local or not host:
        return DEFAULT_INBOX
    # Guard against someone setting SHOULDBE_INBOX to an already-tagged address.
    local = local.partition("+")[0]
    return f"{local}+{token}@{host}"


def user_for_token(session: Session, token: str) -> User | None:
    route = find_by_token(session, token)
    return route.user if route else None

"""The user's email door (doc 2 §5.2). Thin: parse, delegate, return.

`GET` hands back the address to invite ShouldBe from. `PUT` claims a company domain so
colleagues are attributed without doing anything at all.
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.data.db import get_session
from app.data.inbound_routes import get_or_create_route, invite_address_for, set_domain
from app.data.models import User
from app.data.outbox import list_for_user
from app.routes.auth import acting_user
from app.schemas.api import InboundRouteRead, InboundRouteUpdate, OutboxRead
from app.services.inbound_routing import (
    DomainNotClaimable,
    DomainNotOwned,
    assert_claimant_owns,
    claimable_domain,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["inbound"])


def _to_read(route) -> InboundRouteRead:
    return InboundRouteRead(
        invite_address=invite_address_for(route.token),
        token=route.token,
        domain=route.domain,
        email_configured=bool((os.getenv("SHOULDBE_INBOX") or "").strip()),
    )


@router.get("/inbound-route", response_model=InboundRouteRead)
def read_route(
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    return _to_read(get_or_create_route(session, user.id))


@router.put("/inbound-route", response_model=InboundRouteRead)
def write_route(
    update: InboundRouteUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    """Claim a domain, or send null to clear it."""
    domain = None
    if update.domain is not None and update.domain.strip():
        try:
            domain = claimable_domain(update.domain)
        except DomainNotClaimable as refusal:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(refusal)) from refusal

        # Claiming is an authorization decision, not just a validation one: it decides
        # whose ledger other people's invites land on.
        try:
            assert_claimant_owns(user, domain)
        except DomainNotOwned as refusal:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(refusal)) from refusal

    try:
        route = set_domain(session, user.id, domain)
    except ValueError as taken:
        raise HTTPException(status.HTTP_409_CONFLICT, str(taken)) from taken

    return _to_read(route)


@router.get("/outbox", response_model=list[OutboxRead])
def read_outbox(
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    """This user's replies and their delivery state.

    Small, but it is the difference between "the email never arrived" being a mystery and
    being one request. QUEUED with a `last_error` means it is still being retried; FAILED
    means it never will be.
    """
    return list_for_user(session, user.id)

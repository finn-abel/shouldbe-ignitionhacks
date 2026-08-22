"""Door A — Postmark inbound email (doc 2 §5.2). Thin: parse, delegate, return.

The only asymmetry with Doors B and C is the adapter. Once the .ics is a `ParsedInvite`
this hands it to the same `analyze()` every other door uses.
"""

import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data.db import get_session
from app.data.meetings import find_by_source_key, save_analysis
from app.data.tiers import get_tier_rates
from app.data.users import get_or_create_guest
from app.services.email import send_reply
from app.services.ics_adapter import (
    NoInviteFound,
    find_ics_text,
    parse_ics,
    source_key_for,
)
from app.services.pipeline import analyze

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


def _verify_caller(request: Request) -> None:
    """Shared secret, when one is configured.

    This endpoint is public and it sends email, so an open one is a spam relay. Postmark
    can put the secret in the webhook URL as `?token=`, or send it as HTTP Basic auth.
    Unset means unverified — fine locally, and loudly logged so it is not forgotten.
    """
    expected = os.getenv("POSTMARK_WEBHOOK_SECRET")
    if not expected:
        logger.warning("POSTMARK_WEBHOOK_SECRET is unset; the inbound webhook is unverified.")
        return

    supplied = request.query_params.get("token")
    if supplied is None:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            import base64

            try:
                supplied = base64.b64decode(header[6:]).decode().split(":", 1)[-1]
            except (ValueError, UnicodeDecodeError):
                supplied = None

    if supplied != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad webhook token.")


def _shouldbe_addresses(payload: dict) -> tuple[str, ...]:
    """Addresses that are in the room but are not attending: ShouldBe's own inboxes."""
    candidates = [
        os.getenv("SHOULDBE_INBOX", ""),
        payload.get("OriginalRecipient") or "",
        payload.get("To") or "",
    ]
    return tuple(address.strip().lower() for address in candidates if address and "@" in address)


@router.post("/inbound-email")
def inbound_email(
    payload: dict,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Receive an invite, analyze it, record it, and reply to the organizer.

    Postmark redelivers an inbound message up to six times over ~51 minutes — on a
    non-2xx, on a network failure, and on a timeout where this endpoint did the work but
    answered too slowly. So this handler is idempotent by construction: the ledger row is
    keyed on the invite, and the reply is only sent when a row was actually created.
    Without that, one invite could put six identical meetings on the books and send six
    identical emails to the organizer.
    """
    _verify_caller(request)

    try:
        ics_text = find_ics_text(payload)
        invite = parse_ics(ics_text, _shouldbe_addresses(payload))
    except NoInviteFound as failure:
        # 200, not an error: there is nothing to retry about an email with no invite in
        # it, and a non-2xx would have Postmark redelivering it indefinitely.
        logger.info("Ignoring an inbound email: %s", failure)
        return {"status": "ignored", "reason": str(failure)}

    # Email-door meetings are attributed to the shared guest (doc 2 §5.2's known edge).
    owner = get_or_create_guest(session)
    source_key = source_key_for(payload, ics_text)

    if source_key:
        already = find_by_source_key(session, owner.id, source_key)
        if already is not None:
            logger.info("Invite %s was already analyzed; not replying again.", source_key)
            return {"status": "duplicate", "meeting_id": already.id, "reply": "skipped"}

    analysis = analyze(invite, get_tier_rates(session, owner.id))

    try:
        meeting = save_analysis(session, owner.id, analysis, source_key)
    except IntegrityError:
        # A retry that arrived while the first delivery was still being scored. The
        # unique constraint is the real guarantee; the lookup above is just the fast path.
        session.rollback()
        already = find_by_source_key(session, owner.id, source_key) if source_key else None
        logger.info("Concurrent redelivery of invite %s; kept the first.", source_key)
        return {
            "status": "duplicate",
            "meeting_id": already.id if already else None,
            "reply": "skipped",
        }

    # Reply after responding. Scoring plus an SMTP round trip is exactly the latency that
    # trips Postmark's timeout and starts the redelivery loop this handler defends against.
    background.add_task(send_reply, analysis, invite.organizer_email)

    return {"status": "analyzed", "meeting_id": meeting.id, "reply": "queued"}

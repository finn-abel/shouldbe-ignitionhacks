"""Outbound email (doc 2 §5.2).

Composing the reply is a pure function; sending it is one JSON POST. Two rules from
doc 1 §59-61 shape what goes in the message:

- **Aggregate figures only.** The reply names what the meeting costs in total. It never
  names a person, a role rate, or anyone's share.
- **The drafted alternative carries no price at all.** It is about the meeting's topic,
  and it is what the organizer forwards on — so nothing about money leaves with it.

Sending is one JSON POST behind a two-provider seam. Postmark owns *inbound* — the MX on
the invite subdomain — and that is unaffected by any of this. Outbound is separate, and
switchable, because a new Postmark account refuses every recipient outside your own
verified domains until a human approves it. Resend gates the same capability on domain
verification alone, which is DNS and therefore minutes, so it is what makes replies reach
the organizer who actually invited ShouldBe rather than only the operator.
"""

import logging
import os

import httpx

from app.enums import Verdict
from app.schemas.api import MeetingAnalysis
from app.services.costing import billable_minutes, is_clamped

logger = logging.getLogger(__name__)

POSTMARK_SEND_URL = "https://api.postmarkapp.com/email"
RESEND_SEND_URL = "https://api.resend.com/emails"
# Kept short: the reply now runs after the webhook has already responded, but a
# hung connection should still release the worker promptly.
SEND_TIMEOUT_SECONDS = 8.0
# How many queued replies one drain pass attempts.
DRAIN_BATCH_SIZE = 20


def _money(amount) -> str:
    return f"${amount:,.2f}"


def _attendees(count: int) -> str:
    """"1 attendee" / "4 attendees". This email is the product's visible output."""
    return f"{count} attendee" if count == 1 else f"{count} attendees"


def compose_reply(analysis: MeetingAnalysis) -> tuple[str, str]:
    """The subject and body sent back to the organizer. Pure — no I/O, no secrets."""
    flagged = analysis.verdict is Verdict.EMAIL
    headline = "could be an email" if flagged else "is worth the room"
    subject = f"{analysis.title} — {headline} ({analysis.score}/10)"

    charged = billable_minutes(analysis.duration_minutes)
    lines = [
        f"You invited ShouldBe to \"{analysis.title}\".",
        "",
        f"Necessity score: {analysis.score}/10 — {headline}.",
        f"This occurrence costs {_money(analysis.cost)} "
        f"across {_attendees(analysis.attendee_count)} for {charged} minutes.",
    ]

    if is_clamped(analysis.duration_minutes):
        # Otherwise the figure looks wrong to anyone who checks it against the invite.
        lines.append(
            f"(It is booked for {analysis.duration_minutes} minutes, but no single meeting "
            f"is charged for more than {charged}.)"
        )

    if analysis.annualized_cost is not None:
        lines.append(
            f"It repeats {(analysis.recurrence_freq or '').lower()}, "
            f"so it runs at {_money(analysis.annualized_cost)} a year."
        )

    lines += ["", analysis.reasoning]

    if flagged and analysis.alternative_email:
        lines += [
            "",
            "-- Here is the email that could replace it "
            "----------------------------------",
            "",
            analysis.alternative_email,
            "",
            "-------------------------------------------------------"
            "---------------------",
        ]

    lines += [
        "",
        "Costed from blended role-tier rates. No individual's rate or salary is used, "
        "stored, or shown.",
    ]
    return subject, "\n".join(lines)


class SendOutcome:
    """Why a send did not happen — the drain needs the *reason*, not just False.

    `permanent` decides whether a queued reply is retried or buried. Getting it wrong in
    the optimistic direction (calling a temporary failure permanent) is what would lose a
    reply during Postmark's account-approval window, so anything not clearly a rejected
    recipient is treated as temporary.
    """

    def __init__(self, ok: bool, error: str = "", permanent: bool = False):
        self.ok = ok
        self.error = error
        self.permanent = permanent


# Postmark API error codes that mean "this recipient will never work", as opposed to
# "not yet". 300 is a malformed address; 406 is an inactive/suppressed recipient.
# https://postmarkapp.com/developer/api/overview#error-codes
PERMANENT_ERROR_CODES = frozenset({300, 406})


def _outbound_provider() -> str:
    """Which service sends the reply. Postmark still owns inbound either way."""
    raw = (os.getenv("EMAIL_PROVIDER") or "").strip().lower()
    if raw in {"resend", "postmark"}:
        return raw
    if raw:
        raise RuntimeError(f"Unsupported EMAIL_PROVIDER {raw!r}. Use 'resend' or 'postmark'.")
    # Unset: infer from whichever is configured, preferring Resend because it can reach
    # arbitrary organizers without waiting on a manual account review.
    if os.getenv("RESEND_API_KEY"):
        return "resend"
    return "postmark"


def _sender() -> str:
    """The From address. `RESEND_FROM` wins for Resend, else the shared POSTMARK_FROM."""
    if _outbound_provider() == "resend":
        return (os.getenv("RESEND_FROM") or os.getenv("POSTMARK_FROM") or "").strip()
    return (os.getenv("POSTMARK_FROM") or "").strip()


def _send_via_postmark(sender, to_email, subject, text_body) -> SendOutcome:
    token = os.getenv("POSTMARK_TOKEN")
    if not token:
        return SendOutcome(False, "POSTMARK_TOKEN is unset.", permanent=False)

    message = {
        "From": sender,
        "To": to_email,
        "Subject": subject,
        "TextBody": text_body,
        "MessageStream": os.getenv("POSTMARK_STREAM", "outbound"),
    }
    try:
        response = httpx.post(
            POSTMARK_SEND_URL,
            headers={"X-Postmark-Server-Token": token, "Accept": "application/json"},
            json=message,
            timeout=SEND_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as failure:
        return SendOutcome(False, f"{type(failure).__name__}: {failure}", permanent=False)

    if response.status_code == 200:
        return SendOutcome(True)

    detail, code = response.text, None
    try:
        body = response.json()
        code = body.get("ErrorCode")
        detail = body.get("Message") or detail
    except ValueError:
        pass

    # 422 with an unrecognised code is most often "account pending approval" or "sender
    # signature not confirmed" — both resolve without anyone touching this reply.
    permanent = code in PERMANENT_ERROR_CODES
    return SendOutcome(False, f"HTTP {response.status_code} (ErrorCode {code}): {detail}", permanent)


def _send_via_resend(sender, to_email, subject, text_body, idempotency_key) -> SendOutcome:
    key = os.getenv("RESEND_API_KEY")
    if not key:
        return SendOutcome(False, "RESEND_API_KEY is unset.", permanent=False)

    request_headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if idempotency_key:
        # A drain that times out after Resend already accepted the message would otherwise
        # send it twice on the next pass. Resend honours this key for 24 hours.
        request_headers["Idempotency-Key"] = idempotency_key

    message = {"from": sender, "to": [to_email], "subject": subject, "text": text_body}

    try:
        response = httpx.post(
            RESEND_SEND_URL,
            headers=request_headers,
            json=message,
            timeout=SEND_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as failure:
        return SendOutcome(False, f"{type(failure).__name__}: {failure}", permanent=False)

    if response.status_code in (200, 201):
        return SendOutcome(True)

    detail, name = response.text, ""
    try:
        body = response.json()
        name = (body.get("name") or "").strip()
        detail = body.get("message") or detail
    except ValueError:
        pass

    # Only a malformed request is hopeless. An unverified domain, a missing key, and a
    # rate limit are all things the operator fixes while the reply waits.
    permanent = name == "validation_error" and response.status_code == 422
    return SendOutcome(False, f"HTTP {response.status_code} ({name or 'error'}): {detail}", permanent)


def _post_to_provider(
    to_email: str, subject: str, text_body: str, idempotency_key: str = ""
) -> SendOutcome:
    """Send one message. Never raises; classifies the failure instead."""
    try:
        provider = _outbound_provider()
    except RuntimeError as misconfigured:
        return SendOutcome(False, str(misconfigured), permanent=False)

    sender = _sender()
    if not sender:
        return SendOutcome(
            False,
            "Outbound email is not configured (RESEND_FROM / POSTMARK_FROM are unset).",
            permanent=False,
        )

    if not to_email:
        return SendOutcome(False, "No recipient address.", permanent=True)

    if provider == "resend":
        return _send_via_resend(sender, to_email, subject, text_body, idempotency_key)
    return _send_via_postmark(sender, to_email, subject, text_body)


def drain_outbox(session, limit: int = DRAIN_BATCH_SIZE) -> int:
    """Try every queued reply. Returns how many were accepted by Postmark.

    Safe to call from anywhere and at any time: each row is committed independently, so a
    crash mid-batch loses nothing, and a row that is already SENT is never selected again.
    """
    from app.data.outbox import claim_queued, mark_attempt_failed, mark_sent

    pending = claim_queued(session, limit)
    if not pending:
        return 0

    sent = 0
    for reply in pending:
        outcome = _post_to_provider(
            reply.to_email,
            reply.subject,
            reply.text_body,
            # Stable per reply, so a drain that times out after the provider already
            # accepted the message does not send it a second time on the next pass.
            idempotency_key=f"shouldbe-outbox-{reply.id}",
        )
        if outcome.ok:
            mark_sent(session, reply)
            sent += 1
            logger.info("Outbox %s delivered to %s.", reply.id, reply.to_email)
            continue

        mark_attempt_failed(session, reply, outcome.error, outcome.permanent)
        logger.warning(
            "Outbox %s to %s not sent (attempt %s, %s): %s",
            reply.id,
            reply.to_email,
            reply.attempts,
            "permanent" if outcome.permanent else "will retry",
            outcome.error,
        )

    return sent


def drain_outbox_in_new_session(limit: int = DRAIN_BATCH_SIZE) -> int:
    """Drain with a session of its own — for background tasks and the startup sweep,
    which run after the request that created them has closed its session."""
    from app.data.db import SessionLocal

    with SessionLocal() as session:
        return drain_outbox(session, limit)

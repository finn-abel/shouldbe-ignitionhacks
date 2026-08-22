"""Outbound email via Postmark (doc 2 §5.2).

Composing the reply is a pure function; sending it is one JSON POST. Two rules from
doc 1 §59-61 shape what goes in the message:

- **Aggregate figures only.** The reply names what the meeting costs in total. It never
  names a person, a role rate, or anyone's share.
- **The drafted alternative carries no price at all.** It is about the meeting's topic,
  and it is what the organizer forwards on — so nothing about money leaves with it.
"""

import logging
import os

import httpx

from app.enums import Verdict
from app.schemas.api import MeetingAnalysis
from app.services.costing import billable_minutes, is_clamped

logger = logging.getLogger(__name__)

POSTMARK_SEND_URL = "https://api.postmarkapp.com/email"
# Kept short: the reply now runs after the webhook has already responded, but a
# hung connection should still release the worker promptly.
SEND_TIMEOUT_SECONDS = 8.0


def _money(amount) -> str:
    return f"${amount:,.2f}"


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
        f"across {analysis.attendee_count} attendees for {charged} minutes.",
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


def send_reply(analysis: MeetingAnalysis, to_email: str) -> bool:
    """Send the reply. Returns False (and logs) rather than raising if it cannot.

    A failed send must not lose the meeting: by the time this runs the analysis is
    already in the ledger, and the dashboard is the source of truth either way.
    """
    token = os.getenv("POSTMARK_TOKEN")
    sender = os.getenv("POSTMARK_FROM")

    if not token or not sender:
        logger.warning(
            "Postmark is not configured (POSTMARK_TOKEN / POSTMARK_FROM); "
            "skipping the reply to %s. The meeting is still in the ledger.",
            to_email,
        )
        return False

    if not to_email:
        logger.warning("The invite carried no organizer address; nothing to reply to.")
        return False

    subject, body = compose_reply(analysis)

    try:
        response = httpx.post(
            POSTMARK_SEND_URL,
            headers={"X-Postmark-Server-Token": token, "Accept": "application/json"},
            json={
                "From": sender,
                "To": to_email,
                "Subject": subject,
                "TextBody": body,
                "MessageStream": os.getenv("POSTMARK_STREAM", "outbound"),
            },
            timeout=SEND_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Postmark rejected the reply to %s.", to_email)
        return False

    logger.info("Replied to %s about %r.", to_email, analysis.title)
    return True

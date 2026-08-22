"""Door A / Door C — turn .ics text into a `ParsedInvite` (doc 2 §5.2, §5.3).

This is an adapter and nothing more. It produces exactly the object the manual form
produces, so an emailed invite and a typed-in meeting flow into the same `analyze()`
with no branch anywhere downstream.

Run it against a saved file for the dev/fallback path (doc 2 §5.3):

    cd backend && PYTHONPATH=. python -m app.services.ics_adapter invite.ics
"""

import re
from datetime import timedelta

from ics import Calendar

from app.enums import Tier

DEFAULT_DURATION_MINUTES = 60

# An .ics carries no role information, so every attendee is priced at the lowest tier.
# Understating a cost is the safe direction for a spend claim — better to be told a
# meeting costs less than it does than to overstate someone's time.
DEFAULT_ATTENDEE_TIER = Tier.IC

# RRULE says FREQ + INTERVAL; the cost math counts occurrences per year. Where an
# interval has no exact bucket, fall to the LESS frequent one so the annualised figure
# is never inflated.
_RECURRENCE_BY_INTERVAL = {
    ("DAILY", 1): "DAILY",
    ("WEEKLY", 1): "WEEKLY",
    ("WEEKLY", 2): "BIWEEKLY",
    ("MONTHLY", 1): "MONTHLY",
    ("YEARLY", 1): "YEARLY",
}
_LESS_FREQUENT = {"DAILY": "WEEKLY", "WEEKLY": "MONTHLY", "MONTHLY": "YEARLY", "YEARLY": "YEARLY"}


class NoInviteFound(Exception):
    """The text held no calendar event we could read."""


def _rrule_of(event) -> str | None:
    """The ics library leaves RRULE in `extra` rather than parsing it into a field."""
    for line in getattr(event, "extra", []) or []:
        if getattr(line, "name", "").upper() == "RRULE":
            return getattr(line, "value", None)
    return None


def recurrence_from_rrule(rrule: str | None) -> str | None:
    """Map an RRULE to one of the frequencies the cost math knows (doc 2 §6 costing)."""
    if not rrule:
        return None

    parts = dict(
        piece.split("=", 1) for piece in rrule.split(";") if "=" in piece
    )
    freq = parts.get("FREQ", "").strip().upper()
    if not freq:
        return None

    try:
        interval = max(1, int(parts.get("INTERVAL", "1")))
    except ValueError:
        interval = 1

    exact = _RECURRENCE_BY_INTERVAL.get((freq, interval))
    if exact:
        return exact
    # e.g. FREQ=WEEKLY;INTERVAL=3 — no exact bucket, so round down in cost terms.
    return _LESS_FREQUENT.get(freq)


def _read_calendar(ics_text: str) -> Calendar:
    """Parse the calendar, tolerating a missing PRODID.

    The `ics` library requires PRODID and refuses the whole calendar without it. Real
    invites carry one, but some senders do not — and dropping a genuine meeting over a
    header nobody reads is a worse failure than supplying it ourselves.
    """
    try:
        return Calendar(ics_text)
    except Exception:
        if "PRODID" in ics_text.upper():
            raise
        patched = re.sub(
            r"(BEGIN:VCALENDAR\s*\r?\n)",
            r"\1PRODID:-//ShouldBe//inbound//EN\r\n",
            ics_text,
            count=1,
        )
        return Calendar(patched)


def _duration_minutes(event) -> int:
    duration = getattr(event, "duration", None)
    if isinstance(duration, timedelta) and duration.total_seconds() > 0:
        return int(duration.total_seconds() // 60)
    return DEFAULT_DURATION_MINUTES


def _email_of(participant) -> str:
    email = getattr(participant, "email", None) or str(participant)
    return email.replace("mailto:", "").strip().lower()


def parse_ics(ics_text: str, exclude_emails: tuple[str, ...] = ()) -> "ParsedInvite":
    """One .ics event as a `ParsedInvite`.

    `exclude_emails` drops addresses that are in the room but not in the meeting —
    ShouldBe's own inbox above all. Billing the tool as an attendee would inflate every
    meeting it was ever invited to.
    """
    from app.schemas.invite import ParsedInvite  # local: keeps the schema import one-way

    try:
        calendar = _read_calendar(ics_text)
    except Exception as failure:  # the ics library raises a variety of parse errors
        raise NoInviteFound(f"Could not read the calendar attachment: {failure}") from failure

    events = list(calendar.events)
    if not events:
        raise NoInviteFound("The calendar attachment contained no event.")

    # A METHOD:REQUEST invite carries one event; take the earliest if it carries more.
    event = min(events, key=lambda e: (e.begin is None, e.begin))

    ignored = {address.lower() for address in exclude_emails if address}
    attendees = [
        email for email in (_email_of(a) for a in event.attendees) if email and email not in ignored
    ]

    organizer = _email_of(event.organizer) if event.organizer else ""
    recurrence = recurrence_from_rrule(_rrule_of(event))

    return ParsedInvite(
        title=(event.name or "Untitled meeting").strip(),
        description=(event.description or "").strip(),
        start=event.begin.datetime if event.begin else None,
        duration_minutes=_duration_minutes(event),
        attendee_tiers=[DEFAULT_ATTENDEE_TIER] * len(attendees),
        organizer_email=organizer,
        is_recurring=recurrence is not None,
        recurrence_freq=recurrence,
    )


def find_ics_text(payload: dict) -> str:
    """Pull the calendar part out of Postmark's parsed inbound JSON (doc 2 §5.2).

    Providers vary: an invite usually arrives as a `text/calendar` attachment, but is
    sometimes pasted into the body instead.
    """
    import base64

    for attachment in payload.get("Attachments") or []:
        content_type = (attachment.get("ContentType") or "").lower()
        name = (attachment.get("Name") or "").lower()
        if "text/calendar" not in content_type and not name.endswith(".ics"):
            continue
        try:
            return base64.b64decode(attachment.get("Content") or "").decode("utf-8", "replace")
        except (ValueError, TypeError):
            continue

    for body in (payload.get("TextBody"), payload.get("HtmlBody")):
        if body and "BEGIN:VCALENDAR" in body:
            match = re.search(r"BEGIN:VCALENDAR.*?END:VCALENDAR", body, re.S)
            if match:
                return match.group(0)

    raise NoInviteFound("No calendar attachment on that email.")


if __name__ == "__main__":  # Door C: parse and score a saved .ics with no email at all
    import json
    import sys

    from app.services.pipeline import analyze

    if len(sys.argv) < 2:
        sys.exit("usage: python -m app.services.ics_adapter <file.ics> [address-to-ignore]")

    invite = parse_ics(open(sys.argv[1]).read(), tuple(sys.argv[2:]))
    print(json.dumps(json.loads(invite.model_dump_json()), indent=2))
    print("\n--- analysis ---")
    print(json.dumps(json.loads(analyze(invite).model_dump_json()), indent=2))

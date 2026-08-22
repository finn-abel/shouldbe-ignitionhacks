"""Who was in the room, and what tier their time is priced at — pure, no I/O.

An .ics carries addresses and no roles, so every emailed meeting used to be priced as if
the whole room were the lowest tier. That is a systematic *understatement*: the meeting
with two directors in it reads the same as the one with two juniors. The directory is the
missing half — a per-user map from address to role tier — and this module is the logic
that applies it.

Two rules run through everything here:

- **Unknown is assumed, and assumed is visible.** An address nobody has placed is still
  priced (a meeting must land on the ledger), but the seat is flagged, so "we guessed" is
  never indistinguishable from "we knew".
- **Only a guess is ever revised.** Identifying someone corrects seats that were assumed.
  It never touches a seat whose tier was known when the meeting was priced — that is the
  ledger recording what happened, and it is the same reason changing a rate does not
  re-price the past.
"""

from dataclasses import dataclass

from app.enums import Tier
from app.services.inbound_routing import normalize_address

# What an address is priced at until someone says otherwise. Understating a cost is the
# safe direction for a spend claim: better to be told a meeting cost less than it did than
# to overstate someone's time. Kept identical to `ics_adapter.DEFAULT_ATTENDEE_TIER`.
UNKNOWN_TIER = Tier.IC

# One directory is one person's view of their colleagues. Bounded for the same reason the
# budget scope list is: a single PUT writes one row per entry.
MAX_DIRECTORY_ENTRIES = 2000


def person_key(email: str | None) -> str:
    """The identity an address is matched on: lowercased, unwrapped, `mailto:`-free.

    Plus-addressing is deliberately *not* stripped here, unlike the inbound routing check.
    `ada+standup@corp.com` is a real place mail lands and someone may reasonably want it
    priced on its own; collapsing it into `ada@corp.com` would silently merge two
    directory entries that the user typed separately.
    """
    return normalize_address(email)


@dataclass(frozen=True)
class Seat:
    """One attendee's place in a meeting, and whether their tier was known or guessed."""

    email: str
    tier: Tier
    is_assumed: bool


def seats_for(
    emails: list[str],
    known: dict[str, Tier],
    default: Tier = UNKNOWN_TIER,
) -> list[Seat]:
    """Resolve invite addresses against a directory, in the order they were invited.

    `known` is keyed by `person_key`. An address absent from it becomes an assumed seat at
    `default` rather than an error: an invite from a stranger still has to be costed and
    recorded, it just has to say so.
    """
    seats = []
    for email in emails:
        key = person_key(email)
        tier = known.get(key)
        seats.append(
            Seat(email=key, tier=tier if tier is not None else default, is_assumed=tier is None)
        )
    return seats


def resolved_invite(invite, known: dict[str, Tier]):
    """An invite priced against the directory — the shared path for every source.

    Returns the invite untouched when it names no addresses at all. That guard is the
    whole reason this exists rather than each source calling `seats_for` itself: the
    manual form sends head counts and no addresses, and resolving `[]` into seats replaces
    a room of fifteen people with a room of nobody. Every count-only meeting silently
    costs zero, the ledger totals collapse, and nothing raises.
    """
    if not invite.attendee_emails:
        return invite
    return invite.with_seats(seats_for(invite.attendee_emails, known))


def counted_seats(count: int, tiers: list[Tier]) -> list[Seat]:
    """Manual-form seats: head counts per tier, so nobody to identify and nothing assumed.

    The manual form asks how many people of each tier are in the room. Those tiers came
    from the user directly, which makes them known by construction — an anonymous seat is
    not the same thing as an unidentified one.
    """
    return [Seat(email="", tier=tier, is_assumed=False) for tier in tiers[:count]]


def unidentified(seats: list[Seat]) -> list[str]:
    """The addresses in these seats that nobody has placed yet, de-duplicated in order."""
    seen: list[str] = []
    for seat in seats:
        if seat.is_assumed and seat.email and seat.email not in seen:
            seen.append(seat.email)
    return seen

"""Meeting cost math — pure functions, no I/O (doc 2 §3.1, §4.4).

Two privacy rules from doc 1 are structural here, not incidental:

- Cost is derived from **blended role-tier rates**, never individual salaries.
- Output is **aggregate only** — a single pooled figure. Nothing in this module returns,
  or can be asked for, one attendee's contribution.
"""

import os
from decimal import ROUND_HALF_UP, Decimal

from app.enums import Tier

CENTS = Decimal("0.01")

MINUTES_PER_HOUR = Decimal(60)

# The most meeting time one occurrence can bill: a working day.
#
# A calendar is not only meetings. An .ics all-day event reads as 1440 minutes and a
# week-long conference as 6240, and costing those literally puts a $21,600 "meeting" and a
# $93,600 one on the books, which detonates the budget headline. The true duration is still
# recorded on the meeting (doc 2 §4.4); this caps only what it is billed for.
DEFAULT_MAX_BILLABLE_MINUTES = 8 * 60

# Doc 2 §4.2 defaults. Each user may override these; they are the starting point, not a
# hardcoded basis.
DEFAULT_TIER_RATES: dict[Tier, Decimal] = {
    Tier.IC: Decimal("75"),
    Tier.SENIOR: Decimal("110"),
    Tier.MANAGER: Decimal("150"),
    Tier.EXEC: Decimal("250"),
}

# Occurrences per year by recurrence frequency. DAILY counts workdays (260), not calendar
# days — a daily standup does not happen on Saturdays.
OCCURRENCES_PER_YEAR: dict[str, int] = {
    "DAILY": 260,
    "WEEKLY": 52,
    "BIWEEKLY": 26,
    "MONTHLY": 12,
    "YEARLY": 1,
}


def max_billable_minutes() -> int:
    """The billing cap, overridable per deployment."""
    raw = os.getenv("SHOULDBE_MAX_BILLABLE_MINUTES")
    if not raw:
        return DEFAULT_MAX_BILLABLE_MINUTES
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_BILLABLE_MINUTES


def billable_minutes(duration_minutes: int) -> int:
    """How much of a meeting's length is charged for. Applies to every door."""
    return min(duration_minutes, max_billable_minutes())


def is_clamped(duration_minutes: int) -> bool:
    """Whether this meeting is longer than a day's worth of billable time."""
    return duration_minutes > max_billable_minutes()


def _to_money(value: Decimal) -> Decimal:
    """Round to cents, half-up — how money reads on an invoice, not banker's rounding."""
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def _resolve_tier(tier: Tier | str) -> Tier:
    """Accept either the enum or its stored string form (Meeting.attendee_tiers is JSON)."""
    if isinstance(tier, Tier):
        return tier
    try:
        return Tier(tier)
    except ValueError:
        known = ", ".join(t.value for t in Tier)
        raise ValueError(f"Unknown role tier {tier!r}. Expected one of: {known}.") from None


def meeting_cost(
    attendee_tiers: list[Tier | str],
    duration_minutes: int,
    tier_rates: dict[Tier, Decimal] | None = None,
) -> Decimal:
    """Aggregate cost of one occurrence: Σ(attendee tier rate) × hours.

    `attendee_tiers` carries one entry per attendee, so its length is the head count that
    drives cost. An empty list costs nothing. Time beyond `max_billable_minutes()` is not
    charged for — see the constant for why.
    """
    if duration_minutes < 0:
        raise ValueError(f"duration_minutes must not be negative, got {duration_minutes}.")

    rates = DEFAULT_TIER_RATES if tier_rates is None else tier_rates

    hourly_total = Decimal(0)
    for tier in attendee_tiers:
        resolved = _resolve_tier(tier)
        if resolved not in rates:
            raise ValueError(f"No hourly rate configured for tier {resolved.value!r}.")
        hourly_total += Decimal(rates[resolved])

    hours = Decimal(billable_minutes(duration_minutes)) / MINUTES_PER_HOUR
    return _to_money(hourly_total * hours)


def annualized_cost(
    cost: Decimal,
    is_recurring: bool,
    recurrence_freq: str | None = None,
) -> Decimal | None:
    """Yearly run-rate of a recurring meeting: per-occurrence cost × occurrences per year.

    Returns None for a one-off meeting — matching the nullable `annualized_cost` column,
    where null means "does not recur".

    A recurring meeting with an unreadable frequency raises rather than returning None: a
    null would be indistinguishable from "one-off" and quietly understate the ledger.
    Callers that receive odd invites should normalise the frequency before calling.
    """
    if not is_recurring:
        return None

    if recurrence_freq is None:
        raise ValueError("A recurring meeting needs a recurrence_freq to be annualized.")

    key = recurrence_freq.strip().upper()
    if key not in OCCURRENCES_PER_YEAR:
        known = ", ".join(OCCURRENCES_PER_YEAR)
        raise ValueError(f"Unknown recurrence frequency {recurrence_freq!r}. Expected: {known}.")

    return _to_money(Decimal(cost) * OCCURRENCES_PER_YEAR[key])

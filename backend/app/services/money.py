"""The four dollar concepts and the burn-rate series (doc 2 §6).

Pure functions over a user's ledger — no DB, no HTTP. They take `MeetingRead` rather than
ORM rows so the money logic, like the cost math, can be tested without a database.

**Converted meetings are not spend.** Doc 2 §6's derivation column shows total spend as a
plain sum, but its prose is explicit that "spend is real money that happened" and that a
`converted` meeting "contributes to reclaimed savings, not spend" — a meeting swapped for
an email never happened, so its cost was never paid. Reading it the other way would leave
a converted meeting counted as spend and as avoided money at the same time, and would mean
converting meetings never moves the over-budget headline the product exists to move.

The reading gives a clean invariant the dashboard can rely on:

    total spend == necessary spend + avoidable spend
"""

import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.enums import BudgetScope, Status, Verdict
from app.schemas.api import BudgetComparison, BudgetGuardrailRead, MeetingRead, SpendBucket

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")
BUDGET_THRESHOLDS = (50, 80, 100)

Bucket = Literal["day", "week"]
Period = Literal["month", "all"]

# Timestamps are stored in UTC, but "this month" and "which day" are questions about the
# calendar the team lives in. Answering them in UTC means a meeting analysed at 9pm in
# Toronto lands on tomorrow, and on the last evening of a month the budget headline rolls
# over and the month's spend disappears mid-demo.
DEFAULT_TIMEZONE = "America/Toronto"


def business_timezone() -> ZoneInfo:
    """The calendar the figures are reported in."""
    name = os.getenv("SHOULDBE_TIMEZONE", DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def _local(moment: datetime, tz: ZoneInfo) -> datetime:
    """A stored timestamp as it reads on the wall clock."""
    if moment.tzinfo is None:  # defensive: the ORM already returns aware UTC
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz)


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def _happened(meeting: MeetingRead) -> bool:
    """Whether the meeting was actually held, and so actually cost money."""
    return meeting.status is not Status.CONVERTED


def total_spend(meetings: Iterable[MeetingRead]) -> Decimal:
    """All money spent on meetings that happened, whatever the verdict — the burn rate."""
    return _money(sum((m.cost for m in meetings if _happened(m)), ZERO))


def _scope_type(meeting: MeetingRead) -> BudgetScope:
    return meeting.budget_scope_type or BudgetScope.USER


def _scope_name(scope_type: BudgetScope, name: str | None) -> str:
    if name and name.strip():
        return name.strip()
    return "Personal" if scope_type is BudgetScope.USER else scope_type.value.title()


def within_budget_scope(
    meetings: Iterable[MeetingRead],
    scope_type: BudgetScope,
    scope_name: str | None = None,
) -> list[MeetingRead]:
    """Meetings that count toward a selected budget scope."""
    clean_name = _scope_name(scope_type, scope_name).lower()
    scoped = []
    for meeting in meetings:
        meeting_type = _scope_type(meeting)
        if meeting_type is not scope_type:
            continue
        if scope_type is BudgetScope.USER:
            scoped.append(meeting)
            continue
        if _scope_name(meeting_type, meeting.budget_scope_name).lower() == clean_name:
            scoped.append(meeting)
    return scoped


def necessary_spend(meetings: Iterable[MeetingRead]) -> Decimal:
    """Spend on meetings judged worth keeping."""
    return _money(
        sum((m.cost for m in meetings if _happened(m) and m.verdict is Verdict.KEEP), ZERO)
    )


def avoidable_spend(meetings: Iterable[MeetingRead]) -> Decimal:
    """Spend on meetings that could have been async but were held anyway."""
    return _money(
        sum((m.cost for m in meetings if _happened(m) and m.verdict is Verdict.EMAIL), ZERO)
    )


def reclaimed_savings(meetings: Iterable[MeetingRead]) -> Decimal:
    """Money *not* spent because a meeting was converted to an email — a counterfactual."""
    return _money(
        sum((m.reclaimed_savings for m in meetings if m.status is Status.CONVERTED), ZERO)
    )


def _month_of(moment: datetime, tz: ZoneInfo) -> tuple[int, int]:
    local = _local(moment, tz)
    return local.year, local.month


def _bucket_start(moment: datetime, bucket: Bucket, tz: ZoneInfo) -> date:
    day = _local(moment, tz).date()
    if bucket == "week":
        return day - timedelta(days=day.weekday())  # the Monday of that week
    return day


def within_period(
    meetings: Iterable[MeetingRead],
    period: Period = "all",
    now: datetime | None = None,
    tz: ZoneInfo | None = None,
) -> list[MeetingRead]:
    """The meetings a set of figures covers.

    Every dollar on the dashboard should state the span it covers, or two figures from
    different spans sit side by side looking comparable.
    """
    if period == "all":
        return list(meetings)
    if period != "month":
        raise ValueError(f"period must be 'month' or 'all', got {period!r}.")

    zone = tz or business_timezone()
    this_month = _month_of(now or datetime.now(timezone.utc), zone)
    return [m for m in meetings if _month_of(m.created_at, zone) == this_month]


def spend_over_time(
    meetings: Iterable[MeetingRead],
    bucket: Bucket = "day",
    tz: ZoneInfo | None = None,
) -> list[SpendBucket]:
    """Spend grouped by day or week of `created_at`, oldest first.

    Only periods that actually contain meetings are returned; the chart decides how to
    render the gaps between them.
    """
    if bucket not in ("day", "week"):
        raise ValueError(f"bucket must be 'day' or 'week', got {bucket!r}.")

    zone = tz or business_timezone()
    totals: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for meeting in meetings:
        if _happened(meeting):
            totals[_bucket_start(meeting.created_at, bucket, zone)] += meeting.cost

    return [SpendBucket(period=period, amount=_money(totals[period])) for period in sorted(totals)]


def budget_comparison(
    meetings: Iterable[MeetingRead],
    monthly_amount: Decimal | None,
    now: datetime | None = None,
    tz: ZoneInfo | None = None,
    scope_type: BudgetScope = BudgetScope.USER,
    scope_name: str | None = None,
) -> BudgetComparison:
    """This calendar month's spend against the monthly budget (doc 2 §6).

    "This month" means the month it is where the team is, not where the server is.
    """
    zone = tz or business_timezone()
    clean_scope_name = _scope_name(scope_type, scope_name)
    month_spend = total_spend(within_period(meetings, "month", now, zone))

    if monthly_amount is None:
        return BudgetComparison(
            monthly_amount=None,
            month_spend=month_spend,
            remaining_amount=None,
            usage_percent=None,
            difference=None,
            percent_over=None,
            is_over_budget=False,
            threshold=None,
            scope_type=scope_type,
            scope_name=clean_scope_name,
        )

    budget = Decimal(monthly_amount)
    difference = _money(month_spend - budget)
    remaining = _money(budget - month_spend)

    # A zero budget cannot be exceeded by a percentage; report the dollars instead.
    usage_percent = float(month_spend / budget * 100) if budget > 0 else None
    percent_over = float(difference / budget * 100) if budget > 0 else None
    threshold = _budget_threshold(usage_percent)

    return BudgetComparison(
        monthly_amount=_money(budget),
        month_spend=month_spend,
        remaining_amount=remaining,
        usage_percent=usage_percent,
        difference=difference,
        percent_over=percent_over,
        is_over_budget=month_spend > budget,
        threshold=threshold,
        scope_type=scope_type,
        scope_name=clean_scope_name,
    )


def _budget_threshold(usage_percent: float | None) -> int | None:
    if usage_percent is None:
        return None
    crossed = [threshold for threshold in BUDGET_THRESHOLDS if usage_percent >= threshold]
    return crossed[-1] if crossed else None


def budget_guardrail(
    meetings: Iterable[MeetingRead],
    monthly_amount: Decimal | None,
    meeting_cost: Decimal,
    *,
    scope_type: BudgetScope = BudgetScope.USER,
    scope_name: str | None = None,
    now: datetime | None = None,
    tz: ZoneInfo | None = None,
) -> BudgetGuardrailRead:
    """Project one prospective meeting against the selected monthly budget."""
    scoped = within_budget_scope(meetings, scope_type, scope_name)
    current = budget_comparison(scoped, monthly_amount, now, tz, scope_type, scope_name)
    cost = _money(meeting_cost)
    projected_spend = _money(current.month_spend + cost)

    if monthly_amount is None:
        return BudgetGuardrailRead(
            budget=current,
            meeting_cost=cost,
            projected_spend=projected_spend,
            projected_remaining_amount=None,
            projected_usage_percent=None,
            threshold_crossed=None,
            exceeds_budget=False,
            warning=None,
        )

    budget = _money(Decimal(monthly_amount))
    projected_remaining = _money(budget - projected_spend)
    projected_usage = float(projected_spend / budget * 100) if budget > 0 else None
    projected_threshold = _budget_threshold(projected_usage)
    threshold_crossed = (
        projected_threshold
        if projected_threshold is not None and projected_threshold != current.threshold
        else None
    )
    exceeds_budget = projected_spend > budget
    warning = None
    label = f"{current.scope_name} {current.scope_type.value}"
    if exceeds_budget:
        if current.is_over_budget:
            warning = (
                f"{label} budget is already over. This meeting adds {_money(cost)} and "
                f"would put monthly spend at {_money(projected_spend)} against a "
                f"{_money(budget)} budget."
            )
        else:
            warning = (
                f"This meeting would exceed the {label} budget: projected spend "
                f"{_money(projected_spend)} against {_money(budget)}."
            )
        threshold_crossed = 100
    elif threshold_crossed is not None:
        warning = (
            f"This meeting would move the {label} budget past {threshold_crossed}% usage "
            f"({_money(projected_spend)} of {_money(budget)})."
        )

    return BudgetGuardrailRead(
        budget=current,
        meeting_cost=cost,
        projected_spend=projected_spend,
        projected_remaining_amount=projected_remaining,
        projected_usage_percent=projected_usage,
        threshold_crossed=threshold_crossed,
        exceeds_budget=exceeds_budget,
        warning=warning,
    )


def reclaimed_by_converting(cost: Decimal) -> Decimal:
    """What swapping a meeting for an email reclaims (doc 2 §5.4).

    The whole cost, because the meeting does not happen at all. Named and kept here with
    the other money rules rather than inlined at the call site: it is the one place that
    decides how much a conversion is worth, and assignment (not accumulation) makes
    converting an already-converted meeting a no-op rather than double-counting.
    """
    return _money(cost)

"""API response schemas (doc 2 §3.2, §3.5).

ORM models never leave an endpoint; these are what the API actually returns.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

from app.enums import Status, Tier, Verdict


class MeetingAnalysis(BaseModel):
    """The analysis record — what `analyze()` produces (doc 2 §4.4).

    Carries every field of a `Meeting` except the persistence ones (`id`, `user_id`,
    `created_at`), which the ledger assigns when the analysis is saved in step 5.
    """

    # --- invite facts ---
    title: str
    description: str
    start: datetime | None
    duration_minutes: int
    attendee_count: int
    attendee_tiers: list[Tier]
    organizer_email: str
    is_recurring: bool
    recurrence_freq: str | None

    # --- computed financials ---
    cost: Decimal
    annualized_cost: Decimal | None

    # --- AI output ---
    score: int
    verdict: Verdict
    reasoning: str
    alternative_email: str | None

    # --- lifecycle / money state ---
    status: Status
    reclaimed_savings: Decimal


class MeetingRead(MeetingAnalysis):
    """A saved ledger row. The analysis, plus the two fields persistence assigns."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class SpendBucket(BaseModel):
    """One point on the burn-rate chart."""

    period: date
    amount: Decimal


class BudgetComparison(BaseModel):
    """Current-month spend against the user's budget (doc 2 §6).

    `monthly_amount` and the two derived figures are null when the user has no budget set
    — a missing budget is not the same as a zero one.
    """

    monthly_amount: Decimal | None
    month_spend: Decimal
    difference: Decimal | None        # spend - budget; positive means over
    percent_over: float | None        # the "34% over budget" headline
    is_over_budget: bool


class Stats(BaseModel):
    """The four dollar concepts, the burn-rate series, and the budget headline."""

    total_spend: Decimal
    necessary_spend: Decimal
    avoidable_spend: Decimal
    reclaimed_savings: Decimal
    spend_over_time: list[SpendBucket]
    budget: BudgetComparison


class BudgetRead(BaseModel):
    """The acting user's monthly meeting budget. Null when they have not set one."""

    monthly_amount: Decimal | None


class BudgetUpdate(BaseModel):
    monthly_amount: Decimal = Field(ge=0, le=Decimal("100000000"))


class TierRates(RootModel[dict[Tier, Decimal]]):
    """The four blended role-tier rates, keyed by tier.

    Blended rates only — doc 1's privacy stance means an individual salary must never be
    representable here, and a per-person shape would make it representable.
    """

    @field_validator("root")
    @classmethod
    def _complete_and_non_negative(cls, rates: dict[Tier, Decimal]) -> dict[Tier, Decimal]:
        missing = {tier.value for tier in Tier} - {tier.value for tier in rates}
        if missing:
            raise ValueError(f"Every tier needs a rate. Missing: {', '.join(sorted(missing))}.")
        for tier, rate in rates.items():
            if rate < 0:
                raise ValueError(f"The {tier.value} rate must not be negative.")
        return rates


class MeetingStatusUpdate(BaseModel):
    """The convert transition (doc 2 §5.4). Only `converted` is offered by this step."""

    status: Status

    @field_validator("status")
    @classmethod
    def _only_converted(cls, value: Status) -> Status:
        # Literal[Status.CONVERTED] would not accept the JSON string "converted", since
        # Status is a plain Enum rather than a str-Enum. Coerce, then check.
        if value is not Status.CONVERTED:
            raise ValueError(
                f"Only a change to {Status.CONVERTED.value!r} is supported here, "
                f"got {value.value!r}."
            )
        return value

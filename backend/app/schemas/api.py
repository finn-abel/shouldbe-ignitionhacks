"""API response schemas (doc 2 §3.2, §3.5).

ORM models never leave an endpoint; these are what the API actually returns.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

from app.enums import BudgetScope, OutboxStatus, Status, Tier, Verdict


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
    budget_scope_type: BudgetScope | None = BudgetScope.USER
    budget_scope_name: str | None = None

    # --- computed financials ---
    cost: Decimal
    annualized_cost: Decimal | None

    # --- AI output ---
    score: int
    verdict: Verdict
    reasoning: str
    alternative_email: str | None
    analysis_notice: str | None = None
    analysis_error_code: str | None = None

    # --- lifecycle / money state ---
    status: Status
    reclaimed_savings: Decimal

    @model_validator(mode="after")
    def _default_budget_scope(self):
        if self.budget_scope_type is None:
            object.__setattr__(self, "budget_scope_type", BudgetScope.USER)
        if not self.budget_scope_name:
            name = "Personal" if self.budget_scope_type is BudgetScope.USER else self.budget_scope_type.value.title()
            object.__setattr__(self, "budget_scope_name", name)
        return self


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
    remaining_amount: Decimal | None = None
    usage_percent: float | None = None
    difference: Decimal | None        # spend - budget; positive means over
    percent_over: float | None        # the "34% over budget" headline
    is_over_budget: bool
    threshold: int | None = None
    scope_type: BudgetScope = BudgetScope.USER
    scope_name: str = "Personal"


class Stats(BaseModel):
    """The four dollar concepts, the burn-rate series, and the budget headline.

    `period` names the span the four figures and the series cover, so nothing on the
    dashboard is a dollar amount without a stated span. The budget headline is always the
    current month — it compares against a monthly budget.
    """

    period: str
    total_spend: Decimal
    necessary_spend: Decimal
    avoidable_spend: Decimal
    reclaimed_savings: Decimal
    spend_over_time: list[SpendBucket]
    budget: BudgetComparison


class ScopedBudgetRead(BaseModel):
    """One configured monthly budget guardrail."""

    scope_type: BudgetScope
    scope_name: str
    monthly_amount: Decimal | None = None
    is_active: bool = False


class BudgetRead(BaseModel):
    """The acting user's user/team/department monthly meeting budgets."""

    monthly_amount: Decimal | None
    active_scope_type: BudgetScope = BudgetScope.USER
    active_scope_name: str = "Personal"
    budgets: list[ScopedBudgetRead] = Field(default_factory=list)


class ScopedBudgetUpdate(BaseModel):
    scope_type: BudgetScope
    scope_name: str = Field(min_length=1, max_length=255)
    monthly_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    is_active: bool = False


class BudgetUpdate(BaseModel):
    monthly_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    active_scope_type: BudgetScope = BudgetScope.USER
    active_scope_name: str = Field(default="Personal", min_length=1, max_length=255)
    budgets: list[ScopedBudgetUpdate] | None = None


class BudgetGuardrailRead(BaseModel):
    """Projected budget impact before a meeting is recorded."""

    budget: BudgetComparison
    meeting_cost: Decimal
    projected_spend: Decimal
    projected_remaining_amount: Decimal | None = None
    projected_usage_percent: float | None = None
    threshold_crossed: int | None = None
    exceeds_budget: bool
    warning: str | None = None


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


class UserRead(BaseModel):
    """Who the request is acting as (doc 2 §4.1)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    is_guest: bool


class InboundRouteRead(BaseModel):
    """The user's email door: where to invite ShouldBe from, and what it answers to."""

    model_config = ConfigDict(from_attributes=True)

    invite_address: str
    token: str
    domain: str | None = None
    # False when SHOULDBE_INBOX is unset, so the UI can say "email is not set up yet"
    # instead of showing a plausible address that silently goes nowhere.
    email_configured: bool


class InboundRouteUpdate(BaseModel):
    """Claim a company domain, or clear it with null."""

    domain: str | None = Field(default=None, max_length=255)


class OutboxRead(BaseModel):
    """One queued or delivered reply — what `GET /api/outbox` returns."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    meeting_id: int
    to_email: str
    subject: str
    status: OutboxStatus
    attempts: int
    last_error: str | None = None
    created_at: datetime
    sent_at: datetime | None = None

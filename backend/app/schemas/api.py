"""API response schemas (doc 2 §3.2, §3.5).

ORM models never leave an endpoint; these are what the API actually returns.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

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

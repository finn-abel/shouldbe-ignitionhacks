"""ORM entities exactly per doc 2 §4 — persistence only.

The shared enums live in `app/enums.py` so the pure services can use the same vocabulary
without importing the database layer.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.data.db import Base
from app.enums import Status, Tier, Verdict

class UtcDateTime(TypeDecorator):
    """Timestamps that are UTC-aware on the way in and on the way out, on any dialect.

    Postgres returns an aware datetime from a `timestamptz` column; SQLite has no
    timezone storage and hands back a naive one. Left alone, that divergence means code
    comparing a stored timestamp against `datetime.now(timezone.utc)` works in the cloud
    and raises "can't compare offset-naive and offset-aware datetimes" locally — the
    exact class of SQLite/Postgres surprise doc 4 task 4-B warns about. The burn-rate
    bucketing and the current-month budget comparison both do that comparison.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


# Money is stored at cent precision. Postgres enforces this; SQLite is lax about it
# (doc 4 task 4-B) — keep the column type authoritative rather than the dialect.
MONEY = Numeric(12, 2)

DEFAULT_DURATION_MINUTES = 60


def _enum_column(enum_cls, **kwargs):
    """Portable enum column: VARCHAR + CHECK, storing the lowercase member *values*.

    Avoids Postgres native ENUM types, which need a migration to gain a value, and keeps
    the stored strings identical to the ones doc 2 §4 names.
    """
    return mapped_column(
        SAEnum(
            enum_cls,
            native_enum=False,
            values_callable=lambda e: [member.value for member in e],
        ),
        **kwargs,
    )


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    """The account. Real sign-ins and the single shared guest are both rows here (§4.1)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    is_guest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow)

    tier_rates: Mapped[list["RoleTierRate"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    budget: Mapped["Budget | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    meetings: Mapped[list["Meeting"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RoleTierRate(Base):
    """Blended hourly rate for one role tier — never an individual salary (§4.2)."""

    __tablename__ = "role_tier_rates"
    __table_args__ = (UniqueConstraint("user_id", "tier", name="uq_tier_rate_per_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    tier: Mapped[Tier] = _enum_column(Tier, nullable=False)
    hourly_rate: Mapped[float] = mapped_column(MONEY, nullable=False)

    user: Mapped[User] = relationship(back_populates="tier_rates")


class Budget(Base):
    """One org-wide monthly meeting budget per user (§4.3)."""

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    monthly_amount: Mapped[float] = mapped_column(MONEY, nullable=False)

    user: Mapped[User] = relationship(back_populates="budget")


class Meeting(Base):
    """The analysis record — every analyzed meeting from any door (§4.4).

    Meetings judged necessary are recorded too: the ledger tracks all meeting spend, and
    the verdict is an attribute of the transaction, not a filter on what gets written.
    """

    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    # --- invite facts (populated by whichever door's adapter) ---
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    start: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_DURATION_MINUTES
    )
    attendee_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attendee_tiers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    organizer_email: Mapped[str] = mapped_column(String(320), nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recurrence_freq: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- computed financials ---
    cost: Mapped[float] = mapped_column(MONEY, nullable=False)
    annualized_cost: Mapped[float | None] = mapped_column(MONEY, nullable=True)

    # --- AI output ---
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[Verdict] = _enum_column(Verdict, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    alternative_email: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- lifecycle / money state ---
    status: Mapped[Status] = _enum_column(Status, nullable=False, default=Status.ANALYZED)
    reclaimed_savings: Mapped[float] = mapped_column(MONEY, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow, index=True)

    user: Mapped[User] = relationship(back_populates="meetings")

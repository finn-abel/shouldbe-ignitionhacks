"""ORM entities exactly per doc 2 §4 — persistence only.

The shared enums live in `app/enums.py` so the pure services can use the same vocabulary
without importing the database layer.
"""

from datetime import datetime, timezone
from decimal import Decimal

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
from app.enums import BudgetScope, OutboxStatus, Status, Tier, Verdict

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
    people: Mapped[list["Person"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    budget: Mapped["Budget | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    scoped_budgets: Mapped[list["ScopedBudget"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
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
    hourly_rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    user: Mapped[User] = relationship(back_populates="tier_rates")


class Person(Base):
    """One known colleague and the role tier their time is priced at.

    The directory is what turns "18 email addresses on an invite" into a real cost. An
    .ics carries no role information, so without this every attendee is priced at the
    lowest tier and every emailed meeting is understated (see
    `ics_adapter.DEFAULT_ATTENDEE_TIER`).

    Still not individual compensation: a row says which *blended tier* a person is priced
    at, never what they are paid. The rate lives on `role_tier_rates`, shared by everyone
    in the tier, so doc 1's privacy stance holds — this adds no number that is about one
    person.

    Scoped per user, not global: two accounts may legitimately place the same colleague at
    different tiers, and one user's directory must never leak into another's ledger.
    """

    __tablename__ = "people"
    __table_args__ = (UniqueConstraint("user_id", "email", name="uq_person_per_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # Normalized by `services.directory.person_key` before it ever reaches this column, so
    # `Ada@Corp.com` and `ada@corp.com` are one person rather than two half-priced ones.
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    tier: Mapped[Tier] = _enum_column(Tier, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow)

    user: Mapped[User] = relationship(back_populates="people")


class MeetingAttendee(Base):
    """One seat in one meeting, at the rate it was actually billed.

    `Meeting.attendee_tiers` is the aggregate the cost math consumes; these rows are the
    per-seat detail that makes a *correction* possible later. Two things are stored that
    cannot be recovered afterwards:

    - `email`, so an unidentified attendee can be identified at all. The .ics adapter used
      to discard addresses the moment it counted them.
    - `hourly_rate`, the blended tier rate this seat was priced at. Identifying one person
      then re-prices only their seat, and every other seat keeps exactly what it cost —
      which is the difference between correcting a guess and re-writing history.

    `is_assumed` separates the two: true means nobody ever said who this was and the seat
    was priced at the default tier. Only assumed seats are ever re-priced.
    """

    __tablename__ = "meeting_attendees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Order is preserved so the seat list lines up with `Meeting.attendee_tiers`.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # "" for a manual-form seat: Door B asks for head counts per tier, not addresses, so
    # those seats are known-by-construction and have nobody to identify.
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="", index=True)
    tier: Mapped[Tier] = _enum_column(Tier, nullable=False)
    hourly_rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    is_assumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    meeting: Mapped["Meeting"] = relationship(back_populates="attendees")


class Budget(Base):
    """Legacy user-level monthly meeting budget (§4.3).

    Scoped budgets live in `scoped_budgets`; this row is retained so existing seeded and
    signed-in users keep their user budget without a data migration.
    """

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    monthly_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    user: Mapped[User] = relationship(back_populates="budget")


class ScopedBudget(Base):
    """A monthly meeting budget for one user/team/department guardrail."""

    __tablename__ = "scoped_budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "scope_type", "scope_name", name="uq_budget_scope_per_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    scope_type: Mapped[BudgetScope] = _enum_column(BudgetScope, nullable=False)
    scope_name: Mapped[str] = mapped_column(String(255), nullable=False)
    monthly_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped[User] = relationship(back_populates="scoped_budgets")


class Meeting(Base):
    """The analysis record — every analyzed meeting from any door (§4.4).

    Meetings judged necessary are recorded too: the ledger tracks all meeting spend, and
    the verdict is an attribute of the transaction, not a filter on what gets written.
    """

    __tablename__ = "meetings"
    __table_args__ = (
        # Door A's at-most-once guarantee. Postmark redelivers an inbound message up to
        # six times over ~51 minutes — including when the endpoint did the work but
        # answered too slowly — so the database, not the handler, is what makes a repeat
        # delivery harmless. Null for manual-form meetings, and SQL treats each NULL as
        # distinct, so Door B is unconstrained.
        UniqueConstraint("user_id", "source_key", name="uq_meeting_source_per_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

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
    budget_scope_type: Mapped[BudgetScope | None] = _enum_column(BudgetScope, nullable=True)
    budget_scope_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- computed financials ---
    cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    annualized_cost: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    # --- AI output ---
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[Verdict] = _enum_column(Verdict, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    alternative_email: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- lifecycle / money state ---
    status: Mapped[Status] = _enum_column(Status, nullable=False, default=Status.ANALYZED)
    reclaimed_savings: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow, index=True)

    user: Mapped[User] = relationship(back_populates="meetings")
    attendees: Mapped[list["MeetingAttendee"]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="MeetingAttendee.position",
    )

    # Read by `MeetingRead` through `from_attributes`. Both are empty for a meeting
    # recorded before seats were stored, which reads correctly: nothing to identify.
    @property
    def attendee_emails(self) -> list[str]:
        return [seat.email for seat in self.attendees]

    @property
    def unidentified_count(self) -> int:
        """Seats priced on a guess. Non-zero means this row is an estimate, not a figure."""
        return sum(1 for seat in self.attendees if seat.is_assumed and seat.email)


class InboundRoute(Base):
    """How an emailed invite finds its owner (doc 2 §5.2's "known edge", closed).

    Door A used to attribute every invite to the shared guest, because an inbound email
    carries no session. This row is what an invite is matched against instead. One per
    user, created lazily so an existing database gains routing without a re-seed.

    Two independent handles, because they fail in opposite directions:

    - `token` is explicit and unambiguous — it rides in the address the organizer invited
      (`ledger+ab12cd@...`), so it works no matter which account sent the invite.
    - `domain` is implicit and zero-effort — anyone at the company gets attributed without
      knowing ShouldBe exists. It is nullable, unique, and MUST NOT be a public mailbox
      provider: claiming `gmail.com` would capture every gmail organizer's invites.
      `app.services.inbound_routing` enforces that; the column only enforces uniqueness.
    """

    __tablename__ = "inbound_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    token: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow)

    user: Mapped[User] = relationship()


class EmailOutbox(Base):
    """One outbound reply, durable (the transactional outbox pattern).

    The reply used to be a bare `BackgroundTasks` call: if Postmark was unreachable the
    send was logged and lost, and because a redelivered invite hits the idempotency guard
    and never re-sends, nothing would ever try again. So the reply is now a row, written
    in the *same commit* as its `Meeting` — the meeting and its pending reply either both
    exist or neither does.

    The body is rendered at enqueue time rather than at send time. `compose_reply` needs a
    `MeetingAnalysis`, which only exists in the request that scored the invite; storing the
    finished text means the drain needs nothing but this row.

    This is also what makes a brand-new Postmark account survivable. Until Postmark
    manually approves an account it refuses any recipient outside your own verified
    domains — so those replies simply stay QUEUED and send themselves once approval lands.
    """

    __tablename__ = "email_outbox"
    __table_args__ = (
        # At most one reply per meeting, for the same reason `uq_meeting_source_per_user`
        # exists: Postmark redelivers an inbound message up to six times, and the database
        # rather than the handler is what makes a repeat harmless.
        UniqueConstraint("meeting_id", name="uq_outbox_per_meeting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), nullable=False)

    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    text_body: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[OutboxStatus] = _enum_column(
        OutboxStatus, nullable=False, default=OutboxStatus.QUEUED, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    meeting: Mapped[Meeting] = relationship()

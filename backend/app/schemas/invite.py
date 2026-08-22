"""`ParsedInvite` and the manual-form input that produces one.

Every source — the manual form, an emailed .ics, a saved .ics — is a thin adapter whose
only job is to produce a `ParsedInvite`. `analyze()` never learns which source it came
through, so the mapping from a source's own shape into this one lives with the schemas.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.enums import BudgetScope, Tier
from app.services.costing import OCCURRENCES_PER_YEAR

DEFAULT_DURATION_MINUTES = 60

# Head counts and free text both used to be unbounded, and both are reachable from a tiny
# request body. `{"ic": 100000000}` was ~30 bytes that expanded into a hundred-million-entry
# list — one entry per attendee — which was then validated, priced, and written to a JSON
# column. A cap is the whole fix: no real meeting is near these numbers, and a request that
# exceeds them is a 422 instead of an allocation the process does not survive.
MAX_ATTENDEES = 1000
MAX_DESCRIPTION_CHARS = 20_000
# One budget row is written per scope in a single PUT, so the list needs a ceiling too.
MAX_BUDGET_SCOPES = 100


def normalised_recurrence(is_recurring: bool, recurrence_freq: str | None) -> str | None:
    """Validate and upper-case a recurrence, or clear it for a one-off meeting.

    `annualized_cost` refuses to guess at a frequency it cannot read, so every source checks
    it here first. Both schemas below run this: `ManualMeetingInput` is the HTTP boundary,
    where a failure must surface as a 422 rather than a 500, and `ParsedInvite` is the
    boundary the other two sources come through.
    """
    if not is_recurring:
        return None

    if not recurrence_freq or not recurrence_freq.strip():
        raise ValueError("recurrence_freq is required when is_recurring is true.")

    freq = recurrence_freq.strip().upper()
    if freq not in OCCURRENCES_PER_YEAR:
        known = ", ".join(OCCURRENCES_PER_YEAR)
        raise ValueError(f"recurrence_freq must be one of: {known}.")
    return freq


class ParsedInvite(BaseModel):
    """What every source produces and the pipeline consumes."""

    title: str = Field(min_length=1, max_length=512)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_CHARS)
    start: datetime | None = None
    duration_minutes: int = Field(default=DEFAULT_DURATION_MINUTES, ge=0)
    attendee_tiers: list[Tier] = Field(default_factory=list, max_length=MAX_ATTENDEES)
    # Positionally aligned with `attendee_tiers`: entry i is who seat i is. Empty for a
    # source that has no addresses to give (the manual form counts heads per tier), and `""`
    # for an individual seat whose address could not be read. Carrying them is what lets
    # an attendee be identified after the fact — the .ics adapter used to count the
    # addresses and throw them away, which made every emailed meeting permanently a guess.
    attendee_emails: list[str] = Field(default_factory=list, max_length=MAX_ATTENDEES)
    organizer_email: str = ""
    is_recurring: bool = False
    recurrence_freq: str | None = None
    budget_scope_type: BudgetScope = BudgetScope.USER
    budget_scope_name: str = Field(default="Personal", max_length=255)

    @property
    def attendee_count(self) -> int:
        """One entry per attendee, so the tier list is the head count."""
        return len(self.attendee_tiers)

    @model_validator(mode="after")
    def _check_recurrence(self):
        object.__setattr__(
            self, "recurrence_freq", normalised_recurrence(self.is_recurring, self.recurrence_freq)
        )
        return self

    @model_validator(mode="after")
    def _emails_line_up_with_tiers(self):
        """An address list, if given at all, must have one entry per seat.

        A short list would silently shift every address onto the wrong attendee — seat 5's
        tier attributed to seat 4's person — and identifying someone would then re-price
        the wrong seat. Padding is the fix rather than raising: a door that reads only some
        addresses should still record the meeting.
        """
        if self.attendee_emails and len(self.attendee_emails) != len(self.attendee_tiers):
            padded = (list(self.attendee_emails) + [""] * len(self.attendee_tiers))[
                : len(self.attendee_tiers)
            ]
            object.__setattr__(self, "attendee_emails", padded)
        return self

    def with_seats(self, seats) -> "ParsedInvite":
        """A copy priced for these seats — the directory applied, nothing mutated.

        `seats` is a list of `services.directory.Seat`. Returns a new invite rather than
        editing this one, so the raw parse of what arrived stays intact next to the
        resolved version of it.
        """
        return self.model_copy(
            update={
                "attendee_tiers": [seat.tier for seat in seats],
                "attendee_emails": [seat.email for seat in seats],
            }
        )


class ManualMeetingInput(BaseModel):
    """The dashboard form input.

    Attendees arrive as a head count per role tier rather than one entry each: it is what
    a form can reasonably ask for, and it makes the demo's "change 3 attendees to 10"
    a single number to edit.
    """

    title: str = Field(min_length=1, max_length=512)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_CHARS)
    start: datetime | None = None
    duration_minutes: int = Field(default=DEFAULT_DURATION_MINUTES, ge=0, le=24 * 60)
    attendees: dict[Tier, int] = Field(default_factory=dict)
    organizer_email: str = ""
    is_recurring: bool = False
    recurrence_freq: str | None = None
    budget_scope_type: BudgetScope = BudgetScope.USER
    budget_scope_name: str = Field(default="Personal", min_length=1, max_length=255)

    @field_validator("attendees")
    @classmethod
    def _sane_head_counts(cls, value: dict[Tier, int]) -> dict[Tier, int]:
        """Reject negatives, and reject a total nobody could fit in a meeting.

        The total is what matters: `to_parsed_invite` expands these counts into one list
        entry per attendee, so an unbounded sum is an unbounded allocation driven by a
        request body of a few dozen bytes.
        """
        for tier, count in value.items():
            if count < 0:
                raise ValueError(f"Attendee count for {tier.value!r} must not be negative.")

        total = sum(value.values())
        if total > MAX_ATTENDEES:
            raise ValueError(
                f"{total} attendees is more than the {MAX_ATTENDEES} this supports. "
                "Check the head counts."
            )
        return value

    @model_validator(mode="after")
    def _check_recurrence(self):
        object.__setattr__(
            self, "recurrence_freq", normalised_recurrence(self.is_recurring, self.recurrence_freq)
        )
        return self

    def to_parsed_invite(self) -> ParsedInvite:
        """Manual-form adapter: expand the per-tier counts into one entry per attendee."""
        tiers = [tier for tier, count in self.attendees.items() for _ in range(count)]
        return ParsedInvite(
            title=self.title,
            description=self.description,
            start=self.start,
            duration_minutes=self.duration_minutes,
            attendee_tiers=tiers,
            organizer_email=self.organizer_email,
            is_recurring=self.is_recurring,
            recurrence_freq=self.recurrence_freq,
            budget_scope_type=self.budget_scope_type,
            budget_scope_name=self.budget_scope_name,
        )

"""Shared domain vocabulary (doc 2 §4).

A leaf module: it imports nothing of ours, so both `services/` and `data/` can depend on
it without the pure money functions dragging in SQLAlchemy or a database URL.
"""

from enum import Enum


class Tier(Enum):
    """Role tier — the privacy-preserving cost basis (doc 2 §4.2)."""

    IC = "ic"
    SENIOR = "senior"
    MANAGER = "manager"
    EXEC = "exec"


class BudgetScope(Enum):
    """Where a meeting's spend is counted for guardrails."""

    USER = "user"
    TEAM = "team"
    DEPARTMENT = "department"


class Verdict(Enum):
    """Necessity call (doc 2 §4.4). KEEP = genuine live need; EMAIL = could be async."""

    KEEP = "keep"
    EMAIL = "email"

    @property
    def label(self) -> str:
        """How the verdict is worded wherever a person reads it.

        One source for the sentence, because it is said in three places that must agree:
        the dashboard, the ledger row, and the subject line of the reply that goes to the
        organizer. Those had drifted into three different phrasings of the same call —
        "Should be an email", "Worth the room", "could be an email" — so an organizer
        reading their inbox and a user reading the ledger saw different words for one
        decision. The frontend's `lib/verdict.js` carries the same two strings.
        """
        return _VERDICT_LABELS[self]


_VERDICT_LABELS = {
    Verdict.EMAIL: "Should Be an email",
    Verdict.KEEP: "Should Be a meeting",
}


class Status(Enum):
    """Lifecycle / money state (doc 2 §6).

    ANALYZED  — default; the meeting is on the books as spend.
    HELD      — explicitly kept, whether necessary or unnecessary-but-not-converted.
    CONVERTED — swapped for an email; contributes to reclaimed savings, not spend.
    """

    ANALYZED = "analyzed"
    HELD = "held"
    CONVERTED = "converted"


class OutboxStatus(Enum):
    """Delivery state of one queued outbound reply.

    QUEUED — not yet accepted by the mail provider. Covers every recoverable state:
             not configured, domain not verified yet, rate limited, provider down. All
             of them resolve without anyone touching this row, so it waits.
    SENT   — the provider accepted it.
    FAILED — permanently undeliverable, or out of attempts. Never retried again.
    """

    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"

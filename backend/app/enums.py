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


class Verdict(Enum):
    """Necessity call (doc 2 §4.4). KEEP = genuine live need; EMAIL = could be async."""

    KEEP = "keep"
    EMAIL = "email"


class Status(Enum):
    """Lifecycle / money state (doc 2 §6).

    ANALYZED  — default; the meeting is on the books as spend.
    HELD      — explicitly kept, whether necessary or unnecessary-but-not-converted.
    CONVERTED — swapped for an email; contributes to reclaimed savings, not spend.
    """

    ANALYZED = "analyzed"
    HELD = "held"
    CONVERTED = "converted"

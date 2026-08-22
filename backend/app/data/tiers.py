"""Role-tier rate access (doc 2 §4.2) — the privacy-preserving cost basis.

Blended rates per role tier. Individual compensation never enters the system.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import RoleTierRate
from app.enums import Tier
from app.services.costing import DEFAULT_TIER_RATES


def get_tier_rates(session: Session, user_id: int) -> dict[Tier, Decimal]:
    """The user's rates, in the shape the cost math takes.

    Any tier the user has no row for falls back to the documented default, so a partially
    configured user can still be costed rather than erroring mid-analysis.
    """
    rows = session.scalars(select(RoleTierRate).where(RoleTierRate.user_id == user_id))
    return {**DEFAULT_TIER_RATES, **{row.tier: row.hourly_rate for row in rows}}


def set_tier_rates(
    session: Session, user_id: int, rates: dict[Tier, Decimal]
) -> dict[Tier, Decimal]:
    """Replace the user's rates. Existing meetings keep the cost they were priced at."""
    existing = {
        row.tier: row
        for row in session.scalars(
            select(RoleTierRate).where(RoleTierRate.user_id == user_id)
        )
    }

    for tier, hourly_rate in rates.items():
        if tier in existing:
            existing[tier].hourly_rate = hourly_rate
        else:
            session.add(RoleTierRate(user_id=user_id, tier=tier, hourly_rate=hourly_rate))

    session.commit()
    # SessionLocal keeps objects alive past commit, so re-read through the DB rather
    # than echoing the Python values back — otherwise PUT answers "75" where GET
    # answers "75.00" for the same rate.
    session.expire_all()
    return get_tier_rates(session, user_id)

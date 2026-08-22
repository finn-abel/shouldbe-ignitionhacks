"""Role-tier hourly rate config (doc 2 §4.2). Thin: parse, delegate, return."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.data.db import get_session
from app.data.models import User
from app.data.tiers import get_tier_rates, set_tier_rates
from app.routes.auth import acting_user
from app.schemas.api import TierRates

router = APIRouter(prefix="/api", tags=["tiers"])


@router.get("/tiers", response_model=TierRates)
def read_tier_rates(
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    return TierRates(get_tier_rates(session, user.id))


@router.put("/tiers", response_model=TierRates)
def write_tier_rates(
    rates: TierRates,
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    return TierRates(set_tier_rates(session, user.id, rates.root))

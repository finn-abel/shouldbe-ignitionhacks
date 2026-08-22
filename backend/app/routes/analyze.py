"""Door B — analyze a meeting and record it (doc 2 §5.1). Thin: parse, delegate, return."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.data.db import get_session
from app.data.meetings import save_analysis
from app.data.models import User
from app.data.people import tier_map
from app.data.tiers import get_tier_rates
from app.routes.auth import acting_user
from app.schemas.api import MeetingRead
from app.schemas.invite import ManualMeetingInput
from app.services.pipeline import analyze
from app.services.rate_limit import FixedWindowLimiter, rate_limited

router = APIRouter(prefix="/api", tags=["analyze"])

# Every call here can spend LLM tokens. Generous for a person clicking Analyze, and a
# hard stop for a script pointed at the endpoint.
ANALYZE_LIMIT = FixedWindowLimiter(limit=30, window_seconds=60)


@router.post(
    "/analyze",
    response_model=MeetingRead,
    dependencies=[Depends(rate_limited(ANALYZE_LIMIT))],
)
def analyze_meeting(
    form: ManualMeetingInput,
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    # Priced with this user's own tier rates, so editing them changes what new meetings
    # cost (doc 3 step 9). Meetings already on the books keep the cost they were priced
    # at — a ledger records what happened.
    rates = get_tier_rates(session, user.id)
    analysis = analyze(form.to_parsed_invite(), rates)
    # Door B names no addresses — it asks for head counts per tier — so every seat here is
    # known by construction and there is nobody to identify later. The directory is passed
    # anyway so the "was this a guess?" question has one answer on every door.
    return save_analysis(
        session,
        user.id,
        analysis,
        tier_rates=rates,
        known_people=tier_map(session, user.id),
    )

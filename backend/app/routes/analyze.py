"""Door B — analyze a meeting (doc 2 §5.1). Thin: parse, delegate, return."""

from fastapi import APIRouter

from app.schemas.api import MeetingAnalysis
from app.schemas.invite import ManualMeetingInput
from app.services.pipeline import analyze

router = APIRouter(prefix="/api", tags=["analyze"])


@router.post("/analyze", response_model=MeetingAnalysis)
def analyze_meeting(form: ManualMeetingInput) -> MeetingAnalysis:
    # Persisting the analysis is step 5; this returns it for immediate render.
    return analyze(form.to_parsed_invite())

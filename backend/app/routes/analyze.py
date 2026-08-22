"""Door B — analyze a meeting and record it (doc 2 §5.1). Thin: parse, delegate, return."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.data.db import get_session
from app.data.meetings import save_analysis
from app.data.users import get_acting_user
from app.schemas.api import MeetingRead
from app.schemas.invite import ManualMeetingInput
from app.services.pipeline import analyze

router = APIRouter(prefix="/api", tags=["analyze"])


@router.post("/analyze", response_model=MeetingRead)
def analyze_meeting(form: ManualMeetingInput, session: Session = Depends(get_session)):
    user = get_acting_user(session)
    analysis = analyze(form.to_parsed_invite())
    return save_analysis(session, user.id, analysis)

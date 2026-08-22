"""The meeting ledger (doc 2 §4.4). Thin: parse, delegate, return."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.data.db import get_session
from app.data.meetings import get_meeting, list_meetings
from app.data.users import get_acting_user
from app.schemas.api import MeetingRead

router = APIRouter(prefix="/api", tags=["meetings"])


@router.get("/meetings", response_model=list[MeetingRead])
def read_meetings(session: Session = Depends(get_session)):
    user = get_acting_user(session)
    return list_meetings(session, user.id)


@router.get("/meetings/{meeting_id}", response_model=MeetingRead)
def read_meeting(meeting_id: int, session: Session = Depends(get_session)):
    user = get_acting_user(session)
    meeting = get_meeting(session, user.id, meeting_id)
    if meeting is None:
        # 404 rather than 403 for someone else's meeting: never confirm it exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found.")
    return meeting

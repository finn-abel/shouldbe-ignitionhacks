"""The meeting ledger and its money figures (doc 2 §4.4, §6).

Thin: parse, delegate, return. Every dollar figure is computed in services/money.py.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.data.db import get_session
from app.data.meetings import get_meeting, list_meetings
from app.data.users import get_acting_user
from app.schemas.api import MeetingRead, Stats
from app.services.money import (
    avoidable_spend,
    budget_comparison,
    necessary_spend,
    reclaimed_savings,
    spend_over_time,
    total_spend,
)

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


@router.get("/stats", response_model=Stats)
def read_stats(bucket: Literal["day", "week"] = "day", session: Session = Depends(get_session)):
    user = get_acting_user(session)
    ledger = [MeetingRead.model_validate(m) for m in list_meetings(session, user.id)]
    budget = user.budget.monthly_amount if user.budget else None

    return Stats(
        total_spend=total_spend(ledger),
        necessary_spend=necessary_spend(ledger),
        avoidable_spend=avoidable_spend(ledger),
        reclaimed_savings=reclaimed_savings(ledger),
        spend_over_time=spend_over_time(ledger, bucket),
        budget=budget_comparison(ledger, budget),
    )

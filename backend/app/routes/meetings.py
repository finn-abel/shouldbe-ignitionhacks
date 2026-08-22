"""The meeting ledger and its money figures (doc 2 §4.4, §6).

Thin: parse, delegate, return. Every dollar figure is computed in services/money.py.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.data.db import get_session
from app.data.meetings import NotConvertible, convert_meeting, get_meeting, list_meetings
from app.data.models import User
from app.routes.auth import acting_user
from app.schemas.api import MeetingRead, MeetingStatusUpdate, Stats
from app.services.money import (
    avoidable_spend,
    budget_comparison,
    necessary_spend,
    reclaimed_savings,
    spend_over_time,
    total_spend,
    within_period,
)

router = APIRouter(prefix="/api", tags=["meetings"])


@router.get("/meetings", response_model=list[MeetingRead])
def read_meetings(
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    return list_meetings(session, user.id)


@router.get("/stats", response_model=Stats)
def read_stats(
    bucket: Literal["day", "week"] = "day",
    period: Literal["month", "all"] = "month",
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    ledger = [MeetingRead.model_validate(m) for m in list_meetings(session, user.id)]
    budget = user.budget.monthly_amount if user.budget else None

    # The four figures and the chart cover the requested span; the budget headline always
    # covers the current month, because that is what a monthly budget is measured against.
    scoped = within_period(ledger, period)

    return Stats(
        period=period,
        total_spend=total_spend(scoped),
        necessary_spend=necessary_spend(scoped),
        avoidable_spend=avoidable_spend(scoped),
        reclaimed_savings=reclaimed_savings(scoped),
        spend_over_time=spend_over_time(scoped, bucket),
        budget=budget_comparison(ledger, budget),
    )


@router.get("/meetings/{meeting_id}", response_model=MeetingRead)
def read_meeting(
    meeting_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    meeting = get_meeting(session, user.id, meeting_id)
    if meeting is None:
        # 404 rather than 403 for someone else's meeting: never confirm it exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found.")
    return meeting


@router.patch("/meetings/{meeting_id}", response_model=MeetingRead)
def update_meeting_status(
    meeting_id: int,
    update: MeetingStatusUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    try:
        meeting = convert_meeting(session, user.id, meeting_id)
    except NotConvertible as refusal:
        raise HTTPException(status.HTTP_409_CONFLICT, str(refusal)) from refusal

    if meeting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found.")
    return meeting

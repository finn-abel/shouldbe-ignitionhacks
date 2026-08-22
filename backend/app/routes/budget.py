"""Monthly meeting budget config (doc 2 §4.3). Thin: parse, delegate, return."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.data.budgets import get_budget, set_budget
from app.data.db import get_session
from app.data.models import User
from app.routes.auth import acting_user
from app.schemas.api import BudgetRead, BudgetUpdate

router = APIRouter(prefix="/api", tags=["budget"])


@router.get("/budget", response_model=BudgetRead)
def read_budget(
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    budget = get_budget(session, user.id)
    return BudgetRead(monthly_amount=budget.monthly_amount if budget else None)


@router.put("/budget", response_model=BudgetRead)
def write_budget(
    update: BudgetUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    budget = set_budget(session, user.id, update.monthly_amount)
    return BudgetRead(monthly_amount=budget.monthly_amount)

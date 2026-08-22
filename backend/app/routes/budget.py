"""Monthly meeting budget config and guardrail previews."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.data.budgets import budget_for_scope, get_budget_config, set_budget_config
from app.data.db import get_session
from app.data.meetings import list_meetings
from app.data.models import User
from app.data.tiers import get_tier_rates
from app.routes.auth import acting_user
from app.schemas.api import BudgetGuardrailRead, BudgetRead, BudgetUpdate, MeetingRead, ScopedBudgetUpdate
from app.schemas.invite import ManualMeetingInput
from app.services.costing import meeting_cost
from app.services.money import budget_guardrail

router = APIRouter(prefix="/api", tags=["budget"])


def _budget_read(config) -> BudgetRead:
    return BudgetRead(
        monthly_amount=config.monthly_amount,
        active_scope_type=config.active_scope_type,
        active_scope_name=config.active_scope_name,
        budgets=[
            {
                "scope_type": item.scope_type,
                "scope_name": item.scope_name,
                "monthly_amount": item.monthly_amount,
                "is_active": item.is_active,
            }
            for item in config.budgets
        ],
    )


@router.get("/budget", response_model=BudgetRead)
def read_budget(
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    return _budget_read(get_budget_config(session, user.id))


@router.put("/budget", response_model=BudgetRead)
def write_budget(
    update: BudgetUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    updates = update.budgets
    if updates is None:
        updates = [
            ScopedBudgetUpdate(
                scope_type=update.active_scope_type,
                scope_name=update.active_scope_name,
                monthly_amount=update.monthly_amount,
                is_active=True,
            )
        ]
    config = set_budget_config(
        session,
        user.id,
        updates,
        update.active_scope_type,
        update.active_scope_name,
    )
    return _budget_read(config)


@router.post("/budget/guardrail", response_model=BudgetGuardrailRead)
def preview_budget_guardrail(
    form: ManualMeetingInput,
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    invite = form.to_parsed_invite()
    cost = meeting_cost(invite.attendee_tiers, invite.duration_minutes, get_tier_rates(session, user.id))
    budget = budget_for_scope(session, user.id, invite.budget_scope_type, invite.budget_scope_name)
    ledger = [MeetingRead.model_validate(meeting) for meeting in list_meetings(session, user.id)]

    return budget_guardrail(
        ledger,
        budget.monthly_amount,
        cost,
        scope_type=budget.scope_type,
        scope_name=budget.scope_name,
    )

"""Budget access (doc 2 §4.3) — one monthly meeting-spend budget per user."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Budget


def get_budget(session: Session, user_id: int) -> Budget | None:
    return session.scalar(select(Budget).where(Budget.user_id == user_id))


def set_budget(session: Session, user_id: int, monthly_amount: Decimal) -> Budget:
    """Set the monthly budget, creating the row if the user has none yet."""
    budget = get_budget(session, user_id)
    if budget is None:
        budget = Budget(user_id=user_id, monthly_amount=monthly_amount)
        session.add(budget)
    else:
        budget.monthly_amount = monthly_amount

    session.commit()
    session.refresh(budget)
    return budget

"""User lookup (doc 2 §4.1).

# TEMPORARY: replaced in step 11
Until Google sign-in and guest entry exist (doc 2 §5.5), every request acts as one
find-or-created demo user. Step 11 resolves the acting user from the session instead and
seeds the real shared guest; the rest of the code already scopes every query by user id,
so only this function changes.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Budget, User

DEMO_USER_EMAIL = "demo@shouldbe.local"
DEMO_USER_NAME = "Demo"

# TEMPORARY: replaced in step 11
# The dashboard headline is "spend vs budget", so the demo user needs a budget before
# step 9 builds the editor for it. Step 11's seed script sets the real guest figure.
DEMO_BUDGET = Decimal("3000.00")


def get_acting_user(session: Session) -> User:
    """The user every request currently acts as."""
    user = session.scalar(select(User).where(User.email == DEMO_USER_EMAIL))
    if user is None:
        user = User(email=DEMO_USER_EMAIL, display_name=DEMO_USER_NAME, is_guest=True)
        user.budget = Budget(monthly_amount=DEMO_BUDGET)
        session.add(user)
        session.commit()
        session.refresh(user)
    return user

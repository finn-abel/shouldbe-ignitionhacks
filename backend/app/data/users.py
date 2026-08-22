"""User lookup and entry.

Two ways in, one outcome: Google sign-in resolves to a `User` found or created by its
`google_sub`, "continue as guest" resolves to the single shared `is_guest` row. Both hand
back a real, fully writable user — guest is shared and pre-seeded, never restricted.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data.models import Budget, RoleTierRate, User
from app.services.costing import DEFAULT_TIER_RATES

GUEST_EMAIL = "guest@shouldbe.local"
GUEST_NAME = "Guest"

# What a brand-new signed-in user starts with. The guest's figures come from seed.py.
STARTING_BUDGET = Decimal("6000.00")


def get_user(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def _with_starting_config(user: User) -> User:
    """Every user needs a cost basis before their first meeting can be priced."""
    user.budget = Budget(monthly_amount=STARTING_BUDGET)
    user.tier_rates = [
        RoleTierRate(tier=tier, hourly_rate=rate) for tier, rate in DEFAULT_TIER_RATES.items()
    ]
    return user


def get_or_create_guest(session: Session) -> User:
    """The one shared guest row.

    Normally created by `seed.py` with curated data. Created bare here as a fallback so
    guest entry works even on a database nobody remembered to seed.
    """
    guest = session.scalar(select(User).where(User.is_guest.is_(True)))
    if guest is not None:
        return guest

    guest = _with_starting_config(
        User(email=GUEST_EMAIL, display_name=GUEST_NAME, is_guest=True)
    )
    session.add(guest)
    try:
        session.commit()
    except IntegrityError:
        # Two people pressed "continue as guest" at the same moment on a fresh database.
        # The unique email is what settles it; whoever lost simply reads the winner's row.
        session.rollback()
        return session.scalar(select(User).where(User.email == GUEST_EMAIL))

    session.refresh(guest)
    return guest


def find_or_create_by_google(
    session: Session, google_sub: str, email: str, display_name: str
) -> User:
    """Resolve a Google sign-in to a user, keyed on the stable `sub` claim."""
    user = session.scalar(select(User).where(User.google_sub == google_sub))
    if user is not None:
        return user

    # Someone may have signed in before under the same address; adopt that row rather
    # than colliding on the unique email.
    user = session.scalar(select(User).where(User.email == email))
    if user is not None:
        user.google_sub = google_sub
        session.commit()
        return user

    user = _with_starting_config(
        User(
            email=email,
            display_name=display_name or email.split("@")[0],
            google_sub=google_sub,
            is_guest=False,
        )
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

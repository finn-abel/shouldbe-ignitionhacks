"""Budget access (doc 2 §4.3) — monthly guardrails by user/team/department."""

from dataclasses import dataclass

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Budget, ScopedBudget
from app.enums import BudgetScope
from app.schemas.api import ScopedBudgetUpdate

DEFAULT_SCOPE_NAMES = {
    BudgetScope.USER: "Personal",
    BudgetScope.TEAM: "Team",
    BudgetScope.DEPARTMENT: "Department",
}

BUDGET_SCOPES = (BudgetScope.USER, BudgetScope.TEAM, BudgetScope.DEPARTMENT)


@dataclass(frozen=True)
class BudgetItem:
    scope_type: BudgetScope
    scope_name: str
    monthly_amount: Decimal | None
    is_active: bool = False


@dataclass(frozen=True)
class BudgetConfig:
    active_scope_type: BudgetScope
    active_scope_name: str
    monthly_amount: Decimal | None
    budgets: list[BudgetItem]


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


def _clean_scope_name(scope_type: BudgetScope, scope_name: str | None) -> str:
    text = (scope_name or "").strip()
    return text or DEFAULT_SCOPE_NAMES[scope_type]


def _legacy_budget_item(session: Session, user_id: int) -> BudgetItem:
    budget = get_budget(session, user_id)
    return BudgetItem(
        scope_type=BudgetScope.USER,
        scope_name=DEFAULT_SCOPE_NAMES[BudgetScope.USER],
        monthly_amount=budget.monthly_amount if budget else None,
        is_active=True,
    )


def _scoped_budget_rows(session: Session, user_id: int) -> list[ScopedBudget]:
    return list(
        session.scalars(
            select(ScopedBudget)
            .where(ScopedBudget.user_id == user_id)
            .order_by(ScopedBudget.scope_type, ScopedBudget.scope_name)
        )
    )


def get_budget_config(session: Session, user_id: int) -> BudgetConfig:
    """All configured guardrails, with legacy user budgets folded in."""
    rows = _scoped_budget_rows(session, user_id)
    by_scope = {(row.scope_type, row.scope_name.lower()): row for row in rows}

    items: list[BudgetItem] = []
    for scope_type in BUDGET_SCOPES:
        default_name = DEFAULT_SCOPE_NAMES[scope_type]
        row = next((row for row in rows if row.scope_type is scope_type), None)
        if row is None and scope_type is BudgetScope.USER:
            legacy = _legacy_budget_item(session, user_id)
            items.append(legacy)
            continue

        items.append(
            BudgetItem(
                scope_type=scope_type,
                scope_name=row.scope_name if row else default_name,
                monthly_amount=row.monthly_amount if row else None,
                is_active=bool(row.is_active) if row else False,
            )
        )

    active = next((item for item in items if item.is_active), None)
    if active is None:
        active = next((item for item in items if item.monthly_amount is not None), items[0])
        items = [
            BudgetItem(
                scope_type=item.scope_type,
                scope_name=item.scope_name,
                monthly_amount=item.monthly_amount,
                is_active=item.scope_type is active.scope_type and item.scope_name == active.scope_name,
            )
            for item in items
        ]

    return BudgetConfig(
        active_scope_type=active.scope_type,
        active_scope_name=active.scope_name,
        monthly_amount=active.monthly_amount,
        budgets=items,
    )


def budget_for_scope(
    session: Session,
    user_id: int,
    scope_type: BudgetScope,
    scope_name: str | None,
) -> BudgetItem:
    """The budget configured for a meeting scope, or an unset default item."""
    clean_name = _clean_scope_name(scope_type, scope_name)
    if scope_type is BudgetScope.USER:
        config = get_budget_config(session, user_id)
        user_item = next(
            (item for item in config.budgets if item.scope_type is BudgetScope.USER),
            None,
        )
        if user_item is not None:
            return BudgetItem(BudgetScope.USER, user_item.scope_name, user_item.monthly_amount)

    row = session.scalar(
        select(ScopedBudget).where(
            ScopedBudget.user_id == user_id,
            ScopedBudget.scope_type == scope_type,
            ScopedBudget.scope_name == clean_name,
        )
    )
    return BudgetItem(
        scope_type=scope_type,
        scope_name=clean_name,
        monthly_amount=row.monthly_amount if row else None,
    )


def set_budget_config(
    session: Session,
    user_id: int,
    updates: list[ScopedBudgetUpdate],
    active_scope_type: BudgetScope,
    active_scope_name: str,
) -> BudgetConfig:
    """Replace this user's guardrail settings with the supplied scope rows."""
    existing = {
        (row.scope_type, row.scope_name.lower()): row
        for row in _scoped_budget_rows(session, user_id)
    }
    active_name = _clean_scope_name(active_scope_type, active_scope_name)
    seen_user_amount: Decimal | None = None

    for update in updates:
        scope_type = update.scope_type
        scope_name = _clean_scope_name(scope_type, update.scope_name)
        key = (scope_type, scope_name.lower())
        amount = update.monthly_amount

        if scope_type is BudgetScope.USER:
            seen_user_amount = amount

        row = existing.get(key)
        if amount is None:
            if row is not None:
                session.delete(row)
            continue

        if row is None:
            row = ScopedBudget(
                user_id=user_id,
                scope_type=scope_type,
                scope_name=scope_name,
                monthly_amount=amount,
            )
            session.add(row)
        else:
            row.scope_name = scope_name
            row.monthly_amount = amount
        row.is_active = scope_type is active_scope_type and scope_name.lower() == active_name.lower()

    for row in existing.values():
        if row not in session.deleted and not (
            row.scope_type is active_scope_type and row.scope_name.lower() == active_name.lower()
        ):
            row.is_active = False

    legacy = get_budget(session, user_id)
    if seen_user_amount is None:
        if legacy is not None:
            session.delete(legacy)
    elif legacy is None:
        session.add(Budget(user_id=user_id, monthly_amount=seen_user_amount))
    else:
        legacy.monthly_amount = seen_user_amount

    session.commit()
    return get_budget_config(session, user_id)

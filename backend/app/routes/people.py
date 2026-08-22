"""The people directory (see `data.models.Person`). Thin: parse, delegate, return.

The screen behind these three endpoints answers one question the product could not answer
before: *who was actually in that meeting?* An .ics gives addresses and no roles, so every
emailed meeting was priced as if the whole room were the lowest tier. Placing a person
fixes that meeting and every other one that guessed at them.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.data.db import get_session
from app.data.meetings import identify_people
from app.data.models import Person, User
from app.data.people import (
    delete_person,
    list_people,
    unidentified_addresses,
    upsert_person,
)
from app.data.tiers import get_tier_rates
from app.routes.auth import acting_user
from app.schemas.api import (
    DirectoryRead,
    DirectorySaved,
    PeopleUpdate,
    PersonRead,
    RepricingRead,
    UnidentifiedPerson,
)
from app.services.directory import person_key

router = APIRouter(prefix="/api", tags=["people"])


def _to_read(person: Person, self_key: str) -> PersonRead:
    return PersonRead(
        id=person.id,
        email=person.email,
        tier=person.tier,
        display_name=person.display_name,
        is_self=person.email == self_key,
    )


def _directory(session: Session, user: User) -> DirectoryRead:
    self_key = person_key(user.email)
    people = [_to_read(person, self_key) for person in list_people(session, user.id)]
    counts = unidentified_addresses(session, user.id)

    return DirectoryRead(
        self_email=self_key,
        me=next((person for person in people if person.is_self), None),
        people=people,
        # Busiest first: the address in eleven meetings is the one whose role is actually
        # moving the ledger, and the one worth answering before the rest.
        unidentified=[
            UnidentifiedPerson(email=email, meeting_count=count)
            for email, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ],
    )


@router.get("/people", response_model=DirectoryRead)
def read_directory(
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    return _directory(session, user)


@router.put("/people", response_model=DirectorySaved)
def write_directory(
    update: PeopleUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    """Place people, then correct every meeting that had been guessing at them.

    The two halves are one request on purpose. Saving a role and re-pricing the ledger
    are the same act from the user's side — they are telling the system something true
    that it did not know — and splitting them would leave a window where the directory
    says one thing and the ledger still says another.
    """
    rates = get_tier_rates(session, user.id)

    for entry in update.people:
        try:
            upsert_person(
                session, user.id, entry.email, entry.tier, entry.display_name, commit=False
            )
        except ValueError as bad_address:
            session.rollback()
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, str(bad_address)
            ) from bad_address
    session.commit()

    # After the commit, so a re-price never runs against a directory write that then
    # fails: the meeting correction is the irreversible half. One call for the whole
    # batch, because two of these people are routinely in the same meeting.
    result = identify_people(
        session, user.id, {entry.email: entry.tier for entry in update.people}, rates
    )

    return DirectorySaved(
        directory=_directory(session, user),
        repricing=RepricingRead(
            meetings_repriced=result.meetings_repriced,
            seats_corrected=result.seats_corrected,
            cost_before=result.cost_before,
            cost_after=result.cost_after,
            cost_delta=result.cost_delta,
        ),
    )


@router.delete("/people/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def forget_person(
    person_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(acting_user),
):
    """Remove a directory entry. Meetings keep the cost they were priced at.

    Un-knowing someone is not new information about what a meeting cost, so nothing is
    re-priced and no seat goes back to being a guess. Future meetings will assume again.
    """
    if not delete_person(session, user.id, person_id):
        # 404 rather than 403 for someone else's entry: never confirm it exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such person in your directory.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

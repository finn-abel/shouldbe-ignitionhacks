"""The people directory — who a user knows, and at which role tier (see `Person`).

Every read and write is scoped by `user_id`. A directory is one account's view of its
colleagues; nothing here is global, and one user's entry never prices another's meeting.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Meeting, MeetingAttendee, Person
from app.enums import Tier
from app.services.directory import person_key


def list_people(session: Session, user_id: int) -> list[Person]:
    """The user's directory, alphabetically — the order a person scans a list in."""
    return list(
        session.scalars(
            select(Person).where(Person.user_id == user_id).order_by(Person.email)
        )
    )


def tier_map(session: Session, user_id: int) -> dict[str, Tier]:
    """The directory in the shape `services.directory.seats_for` takes.

    One query per analysis rather than one per attendee: an 18-person invite is a single
    round trip.
    """
    return {
        person.email: person.tier
        for person in session.scalars(select(Person).where(Person.user_id == user_id))
    }


def get_person(session: Session, user_id: int, person_id: int) -> Person | None:
    """One entry, or None when it does not exist *or* belongs to someone else."""
    return session.scalar(
        select(Person).where(Person.id == person_id, Person.user_id == user_id)
    )


def upsert_person(
    session: Session,
    user_id: int,
    email: str,
    tier: Tier,
    display_name: str | None = None,
    commit: bool = True,
) -> Person:
    """Place a person at a tier, by address. Re-placing the same address updates them.

    Upsert rather than insert because the address is the identity: the natural way to fix
    a wrong tier is to say the person's role again, and that must not collide with the
    unique constraint or leave two rows disagreeing about one colleague.
    """
    key = person_key(email)
    if not key:
        raise ValueError(f"{email!r} is not an email address.")

    existing = session.scalar(
        select(Person).where(Person.user_id == user_id, Person.email == key)
    )
    if existing is None:
        existing = Person(user_id=user_id, email=key, tier=tier, display_name=display_name)
        session.add(existing)
    else:
        existing.tier = tier
        if display_name is not None:
            existing.display_name = display_name

    if commit:
        session.commit()
        session.refresh(existing)
    return existing


def delete_person(session: Session, user_id: int, person_id: int) -> bool:
    """Forget a person. Meetings keep the cost they were priced at.

    Deliberately not a re-price: the seats they were in were priced on a *known* tier at
    the time, and un-knowing something is not new information about what a meeting cost.
    """
    person = get_person(session, user_id, person_id)
    if person is None:
        return False
    session.delete(person)
    session.commit()
    return True


def unidentified_addresses(session: Session, user_id: int) -> dict[str, int]:
    """Addresses seen in this user's meetings that nobody has placed, and how often.

    The worklist behind "go back and say who these people are". Driven off the stored
    `is_assumed` flag rather than a live directory diff, so a seat that was priced on a
    guess keeps saying so until it is actually corrected.
    """
    rows = session.execute(
        select(MeetingAttendee.email, MeetingAttendee.meeting_id)
        .join(Meeting, Meeting.id == MeetingAttendee.meeting_id)
        .where(
            Meeting.user_id == user_id,
            MeetingAttendee.is_assumed.is_(True),
            MeetingAttendee.email != "",
        )
    )

    # Distinct meetings, not seats. The UI says "in 3 meetings", and an invite that lists
    # the same address twice would otherwise make that sentence a lie.
    seen: dict[str, set[int]] = {}
    for email, meeting_id in rows:
        seen.setdefault(email, set()).add(meeting_id)
    return {email: len(meetings) for email, meetings in seen.items()}

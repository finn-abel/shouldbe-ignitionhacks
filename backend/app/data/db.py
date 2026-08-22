"""Engine, session factory, and the create-all bootstrap (doc 2 §3.5, doc 4 task 4-B).

The database URL comes from the environment, so SQLite locally and Render Postgres in
the cloud are the same code path — a config change, not a code change.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DEFAULT_DATABASE_URL = "sqlite:///./shouldbe.db"

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

# SQLite refuses cross-thread connection sharing by default, which FastAPI's threadpool
# does routinely. Postgres needs no such argument.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for every ORM entity in doc 2 §4."""


def init_db():
    """Create any missing tables. Imported models register themselves on Base.metadata."""
    from app.data import models  # noqa: F401  (import registers the mappings)

    Base.metadata.create_all(bind=engine)

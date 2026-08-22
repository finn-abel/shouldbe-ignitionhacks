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


def _normalize_url(url: str) -> str:
    """Make a hosted Postgres URL something SQLAlchemy 2.x will actually accept.

    Render (and Heroku before it) hands out `postgres://`, a scheme SQLAlchemy dropped in
    1.4 — left alone it raises `Can't load plugin: sqlalchemy.dialects:postgres` at import
    time, before a single line of app code runs.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


DATABASE_URL = _normalize_url(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))

IS_SQLITE = DATABASE_URL.startswith("sqlite")

# SQLite refuses cross-thread connection sharing by default, which FastAPI's threadpool
# does routinely. Postgres needs no such argument.
_connect_args = {"check_same_thread": False} if IS_SQLITE else {}

# A hosted Postgres closes connections the pool still believes are open — an idle
# free-tier database, a maintenance restart, a web service waking from spin-down. Without
# pre-ping the first request after any of those dies on a stale socket, which in a demo
# reads as "the app is broken" rather than "the first click was slow".
_engine_kwargs = {} if IS_SQLITE else {"pool_pre_ping": True, "pool_recycle": 300}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for every ORM entity in doc 2 §4."""


def get_session():
    """FastAPI dependency: one session per request, always closed."""
    with SessionLocal() as session:
        yield session


def init_db():
    """Create any missing tables. Imported models register themselves on Base.metadata."""
    from app.data import models  # noqa: F401  (import registers the mappings)

    Base.metadata.create_all(bind=engine)

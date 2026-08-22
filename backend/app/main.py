"""ShouldBe backend — app wiring only (doc 2 §3.5).

Routes stay thin, services hold all logic, data holds persistence. Nothing in this
module does any work beyond assembling the app.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.data.db import init_db
from app.routes import analyze, auth, budget, inbound_route, meetings, tiers, webhook
from app.seed import seed_if_empty
from app.services.email import drain_outbox_in_new_session

load_dotenv()

DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"
DEFAULT_SESSION_SECRET = "dev-only-not-a-real-secret"

# How often the outbox is swept for replies that could not be sent on their first try.
# The interval only matters while something is broken, so it is deliberately unhurried.
DEFAULT_DRAIN_SECONDS = 120

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


async def _drain_forever(interval: float):
    """Retry queued replies in the background, forever.

    This is what makes a brand-new Postmark account a non-event: until the account is
    manually approved it refuses any recipient outside your own verified domains, so those
    replies sit QUEUED. When approval lands they send themselves with nobody watching.
    """
    while True:
        try:
            await asyncio.sleep(interval)
            sent = await asyncio.to_thread(drain_outbox_in_new_session)
            if sent:
                logger.info("Outbox drain sent %s repl%s.", sent, "y" if sent == 1 else "ies")
        except asyncio.CancelledError:
            raise
        except Exception:
            # A drain that raises must not kill the loop; the next tick tries again.
            logger.exception("Outbox drain failed; will retry in %ss.", interval)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()

    # A freshly provisioned Render Postgres is empty, and nobody demos an empty dashboard.
    # Off by default so a local run is never surprised by rows it did not ask for; the
    # seed itself declines to overwrite a ledger that already has meetings in it.
    if _env_flag("SHOULDBE_SEED_ON_START", False):
        try:
            seeded = await asyncio.to_thread(seed_if_empty)
            if seeded is not None:
                logger.info("Seeded the guest user (id=%s) on an empty database.", seeded)
        except Exception:
            # A failed seed is a cosmetic problem; refusing to boot over it is not.
            logger.exception("Startup seed failed; the app is starting with no demo data.")

    # Anything stranded by a restart between commit and send.
    try:
        await asyncio.to_thread(drain_outbox_in_new_session)
    except Exception:
        logger.exception("Startup outbox drain failed; the periodic drain will retry.")

    interval = float(os.getenv("OUTBOX_DRAIN_SECONDS", DEFAULT_DRAIN_SECONDS))
    drainer = asyncio.create_task(_drain_forever(interval)) if interval > 0 else None

    yield

    if drainer is not None:
        drainer.cancel()
        try:
            await drainer
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="ShouldBe",
    description="Meeting spend management.",
    lifespan=lifespan,
)

# The session cookie carries the acting user id (doc 2 §5.5).
#
# `lax` is right locally, where the frontend and the API are both on localhost and so
# count as the same site. Deployed they are not: a Render Static Site and a Render Web
# Service are different hosts, and a SameSite=Lax cookie is NOT attached to a cross-site
# XHR — every API call would come back 401. Set SESSION_COOKIE_SAMESITE=none and
# SESSION_COOKIE_SECURE=true there (browsers require Secure whenever SameSite is None).
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", DEFAULT_SESSION_SECRET),
    same_site=os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower(),
    https_only=_env_flag("SESSION_COOKIE_SECURE", False),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", DEFAULT_FRONTEND_ORIGIN)],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (analyze, meetings, budget, tiers, auth, webhook, inbound_route):
    app.include_router(module.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}

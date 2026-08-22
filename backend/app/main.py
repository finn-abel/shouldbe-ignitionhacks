"""ShouldBe backend — app wiring only (doc 2 §3.5).

Routes stay thin, services hold all logic, data holds persistence. Nothing in this
module does any work beyond assembling the app.
"""

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import env_flag, is_deployed
from app.data.db import init_db
from app.routes import analyze, auth, budget, inbound_route, meetings, people, tiers, webhook
from app.seed import seed_if_empty
from app.services.email import drain_outbox_in_new_session

load_dotenv()

DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"

# How often the outbox is swept for replies that could not be sent on their first try.
# The interval only matters while something is broken, so it is deliberately unhurried.
DEFAULT_DRAIN_SECONDS = 120

logger = logging.getLogger(__name__)


def _session_secret() -> str:
    """The key the session cookie is signed with. Never a shared constant.

    This used to fall back to a fixed string committed to this file, which meant an
    unset SESSION_SECRET did not disable sessions — it published the signing key. Anyone
    reading the repo could mint a cookie for any `user_id` and be that user.

    Deployed, an unset secret is now a refusal to boot: there is no safe guess to make,
    and a deploy that fails loudly at startup beats one that serves forgeable sessions.
    Locally it is a random per-process key, so `uvicorn app.main:app` still just runs on a
    bare checkout — a restart signs you out, which is the whole cost.
    """
    configured = (os.getenv("SESSION_SECRET") or "").strip()
    if configured:
        return configured

    if is_deployed():
        raise RuntimeError(
            "SESSION_SECRET is unset. It signs the session cookie, so without it every "
            "session is forgeable. Set it to a long random value (render.yaml generates "
            "one automatically) and redeploy."
        )

    logger.warning(
        "SESSION_SECRET is unset; signing sessions with a random per-process key. "
        "Sessions will not survive a restart. Set SESSION_SECRET in backend/.env."
    )
    return secrets.token_urlsafe(32)


def _warn_if_no_inbox() -> None:
    """Say so at boot when a deployed instance is handing out placeholder addresses.

    `invite_address_for` falls back to `ledger+<token>@example.invalid` when
    SHOULDBE_INBOX is unset, which is right locally and near-invisible in the cloud: the
    app looks healthy, every user's email door is quietly undeliverable, and the only
    signal is a line of small print in the UI. Not a refusal to boot — inbound email is
    an optional upgrade and a demo without it is a working demo — but it should never
    again be something you find out by reading the address.
    """
    if not is_deployed() or (os.getenv("SHOULDBE_INBOX") or "").strip():
        return

    logger.warning(
        "SHOULDBE_INBOX is unset. Every invite address will render as the "
        "example.invalid placeholder and no invite can reach this instance. Set it to "
        "the address whose domain has MX pointed at inbound.postmarkapp.com."
    )


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
    _warn_if_no_inbox()

    # A freshly provisioned Render Postgres is empty, and nobody demos an empty dashboard.
    # Off by default so a local run is never surprised by rows it did not ask for; the
    # seed itself declines to overwrite a ledger that already has meetings in it.
    if env_flag("SHOULDBE_SEED_ON_START", False):
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


# The interactive docs publish the whole API surface, including the shape of every write.
# Useful while building, not something to leave open on a public host.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
_docs_enabled = not is_deployed() or env_flag("SHOULDBE_PUBLIC_DOCS", False)

app = FastAPI(
    title="ShouldBe",
    description="Meeting spend management.",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# Methods that cannot change anything, so an unrecognised Origin on them is harmless.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _allowed_origins() -> set[str]:
    return {os.getenv("FRONTEND_ORIGIN", DEFAULT_FRONTEND_ORIGIN).rstrip("/")}


@app.middleware("http")
async def enforce_origin_on_writes(request, call_next):
    """Reject cross-site writes that CORS never gets a chance to stop.

    CORS protects the JSON endpoints for free: `Content-Type: application/json` is not a
    "simple" request, so the browser preflights it and the allowlist answers. But a plain
    form POST *is* simple — no preflight, request goes through, and only the response is
    hidden from the attacker. That was enough to hit the two endpoints that read no body:
    a third-party page could force-logout a visitor, or swap them into the shared guest
    session, both of which matter more now that the deployed cookie is SameSite=None.

    Browsers send `Origin` on every unsafe-method request, so checking it closes that gap.
    A missing Origin is allowed through: that is curl, or Postmark posting an invite, and
    neither is a browser carrying somebody's cookie.
    """
    origin = request.headers.get("origin")
    if request.method not in SAFE_METHODS and origin is not None:
        same_origin = origin.rstrip("/") == str(request.base_url).rstrip("/")
        if not same_origin and origin.rstrip("/") not in _allowed_origins():
            return JSONResponse(
                {"detail": "Cross-origin request refused."},
                status_code=403,
            )
    return await call_next(request)


@app.middleware("http")
async def security_headers(request, call_next):
    """Baseline response headers. The API serves JSON, so it can lock down hard."""
    response = await call_next(request)

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    # Swagger UI pulls its own CSS and JS, so the one route that is not JSON opts out.
    if not request.url.path.startswith(_DOCS_PATHS):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )

    # Only meaningful over https, and actively unhelpful on a localhost http listener.
    if is_deployed():
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )

    return response

# The session cookie carries the acting user id (doc 2 §5.5).
#
# `lax` is right locally, where the frontend and the API are both on localhost and so
# count as the same site. Deployed they are not: a Render Static Site and a Render Web
# Service are different hosts, and a SameSite=Lax cookie is NOT attached to a cross-site
# XHR — every API call would come back 401. Set SESSION_COOKIE_SAMESITE=none and
# SESSION_COOKIE_SECURE=true there (browsers require Secure whenever SameSite is None).
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret(),
    same_site=os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower(),
    https_only=env_flag("SESSION_COOKIE_SECURE", False),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", DEFAULT_FRONTEND_ORIGIN)],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (analyze, meetings, budget, tiers, people, auth, webhook, inbound_route):
    app.include_router(module.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}

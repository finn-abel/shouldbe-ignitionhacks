"""ShouldBe backend — app wiring only (doc 2 §3.5).

Routes stay thin, services hold all logic, data holds persistence. Nothing in this
module does any work beyond assembling the app.
"""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.data.db import init_db
from app.routes import analyze, auth, budget, meetings, tiers, webhook

load_dotenv()

DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"
DEFAULT_SESSION_SECRET = "dev-only-not-a-real-secret"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


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

for module in (analyze, meetings, budget, tiers, auth, webhook):
    app.include_router(module.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}

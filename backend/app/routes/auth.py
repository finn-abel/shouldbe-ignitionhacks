"""Entry: Google sign-in and guest (doc 2 §5.5). Thin: parse, delegate, return.

Also owns `acting_user`, the dependency every other router uses to resolve the session
to a `User`. It lives here because the session *is* the auth concern; the routes that
depend on it never touch cookies themselves.
"""

import os

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.data.db import get_session
from app.data.models import User
from app.data.users import find_or_create_by_google, get_or_create_guest, get_user
from app.schemas.api import UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_USER_KEY = "user_id"
GOOGLE_DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"

# Basic profile only — deliberately NOT calendar. These scopes are not sensitive, so
# Google requires no verification review and shows no "unverified app" wall (doc 4 4-D).
GOOGLE_SCOPES = "openid email profile"


def _frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:5173")


def _google_client():
    """The configured Google client, or None when no credentials are present."""
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=GOOGLE_DISCOVERY,
        client_kwargs={"scope": GOOGLE_SCOPES},
    )
    return oauth.google


def acting_user(request: Request, session: Session = Depends(get_session)) -> User:
    """The user this request acts as. Every scoped query hangs off this."""
    user_id = request.session.get(SESSION_USER_KEY)
    user = get_user(session, user_id) if user_id else None
    if user is None:
        request.session.pop(SESSION_USER_KEY, None)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in or continue as guest.")
    return user


@router.get("/me", response_model=UserRead)
def read_me(user: User = Depends(acting_user)):
    return user


@router.post("/guest", response_model=UserRead)
def enter_as_guest(request: Request, session: Session = Depends(get_session)):
    """Continue as guest — a real, writable, pre-seeded user, not a restricted mode."""
    guest = get_or_create_guest(session)
    request.session[SESSION_USER_KEY] = guest.id
    return guest


@router.post("/logout")
def logout(request: Request):
    request.session.pop(SESSION_USER_KEY, None)
    return {"status": "ok"}


@router.get("/google/login")
async def google_login(request: Request):
    google = _google_client()
    if google is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google sign-in is not configured. Continue as guest instead.",
        )
    return await google.authorize_redirect(request, str(request.url_for("google_callback")))


@router.get("/google/callback", name="google_callback")
async def google_callback(request: Request, session: Session = Depends(get_session)):
    google = _google_client()
    if google is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Google sign-in is not configured."
        )

    try:
        token = await google.authorize_access_token(request)
    except OAuthError as failure:
        # Never strand the browser on a JSON error page mid-sign-in.
        return RedirectResponse(f"{_frontend_url()}?auth_error={failure.error}")

    claims = token.get("userinfo") or {}
    if not claims.get("sub") or not claims.get("email"):
        return RedirectResponse(f"{_frontend_url()}?auth_error=missing_profile")

    user = find_or_create_by_google(
        session, claims["sub"], claims["email"], claims.get("name", "")
    )
    request.session[SESSION_USER_KEY] = user.id
    return RedirectResponse(_frontend_url())

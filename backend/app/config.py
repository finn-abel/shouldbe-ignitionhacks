"""Deployment-shape questions the rest of the app asks before it fails open.

A handful of settings are safe to leave unset on a laptop and dangerous to leave unset on
a public host — the session secret above all, the inbound webhook secret right behind it.
Every one of them used to degrade silently to "no protection at all", which is the right
default for `uvicorn app.main:app` on localhost and the wrong one everywhere else.

`is_deployed()` is what lets both behaviours coexist: unset stays convenient locally and
becomes a refusal to boot in the cloud. The signal is deliberately something that is only
ever true off a laptop, so nothing has to remember to set an extra flag.
"""

import os

# Explicit wins over inference, for anyone whose deployment does not look like Render's.
ENV_VAR = "SHOULDBE_ENV"
PRODUCTION_VALUES = frozenset({"production", "prod", "deployed", "staging"})
LOCAL_VALUES = frozenset({"local", "development", "dev", "test"})


def env_flag(name: str, default: bool = False) -> bool:
    """An env var read as a boolean. Anything unrecognised is False, not an error."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_deployed() -> bool:
    """True when this process is serving something other than a developer's laptop.

    Inferred from `SESSION_COOKIE_SECURE`, which is the one setting that is *meaningless*
    locally and *required* in the cloud: a Secure cookie is dropped over plain http, so
    nobody sets it on localhost, and the deployed app is broken without it (render.yaml
    sets it alongside SameSite=None). That makes it a far more reliable "am I public?"
    signal than a flag someone has to remember.
    """
    declared = (os.getenv(ENV_VAR) or "").strip().lower()
    if declared in PRODUCTION_VALUES:
        return True
    if declared in LOCAL_VALUES:
        return False
    return env_flag("SESSION_COOKIE_SECURE", False)

"""Suite-wide guards for anything that could leave the machine.

Two things are arranged here, and they pull in opposite directions on purpose.

Outbound email is suppressed by default outside a deployment (see `email._dry_run`),
because `load_dotenv()` loads a developer's real provider key into *any* local run. That
default is right for a laptop and wrong for the tests that exist specifically to pin how
provider responses are classified — so the tests opt back into the real code path.

Which would be a nice way to mail a stranger from a verified domain if a test ever forgot
to mock the transport. So the transport is replaced with something that fails loudly, and
a test that wants to exercise a send has to say so by patching it itself.
"""

import httpx
import pytest


@pytest.fixture(autouse=True)
def scoring_stays_offline(monkeypatch):
    """Never spend the developer's LLM budget to run the tests.

    `load_dotenv()` runs at import of `app.main`, so the moment any test builds the app it
    loads the developer's real `SHOULDBE_USE_STUB=0` and API key into the process — and
    every test after it in the same session quietly makes live provider calls. That is not
    hypothetical: it took this suite from 2 seconds to several minutes and billed a real
    account for it, while the guard below sat one layer too low to catch it (the provider
    SDKs use their own HTTP clients, not `httpx.post`).

    Tests that exercise the real-provider path patch `_call_openai` / `_call_anthropic`
    themselves, so forcing the stub on here costs them nothing.
    """
    monkeypatch.setenv("SHOULDBE_USE_STUB", "1")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def no_unmocked_outbound_http(monkeypatch):
    """Exercise the real send path, but make an unmocked HTTP call a test failure."""
    monkeypatch.setenv("SHOULDBE_EMAIL_LIVE", "1")

    def _refuse(url, **kwargs):
        raise AssertionError(
            f"A test tried to make a real HTTP request to {url}. Patch "
            "`email_service.httpx.post` (see `capture` in test_email_providers.py) "
            "instead of letting it out."
        )

    monkeypatch.setattr(httpx, "post", _refuse)

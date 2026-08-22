"""Outbound goes through one of two providers; inbound is always Postmark.

The seam exists for a scheduling reason, not an architectural one: a new Postmark account
refuses every recipient outside your own verified domains until a human approves it, which
can outlast a hackathon. Resend gates the same thing on domain verification alone.

What matters most here is failure *classification*. Calling a temporary failure permanent
buries a reply that would have sent itself minutes later, so the tests below pin which
errors are allowed to be fatal.
"""

import httpx
import pytest

from app.services import email as email_service
from app.services.email import SendOutcome, _outbound_provider, _post_to_provider

EMAIL_ENV_VARS = (
    "EMAIL_PROVIDER", "POSTMARK_TOKEN", "POSTMARK_FROM", "POSTMARK_STREAM",
    "RESEND_API_KEY", "RESEND_FROM",
)


@pytest.fixture(autouse=True)
def isolated_email_env(monkeypatch):
    for name in EMAIL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def capture(monkeypatch, status_code=200, body=None, raises=None):
    """Record the outgoing request instead of making one."""
    seen = {}

    def _post(url, **kwargs):
        seen["url"] = url
        seen["json"] = kwargs.get("json")
        seen["headers"] = kwargs.get("headers")
        if raises is not None:
            raise raises
        return httpx.Response(
            status_code,
            json=body if body is not None else {"id": "abc"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(email_service.httpx, "post", _post)
    return seen


# ------------------------------------------------------------ provider choice


def test_nothing_configured_defaults_to_postmark():
    assert _outbound_provider() == "postmark"


def test_a_resend_key_alone_selects_resend(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    assert _outbound_provider() == "resend"


def test_an_explicit_provider_wins_over_inference(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_PROVIDER", "postmark")
    assert _outbound_provider() == "postmark"


def test_an_unknown_provider_is_reported_not_guessed(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "mailgun")
    # Surfaced as a queued failure rather than a crash that would lose the reply.
    outcome = _post_to_provider("a@b.com", "s", "b")
    assert outcome.ok is False and outcome.permanent is False
    assert "mailgun" in outcome.error


# --------------------------------------------------------- the Resend request


@pytest.fixture
def resend(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM", "shouldbe@shouldbe-ai.me")


def test_resend_request_shape(resend, monkeypatch):
    seen = capture(monkeypatch)

    assert _post_to_provider("dana@acme.example", "Subject", "Body", "key-1").ok

    assert seen["url"] == "https://api.resend.com/emails"
    assert seen["headers"]["Authorization"] == "Bearer re_test"
    assert seen["json"] == {
        "from": "shouldbe@shouldbe-ai.me",
        "to": ["dana@acme.example"],
        "subject": "Subject",
        "text": "Body",
    }


def test_resend_sends_an_idempotency_key(resend, monkeypatch):
    """A drain that times out after Resend accepted the message must not resend it."""
    seen = capture(monkeypatch)
    _post_to_provider("dana@acme.example", "s", "b", "shouldbe-outbox-7")
    assert seen["headers"]["Idempotency-Key"] == "shouldbe-outbox-7"


def test_resend_falls_back_to_postmark_from(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("POSTMARK_FROM", "shouldbe@shouldbe-ai.me")
    seen = capture(monkeypatch)
    _post_to_provider("dana@acme.example", "s", "b")
    assert seen["json"]["from"] == "shouldbe@shouldbe-ai.me"


def test_resend_accepts_200_and_201(resend, monkeypatch):
    for code in (200, 201):
        capture(monkeypatch, status_code=code)
        assert _post_to_provider("dana@acme.example", "s", "b").ok


# ------------------------------------------- Resend failure classification


def test_an_unverified_resend_domain_is_temporary(resend, monkeypatch):
    """The operator fixes this with DNS while the reply waits. Never bury it."""
    capture(monkeypatch, status_code=403, body={
        "name": "validation_error",
        "message": "You can only send testing emails to your own email address.",
    })
    outcome = _post_to_provider("dana@acme.example", "s", "b")
    assert outcome.ok is False
    assert outcome.permanent is False


def test_a_rate_limit_is_temporary(resend, monkeypatch):
    capture(monkeypatch, status_code=429, body={
        "name": "rate_limit_exceeded", "message": "Too many requests."})
    assert _post_to_provider("dana@acme.example", "s", "b").permanent is False


def test_a_missing_key_is_temporary(resend, monkeypatch):
    capture(monkeypatch, status_code=401, body={
        "name": "missing_api_key", "message": "Missing API key."})
    assert _post_to_provider("dana@acme.example", "s", "b").permanent is False


def test_a_server_error_is_temporary(resend, monkeypatch):
    capture(monkeypatch, status_code=500, body={"name": "internal", "message": "boom"})
    assert _post_to_provider("dana@acme.example", "s", "b").permanent is False


def test_a_network_error_is_temporary(resend, monkeypatch):
    capture(monkeypatch, raises=httpx.ConnectError("no route"))
    assert _post_to_provider("dana@acme.example", "s", "b").permanent is False


def test_a_malformed_request_is_permanent(resend, monkeypatch):
    capture(monkeypatch, status_code=422, body={
        "name": "validation_error", "message": "Invalid `to` field."})
    assert _post_to_provider("dana@acme.example", "s", "b").permanent is True


def test_no_recipient_is_permanent(resend, monkeypatch):
    capture(monkeypatch)
    assert _post_to_provider("", "s", "b").permanent is True


def test_no_sender_configured_is_temporary(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    outcome = _post_to_provider("dana@acme.example", "s", "b")
    assert outcome.ok is False and outcome.permanent is False


# ------------------------------------------------- Postmark still works


def test_postmark_request_shape(monkeypatch):
    monkeypatch.setenv("POSTMARK_TOKEN", "pm-test")
    monkeypatch.setenv("POSTMARK_FROM", "shouldbe@shouldbe-ai.me")
    seen = capture(monkeypatch, body={"ErrorCode": 0})

    assert _post_to_provider("dana@acme.example", "Subject", "Body").ok

    assert seen["url"] == "https://api.postmarkapp.com/email"
    assert seen["headers"]["X-Postmark-Server-Token"] == "pm-test"
    assert seen["json"]["To"] == "dana@acme.example"
    assert seen["json"]["MessageStream"] == "outbound"


def test_postmark_pending_approval_is_still_temporary(monkeypatch):
    monkeypatch.setenv("POSTMARK_TOKEN", "pm-test")
    monkeypatch.setenv("POSTMARK_FROM", "shouldbe@shouldbe-ai.me")
    capture(monkeypatch, status_code=422, body={
        "ErrorCode": 412, "Message": "While your account is pending approval..."})
    assert _post_to_provider("dana@acme.example", "s", "b").permanent is False


# --------------------------------- one decision, one wording, everywhere it is read


def test_the_reply_subject_states_the_verdict_the_dashboard_states():
    """The organizer and the ledger owner must be shown the same sentence.

    These had drifted into three phrasings of one decision — "Should be an email" on the
    dashboard, "Worth the room" in the ledger, "could be an email" in the subject line —
    so the person who received the reply and the person reading the ledger were looking at
    the same verdict described differently.
    """
    from app.enums import Tier, Verdict
    from app.schemas.invite import ParsedInvite
    from app.services.email import compose_reply
    from app.services.pipeline import analyze

    flagged = analyze(ParsedInvite(
        title="Weekly status update",
        description="Each workstream posts where it got to.",
        attendee_tiers=[Tier.IC] * 8,
    ))
    kept = analyze(ParsedInvite(
        title="Q4 pricing decision",
        description="We need to agree the floor before the board meets.",
        attendee_tiers=[Tier.EXEC] * 3,
    ))

    assert flagged.verdict is Verdict.EMAIL
    assert kept.verdict is Verdict.KEEP
    assert compose_reply(flagged)[0].startswith(f"{flagged.title} — {Verdict.EMAIL.label}")
    assert compose_reply(kept)[0].startswith(f"{kept.title} — {Verdict.KEEP.label}")

    # And the body says it the same way as its own subject, not a second phrasing.
    subject, body = compose_reply(flagged)
    assert Verdict.EMAIL.label in body


def test_the_verdict_wording_matches_the_frontend_copy():
    """The two live in different languages, so this keeps them aligned."""
    import re
    from pathlib import Path

    from app.enums import Verdict

    source = (Path(__file__).resolve().parents[2] / "frontend/src/lib/verdict.js").read_text()
    labels = dict(re.findall(r"(\w+):\s*\{\s*label:\s*'([^']+)'", source))

    assert labels == {
        "email": Verdict.EMAIL.label,
        "keep": Verdict.KEEP.label,
    }, "frontend/src/lib/verdict.js and app/enums.py disagree about the wording"

"""Necessity scoring and the LLM stub seam (doc 2 §8).

The whole system runs against the stub with no API key: `_call_llm` is the single
function that changes in step 12, and it returns the same JSON shape either way, so
nothing downstream of it knows which branch ran.

Two rules from doc 1 §59-61 are enforced here rather than trusted to the model:
the drafted alternative email carries **no cost figures**, and nothing carries
individual-level data. `score_meeting` is otherwise pure — no DB, no HTTP.
"""

import json
import logging
import os
import re
from decimal import Decimal

from app.enums import Verdict

logger = logging.getLogger(__name__)

# Model string taken from the current provider reference, not from memory — a stale
# identifier is a silent failure (doc 4 task 4-E).
LLM_MODEL = "claude-opus-5"

# Enough room for the reasoning plus a drafted email, with margin.
LLM_MAX_TOKENS = 4000

# This is a short classification with a short piece of writing attached, not a research
# task. Medium keeps the interactive Door B path responsive.
LLM_EFFORT = "medium"

# Score bands. The rubric deliberately *defends* necessary meetings (doc 1 §70), so an
# honestly ambiguous meeting keeps its slot rather than being flagged.
SCORE_RECURRING_ASYNC = 3
SCORE_ASYNC = 4
SCORE_AMBIGUOUS = 6
SCORE_CLEARLY_LIVE = 8
SCORE_NEUTRAL_FALLBACK = 5

SCORE_MIN = 1
SCORE_MAX = 10

# Stub heuristic vocabulary. Matched on word boundaries so "sync" does not fire on
# "asynchronous".
ASYNC_SIGNALS = (
    "standup", "stand-up", "status", "update", "updates", "sync", "fyi",
    "readout", "read-out", "recap", "check-in", "checkin", "roundup", "round-up",
)
LIVE_SIGNALS = (
    "decision", "decide", "kickoff", "kick-off", "planning", "retro", "retrospective",
    "brainstorm", "interview", "1:1", "one-on-one", "negotiation", "escalation",
    "postmortem", "post-mortem", "workshop", "debate",
)

RUBRIC = """\
A meeting STAYS A MEETING when it needs people in the room at the same time:
real-time decisions, genuine debate or disagreement, relational or sensitive
conversations (feedback, conflict, onboarding, bad news), and genuinely complex
topics where back-and-forth is faster than writing.

A meeting COULD BE AN EMAIL when the same value survives being written down:
status updates, one-directional information sharing, read-outs of finished work,
recurring syncs with no decision on the agenda, and anything whose agenda is a list
of things people will say in turn.

Score 1-10, where 1 is certainly an email and 10 is certainly a meeting. Use 5-6 when
the meeting is honestly ambiguous. Defend necessary meetings — do not flag everything.\
"""


def _stub_enabled() -> bool:
    """Stub is ON unless explicitly switched off, so the app runs with no key by default."""
    raw = os.getenv("SHOULDBE_USE_STUB")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _matches(text: str, signals: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(s)}(?!\w)", text) for s in signals)


def build_prompt(
    *,
    title: str,
    description: str,
    duration_minutes: int,
    attendee_count: int,
    is_recurring: bool,
    recurrence_freq: str | None,
    cost: Decimal,
) -> str:
    """Assemble the rubric, this meeting's facts, and its cost into the scoring prompt."""
    recurrence = (
        f"yes, {recurrence_freq}" if is_recurring and recurrence_freq else
        "yes" if is_recurring else "no"
    )
    return f"""\
You assess whether a meeting needs to happen live, for a meeting spend-management tool.

{RUBRIC}

The meeting:
- Title: {title}
- Agenda/description: {description or "(none given)"}
- Duration: {duration_minutes} minutes
- Attendees: {attendee_count}
- Recurring: {recurrence}
- Aggregate cost of this occurrence: ${cost}

Reply with JSON only, no prose and no code fences:
{{"score": <int {SCORE_MIN}-{SCORE_MAX}>,
  "verdict": "keep" | "email",
  "reasoning": "<2-3 sentences specific to THIS meeting>",
  "alternative_email": "<the email that replaces the meeting, or null>"}}

Rules:
- "keep" means it needs to be live; "email" means it could be handled asynchronously.
- Set alternative_email to null when the verdict is "keep".
- When the verdict is "email", write the actual email the organizer could send instead:
  a subject line and a short body covering what the meeting would have covered.
- The email must NOT mention cost, budget, dollar figures, or any individual person's
  rate or salary. It is about the meeting's topic, not its price.\
"""


def _stub_response(
    *,
    title: str,
    description: str,
    duration_minutes: int,
    attendee_count: int,
    is_recurring: bool,
) -> str:
    """Deterministic canned JSON that roughly mimics the rubric — no key, no network."""
    haystack = f"{title} {description}".lower()

    if _matches(haystack, ASYNC_SIGNALS):
        score = SCORE_RECURRING_ASYNC if is_recurring else SCORE_ASYNC
        verdict = Verdict.EMAIL
    elif _matches(haystack, LIVE_SIGNALS):
        score, verdict = SCORE_CLEARLY_LIVE, Verdict.KEEP
    else:
        score, verdict = SCORE_AMBIGUOUS, Verdict.KEEP

    cadence = "This is a recurring commitment, so the cost repeats every occurrence. " if is_recurring else ""

    if verdict is Verdict.EMAIL:
        reasoning = (
            f'"{title}" reads as information moving in one direction rather than a '
            f"decision that needs {attendee_count} people present. {cadence}"
            f"The same {duration_minutes} minutes of content survives being written down."
        )
        alternative_email = (
            f"Subject: {title} — written update\n\n"
            "Hi all,\n\n"
            f"Rather than hold the {duration_minutes}-minute session, here is the update in writing.\n\n"
            "- What changed since last time:\n"
            "- What is in progress:\n"
            "- What is blocked, and what I need from you:\n\n"
            "Reply here if anything needs discussion and we will pick it up live then.\n\n"
            "Thanks!"
        )
    else:
        reasoning = (
            f'"{title}" looks like it needs people in the room at the same time — the kind '
            f"of back-and-forth that is slower in writing than it is out loud. {cadence}"
            f"Keeping {attendee_count} attendees live is defensible here."
        )
        alternative_email = None

    return json.dumps(
        {
            "score": score,
            "verdict": verdict.value,
            "reasoning": reasoning,
            "alternative_email": alternative_email,
        }
    )


def _api_key() -> str | None:
    """Doc 4 names LLM_API_KEY; the SDK's own variable is accepted as well."""
    return os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or None


def _call_llm(prompt: str) -> str:
    """The seam (doc 2 §8) — the only function that changes between stub and provider.

    Returns the model's raw text. Everything downstream parses that text and never
    learns which branch produced it.
    """
    import anthropic  # imported lazily so the stub path needs no SDK at all

    key = _api_key()
    if not key:
        raise RuntimeError(
            "SHOULDBE_USE_STUB is off but no LLM_API_KEY is set. Set a key, or set "
            "SHOULDBE_USE_STUB=1 to score offline."
        )

    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        output_config={"effort": LLM_EFFORT},
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "refusal":
        # Handled like any other unusable answer: the parser returns a neutral keep.
        logger.warning("The model declined to score this meeting.")
        return ""

    # Skip thinking blocks; only the text blocks carry the JSON.
    return "".join(block.text for block in response.content if block.type == "text")


def _strip_fences(raw: str) -> str:
    """Models wrap JSON in ``` fences even when told not to. Take what is inside."""
    text = raw.strip()
    if not text.startswith("```"):
        return text
    body = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    return body[: body.rfind("```")].strip() if "```" in body else body.strip()


def _neutral_keep(reason: str) -> dict:
    """Fallback verdict. Never flags a meeting on the strength of an unreadable answer."""
    return {
        "score": SCORE_NEUTRAL_FALLBACK,
        "verdict": Verdict.KEEP.value,
        "reasoning": reason,
        "alternative_email": None,
    }


def _parse_analysis(raw: str) -> dict:
    """Parse the model's answer defensively; the pipeline must never crash on it.

    Enforces the §4.4 invariant in both directions: a `keep` verdict carries no drafted
    email, and an `email` verdict without one is treated as unusable rather than
    persisted as a flagged meeting with nothing to replace it.
    """
    fallback = _neutral_keep(
        "The necessity analysis could not be read, so this meeting is left on the "
        "calendar. Re-run the analysis to get a verdict."
    )

    try:
        parsed = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, TypeError, AttributeError):
        return fallback

    if not isinstance(parsed, dict):
        return fallback

    try:
        verdict = Verdict(str(parsed.get("verdict", "")).strip().lower())
    except ValueError:
        return fallback

    try:
        score = int(parsed["score"])
    except (KeyError, TypeError, ValueError):
        return fallback
    score = max(SCORE_MIN, min(SCORE_MAX, score))

    reasoning = parsed.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        return fallback

    draft = parsed.get("alternative_email")
    draft = draft.strip() if isinstance(draft, str) else None

    if verdict is Verdict.KEEP:
        draft = None
    elif not draft:
        return fallback

    return {
        "score": score,
        "verdict": verdict.value,
        "reasoning": reasoning.strip(),
        "alternative_email": draft,
    }


def score_meeting(
    *,
    title: str,
    description: str,
    duration_minutes: int,
    attendee_count: int,
    is_recurring: bool,
    recurrence_freq: str | None,
    cost: Decimal,
) -> dict:
    """Score one meeting. Returns {score, verdict, reasoning, alternative_email}.

    The returned shape is identical whether the stub or the real provider answered.
    """
    prompt = build_prompt(
        title=title,
        description=description,
        duration_minutes=duration_minutes,
        attendee_count=attendee_count,
        is_recurring=is_recurring,
        recurrence_freq=recurrence_freq,
        cost=cost,
    )

    if _stub_enabled():
        return _parse_analysis(
            _stub_response(
                title=title,
                description=description,
                duration_minutes=duration_minutes,
                attendee_count=attendee_count,
                is_recurring=is_recurring,
            )
        )

    try:
        raw = _call_llm(prompt)
    except Exception:
        # A missing key, a rate limit, a network drop: the meeting still gets costed and
        # recorded with a neutral verdict rather than failing the whole request. Logged
        # in full server-side; the user sees a plain sentence. Flipping SHOULDBE_USE_STUB
        # back on is the instant recovery (doc 4 task 4-E).
        logger.exception("Necessity scoring failed; falling back to a neutral verdict.")
        return _neutral_keep(
            "The necessity analysis could not be completed, so this meeting is left on "
            "the calendar. Re-run the analysis to get a verdict."
        )

    return _parse_analysis(raw)

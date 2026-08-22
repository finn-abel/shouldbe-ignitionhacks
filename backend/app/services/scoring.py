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

# Real scoring defaults to OpenAI's smallest GPT-5 model because this is a short
# classification + draft-writing task, not long-form reasoning.
DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_OPENAI_MODEL = "gpt-5-nano"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"

# Enough room for the reasoning plus a drafted email, without paying for giant outputs.
DEFAULT_LLM_MAX_TOKENS = 1200

# Anthropic-only effort setting. This is a short classification with a short piece of
# writing attached, not a research task.
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
EMAIL_SCORE_MAX = 4

RUBRIC_CATEGORIES = (
    {
        "key": "decision_pressure",
        "label": "Decision pressure",
        "weight": 35,
        "description": (
            "Does the work need a live decision, unresolved disagreement, escalation, "
            "or sensitive conversation? 0 = no decision; 5 = useful live alignment; "
            "10 = live decision/debate is essential."
        ),
    },
    {
        "key": "collaboration_depth",
        "label": "Collaboration depth",
        "weight": 25,
        "description": (
            "How much real back-and-forth, co-creation, or nuanced discussion is needed? "
            "0 = people can read/update independently; 5 = some discussion helps; "
            "10 = writing would be much slower or lower quality."
        ),
    },
    {
        "key": "interaction_value",
        "label": "Interaction value",
        "weight": 20,
        "description": (
            "Is the agenda multi-directional rather than one-way reporting? "
            "0 = status/readout/FYI; 5 = mixed update and discussion; "
            "10 = most value comes from live exchange."
        ),
    },
    {
        "key": "meeting_fit",
        "label": "Meeting fit",
        "weight": 10,
        "description": (
            "Is the meeting format tight for the goal? 0 = broad recurring sync, too many "
            "attendees, or weak agenda; 5 = acceptable but not sharp; 10 = right people, "
            "right cadence, clear live purpose."
        ),
    },
    {
        "key": "business_impact",
        "label": "Business impact",
        "weight": 10,
        "description": (
            "How important is immediate progress on this topic? 0 = low-stakes update; "
            "5 = useful operational progress; 10 = urgent or high-consequence work."
        ),
    },
)

RUBRIC_WEIGHT_TOTAL = sum(category["weight"] for category in RUBRIC_CATEGORIES)
if RUBRIC_WEIGHT_TOTAL != 100:
    raise RuntimeError("Scoring rubric weights must add up to 100.")

RUBRIC_KEYS = tuple(category["key"] for category in RUBRIC_CATEGORIES)
RUBRIC_SCORE_SCHEMA = {"type": "integer", "minimum": 0, "maximum": 10}


def _rubric_prompt() -> str:
    lines = [
        "Use this fixed percentage rubric. Each category is scored 0-10, where higher "
        "always means the meeting is more necessary live. The backend calculates the "
        "final score as sum(category_score * category_weight) / 100, rounded to a "
        "1-10 score. Do not invent different weights.",
        "",
    ]
    lines.extend(
        f"- {category['key']} ({category['label']}, {category['weight']}%): "
        f"{category['description']}"
        for category in RUBRIC_CATEGORIES
    )
    lines.extend(
        [
            "",
            f"Final score thresholds: {SCORE_MIN}-{EMAIL_SCORE_MAX} means it could be "
            f"an email; {EMAIL_SCORE_MAX + 1}-{SCORE_MAX} means keep it live. Use the "
            "middle carefully: ambiguous meetings should be kept rather than over-flagged.",
            "Do not lower a meeting's necessity just because it is expensive; cost is "
            "context for scrutiny, not a scoring category.",
        ]
    )
    return "\n".join(lines)

ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "rubric": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                category["key"]: RUBRIC_SCORE_SCHEMA.copy()
                for category in RUBRIC_CATEGORIES
            },
            "required": list(RUBRIC_KEYS),
        },
        "reasoning": {"type": "string"},
        "alternative_email": {"type": ["string", "null"]},
    },
    "required": ["rubric", "reasoning", "alternative_email"],
}

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

RUBRIC = _rubric_prompt()


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
{{"rubric": {{
    "decision_pressure": <int 0-10>,
    "collaboration_depth": <int 0-10>,
    "interaction_value": <int 0-10>,
    "meeting_fit": <int 0-10>,
    "business_impact": <int 0-10>
  }},
  "reasoning": "<2-3 sentences specific to THIS meeting>",
  "alternative_email": "<the email that replaces the meeting, or null>"}}

Rules:
- Return only the rubric category scores, reasoning, and alternative_email. Do not return
  a final score or verdict; the backend calculates those from the fixed weights.
- The reasoning should name the one or two rubric categories that most drive the result.
- When the weighted rubric is likely {SCORE_MIN}-{EMAIL_SCORE_MAX}, write the actual email
  the organizer could send instead: a subject line and a short body covering what the
  meeting would have covered.
- When the weighted rubric is likely {EMAIL_SCORE_MAX + 1}-{SCORE_MAX}, set
  alternative_email to null.
- The email must NOT mention cost, budget, dollar figures, or any individual person's
  rate or salary. It is about the meeting's topic, not its price.\
"""


def _score_from_rubric(rubric: dict) -> int:
    """Calculate the 1-10 necessity score from the fixed percentage rubric."""
    weighted = 0
    for category in RUBRIC_CATEGORIES:
        key = category["key"]
        raw_value = rubric[key]
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise ValueError(f"{key} must be an integer from 0 to 10.")
        if raw_value < 0 or raw_value > 10:
            raise ValueError(f"{key} must be an integer from 0 to 10.")
        weighted += raw_value * category["weight"]

    # The weighted average is 0-10. Round half up, then clamp to the stored 1-10 scale.
    score = (weighted + 50) // 100
    return max(SCORE_MIN, min(SCORE_MAX, score))


def _verdict_from_score(score: int) -> Verdict:
    return Verdict.EMAIL if score <= EMAIL_SCORE_MAX else Verdict.KEEP


def _stub_response(
    *,
    title: str,
    description: str,
    duration_minutes: int,
    attendee_count: int,
    is_recurring: bool,
) -> str:
    """Deterministic canned JSON that uses the same weighted rubric as the model."""
    haystack = f"{title} {description}".lower()

    if _matches(haystack, ASYNC_SIGNALS):
        rubric = (
            {
                "decision_pressure": 2,
                "collaboration_depth": 2,
                "interaction_value": 3,
                "meeting_fit": 3,
                "business_impact": 4,
            }
            if is_recurring else
            {
                "decision_pressure": 3,
                "collaboration_depth": 3,
                "interaction_value": 4,
                "meeting_fit": 5,
                "business_impact": 4,
            }
        )
    elif _matches(haystack, LIVE_SIGNALS):
        rubric = {
            "decision_pressure": 9,
            "collaboration_depth": 8,
            "interaction_value": 8,
            "meeting_fit": 7,
            "business_impact": 7,
        }
    else:
        rubric = {
            "decision_pressure": 6,
            "collaboration_depth": 6,
            "interaction_value": 5,
            "meeting_fit": 6,
            "business_impact": 6,
        }

    score = _score_from_rubric(rubric)
    verdict = _verdict_from_score(score)

    cadence = "This is a recurring commitment, so the cost repeats every occurrence. " if is_recurring else ""

    if verdict is Verdict.EMAIL:
        reasoning = (
            f'The weighted rubric puts "{title}" low on decision pressure and live '
            f"interaction value, so it reads as information moving in one direction "
            f"rather than a decision that needs {attendee_count} people present. {cadence}"
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
            f'The weighted rubric keeps "{title}" live because decision pressure and '
            f"collaboration depth are high enough for synchronous discussion. {cadence}"
            f"Keeping {attendee_count} attendees live is defensible here."
        )
        alternative_email = None

    return json.dumps(
        {
            "rubric": rubric,
            "reasoning": reasoning,
            "alternative_email": alternative_email,
        }
    )


def _provider() -> str:
    """Which real provider to call when the stub is off."""
    raw = os.getenv("LLM_PROVIDER")
    if not raw:
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        return DEFAULT_LLM_PROVIDER

    provider = raw.strip().lower()
    if provider in {"openai", "anthropic"}:
        return provider
    if provider == "claude":
        return "anthropic"
    raise RuntimeError(f"Unsupported LLM_PROVIDER {raw!r}. Use 'openai' or 'anthropic'.")


def _model(provider: str | None = None) -> str:
    """Resolve the model lazily so env changes apply on backend restart."""
    provider = provider or _provider()
    if os.getenv("LLM_MODEL"):
        return os.environ["LLM_MODEL"]
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
    return os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)


def _max_tokens() -> int:
    raw = os.getenv("LLM_MAX_TOKENS")
    if not raw:
        return DEFAULT_LLM_MAX_TOKENS
    try:
        return max(200, int(raw))
    except ValueError:
        return DEFAULT_LLM_MAX_TOKENS


def _api_key(provider: str | None = None) -> str | None:
    """Provider-specific key first; LLM_API_KEY remains the generic fallback."""
    provider = provider or _provider()
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY") or os.getenv("LLM_API_KEY") or None
    return os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or None


def _call_llm(prompt: str) -> str:
    """The seam (doc 2 §8) — the only function that changes between stub and provider.

    Returns the model's raw text. Everything downstream parses that text and never
    learns which branch produced it.
    """
    provider = _provider()
    key = _api_key(provider)

    if not key:
        raise RuntimeError(
            f"SHOULDBE_USE_STUB is off but no {provider} API key is set. Set "
            "OPENAI_API_KEY, ANTHROPIC_API_KEY, or LLM_API_KEY; or set "
            "SHOULDBE_USE_STUB=1 to score offline."
        )

    if provider == "anthropic":
        return _call_anthropic(prompt, key)
    return _call_openai(prompt, key)


def _call_openai(prompt: str, key: str) -> str:
    """Call OpenAI Responses with Structured Outputs."""
    from openai import OpenAI  # imported lazily so the stub path needs no SDK at all

    client = OpenAI(api_key=key)
    response = client.responses.create(
        model=_model("openai"),
        input=prompt,
        max_output_tokens=_max_tokens(),
        store=False,
        text={
            "format": {
                "type": "json_schema",
                "name": "meeting_necessity_analysis",
                "schema": ANALYSIS_SCHEMA,
                "strict": True,
            },
            "verbosity": "low",
        },
    )

    if getattr(response, "status", None) == "incomplete":
        logger.warning(
            "OpenAI scoring response was incomplete: %s",
            getattr(response, "incomplete_details", None),
        )

    return getattr(response, "output_text", "") or ""


def _call_anthropic(prompt: str, key: str) -> str:
    """Call Anthropic Messages, retained as an alternate provider."""
    import anthropic  # imported lazily so the stub path needs no SDK at all

    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=_model("anthropic"),
        max_tokens=_max_tokens(),
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


def _parse_legacy_score(parsed: dict) -> tuple[int, Verdict] | None:
    """Accept the old raw provider shape so saved tests and manual spikes stay readable."""
    try:
        verdict = Verdict(str(parsed.get("verdict", "")).strip().lower())
    except ValueError:
        return None

    try:
        score = int(parsed["score"])
    except (KeyError, TypeError, ValueError):
        return None

    return max(SCORE_MIN, min(SCORE_MAX, score)), verdict


def _parse_score_and_verdict(parsed: dict) -> tuple[int, Verdict] | None:
    """Prefer the fixed rubric; fall back to the pre-rubric shape for compatibility."""
    rubric = parsed.get("rubric")
    if rubric is not None:
        if not isinstance(rubric, dict):
            return None
        try:
            score = _score_from_rubric(rubric)
        except (KeyError, TypeError, ValueError):
            return None
        return score, _verdict_from_score(score)

    return _parse_legacy_score(parsed)


def _parse_analysis(raw: str) -> dict:
    """Parse the model's answer defensively; the pipeline must never crash on it.

    The preferred raw shape contains category scores, not a final verdict. The backend
    calculates score/verdict from the fixed percentage rubric, then enforces the §4.4
    invariant in both directions: a `keep` verdict carries no drafted email, and an
    `email` verdict without one is treated as unusable rather than persisted as a flagged
    meeting with nothing to replace it.
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

    scored = _parse_score_and_verdict(parsed)
    if scored is None:
        return fallback
    score, verdict = scored

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

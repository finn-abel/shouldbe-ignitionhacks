"""One-call LLM spike (doc 4 task 4-E). Confirms the key and model before wiring.

    cd backend && LLM_API_KEY=sk-... PYTHONPATH=. ./venv/bin/python scripts_spike_llm.py

Prints the raw text and the parsed analysis. Costs one short request.
"""

import json
import os
import sys

from app.services import scoring

if not scoring._api_key():
    sys.exit("No LLM_API_KEY / ANTHROPIC_API_KEY set — nothing to spike.")

os.environ["SHOULDBE_USE_STUB"] = "0"

prompt = scoring.build_prompt(
    title="Weekly Engineering Standup",
    description="Round the room on what everyone did yesterday.",
    duration_minutes=30,
    attendee_count=18,
    is_recurring=True,
    recurrence_freq="WEEKLY",
    cost="800.00",
)

print(f"model: {scoring.LLM_MODEL}  effort: {scoring.LLM_EFFORT}\n")
raw = scoring._call_llm(prompt)
print("--- raw text ---")
print(raw or "(empty — the model declined)")
print("\n--- parsed ---")
print(json.dumps(scoring._parse_analysis(raw), indent=2))

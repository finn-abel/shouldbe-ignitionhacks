# ShouldBe

[![CI](https://github.com/finn-abel/shouldbe-ignitionhacks/actions/workflows/ci.yml/badge.svg)](https://github.com/finn-abel/shouldbe-ignitionhacks/actions/workflows/ci.yml)

Meeting spend management — scores meetings for necessity, computes their dollar cost, and
drafts email alternatives.

*Ignition Hacks V.7 · Fintech track*

## Layout

```
/backend    FastAPI service — routes (thin) → services (all logic) → data (persistence)
/frontend   React dashboard (Vite)
```

## Requirements

- Python 3.11+
- Node 18+

## Run the backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # first time only
PYTHONPATH=. python -m app.seed # seeds the shared guest with a month of meetings
uvicorn app.main:app --reload --port 8000
```

Re-run the seed any time to reset the guest's numbers before a demo.

Verify: <http://localhost:8000/health> → `{"status":"ok"}`
API docs: <http://localhost:8000/docs>

## Run the frontend

```bash
cd frontend
npm install
cp .env.example .env            # first time only
npm run dev
```

Verify: <http://localhost:5173> → "Continue as guest" opens the seeded dashboard.
Google sign-in needs `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`; without them that button
returns a clear "not configured" message and guest entry still works.
The backend must be running too; the frontend calls it cross-origin at `VITE_API_BASE_URL`.
Use `localhost`, not `127.0.0.1` — the Vite dev server binds IPv6 loopback.

## Tests

```bash
cd backend && ./venv/bin/pytest
```

One-off scripts against the app package need the same path: `PYTHONPATH=. ./venv/bin/python script.py`.

CI runs the same tests, boots the backend to check `/health`, and builds the frontend —
on pushes to `main` and on pull requests into it. See `.github/workflows/ci.yml`.

## Real LLM scoring

Everything runs offline on a deterministic stub by default. To use the real provider, put a key
in `LLM_API_KEY`, validate it in isolation first, then flip the stub off:

```bash
cd backend
LLM_API_KEY=sk-... PYTHONPATH=. ./venv/bin/python spike_llm.py   # one call, prints the analysis
SHOULDBE_USE_STUB=0 ./venv/bin/uvicorn app.main:app --reload --port 8000
```

If the provider errors mid-demo, set `SHOULDBE_USE_STUB=1` and restart — the stub is never removed.

## Door A — invite ShouldBe to a meeting

Set `POSTMARK_TOKEN`, `POSTMARK_FROM`, `SHOULDBE_INBOX` and `POSTMARK_WEBHOOK_SECRET`, then point
the Postmark inbound stream at `POST /webhook/inbound-email?token=<secret>`. Without Postmark
configured the webhook still parses, scores and records the invite — it just skips the reply.

To exercise the same path from a saved `.ics` with no email at all:

```bash
cd backend && PYTHONPATH=. ./venv/bin/python -m app.services.ics_adapter invite.ics you@yourdomain
```

## Environment

Both services read a local `.env` (git-ignored); `.env.example` is the committed template.
Full variable reference: `shouldbe-docs/shouldbe-04-dev-log.md`.

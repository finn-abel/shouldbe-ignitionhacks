# ShouldBe

Meeting spend management — scores meetings for necessity, computes their dollar cost, and
drafts email alternatives.

*Ignition Hacks V.7 · Fintech track*

Design docs live in `shouldbe-docs/` (overview, architecture, build plan, dev log).
The architecture doc is the source of truth for structure.

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
uvicorn app.main:app --reload --port 8000
```

Verify: <http://localhost:8000/health> → `{"status":"ok"}`
API docs: <http://localhost:8000/docs>

## Run the frontend

```bash
cd frontend
npm install
cp .env.example .env            # first time only
npm run dev
```

Verify: <http://localhost:5173> → the placeholder page.
Use `localhost`, not `127.0.0.1` — the Vite dev server binds IPv6 loopback.

## Tests

```bash
cd backend && ./venv/bin/pytest
```

## Environment

Both services read a local `.env` (git-ignored); `.env.example` is the committed template.
Full variable reference: `shouldbe-docs/shouldbe-04-dev-log.md`.

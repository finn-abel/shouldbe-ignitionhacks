<p align="center">
  <img src="frontend/public/shouldbe-logo.svg" alt="ShouldBe logo" width="260" />
</p>

# ShouldBe

[![CI](https://github.com/finn-abel/shouldbe-ignitionhacks/actions/workflows/ci.yml/badge.svg)](https://github.com/finn-abel/shouldbe-ignitionhacks/actions/workflows/ci.yml)

ShouldBe is a meeting spend-management application that turns calendar time into a
financial control surface. It prices meetings from privacy-preserving blended role rates,
scores whether each meeting genuinely needs to happen live, drafts email replacements for
low-necessity meetings, and tracks monthly meeting budgets by user, team, or department.

Built for **Ignition Hacks V.7 · Fintech track**, ShouldBe moves beyond passive
analytics: it gives teams a ledger of meeting spend, budget guardrails before new
meetings are recorded, and a practical path to reclaim avoidable meeting costs.

## Product Overview

Modern teams spend real money in meetings, but that spend is usually invisible until it
has already happened. ShouldBe makes the cost visible at the moment a meeting is created
or received.

Core capabilities:

- **Meeting cost calculation** from configurable blended hourly rates for role tiers.
- **Necessity scoring** using a fixed weighted rubric for decision pressure,
  collaboration depth, interaction value, meeting fit, and business impact.
- **AI-assisted analysis** with an offline deterministic stub by default and optional
  OpenAI or Anthropic scoring for production demos.
- **Budget guardrails** for user, team, and department budgets, including 50%, 80%, and
  100% threshold warnings.
- **Remaining meeting budget** and current-month spend on the dashboard.
- **Email replacement drafts** for meetings that can move async.
- **Inbound calendar invite processing** through the Email Door, with idempotent webhook
  handling and retryable outbound replies.
- **Guest mode and optional Google sign-in** so the app can be demoed immediately.

## How It Works

1. A meeting enters ShouldBe from the manual analysis form or from an emailed `.ics`
   invite.
2. Attendee addresses are resolved against the user's people directory, so each seat is
   priced at that person's role tier. An address nobody has placed is priced at the floor
   tier and flagged as a guess rather than passed off as a figure.
3. The backend prices the meeting from the configured role-tier rates.
4. The scoring service evaluates whether the meeting should stay live or become an email.
5. Budget guardrails compare projected monthly spend against the active user, team, or
   department budget.
6. The meeting is written to the ledger, where the dashboard tracks total spend,
   necessary spend, avoidable spend, reclaimed savings, and remaining budget.

The backend owns all financial logic. The frontend never recomputes dollar totals; it
renders API responses from the FastAPI service.

## Repository Structure

```text
.
├── backend/                  FastAPI API, scoring, cost model, persistence, email routes
│   ├── app/
│   │   ├── data/             SQLAlchemy models and database access
│   │   ├── routes/           Thin HTTP route handlers
│   │   ├── schemas/          Pydantic request and response models
│   │   └── services/         Costing, scoring, money, email, and .ics logic
│   └── tests/                Backend unit and integration tests
├── frontend/                 React + Vite dashboard
│   ├── public/               Logo and static assets
│   └── src/                  App, components, API client, styles
├── render.yaml               Render blueprint for production deployment
├── RUNBOOK.md                Operational commands and troubleshooting
├── SETUP.local.md            Full local integration checklist
└── DEPLOY.md                 Render deployment guide
```

## Tech Stack

### Backend

- Python 3.11+
- FastAPI
- SQLAlchemy 2
- Pydantic 2
- SQLite locally, Postgres in production
- Pytest
- Optional OpenAI or Anthropic SDKs for real LLM scoring
- Optional Postmark and Resend for inbound invites and outbound replies

### Frontend

- Node 18+
- React 19
- Vite 7
- Plain CSS organized by app surface

## Prerequisites

Install:

- Python 3.11 or newer
- Node.js 18 or newer
- npm

Optional for full integrations:

- OpenAI Platform API key or Anthropic API key
- Google OAuth client credentials
- Postmark inbound email setup
- Resend outbound email setup
- Render account for deployment

## Local Setup

### 1. Clone the Repository

```bash
git clone https://github.com/finn-abel/shouldbe-ignitionhacks.git
cd shouldbe-ignitionhacks
```

### 2. Configure the Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.seed
uvicorn app.main:app --reload --host localhost --port 8000
```

The seed command creates the shared guest account and a realistic demo ledger. Re-run it
when you want to reset the guest dashboard before a demo.

Backend health check:

```bash
curl -fsS http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

API documentation:

```text
http://localhost:8000/docs
```

### 3. Configure the Frontend

In a second terminal:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open:

```text
http://localhost:5173
```

Press **Continue as guest** to open the seeded dashboard.

## Environment Variables

Both services use git-ignored local `.env` files. Start from the committed templates:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Important local defaults:

| Variable | Service | Purpose |
|---|---|---|
| `DATABASE_URL` | Backend | SQLite locally or Postgres in production |
| `FRONTEND_ORIGIN` | Backend | CORS origin for the React app |
| `FRONTEND_URL` | Backend | Where OAuth redirects return |
| `SESSION_SECRET` | Backend | Signs the session cookie |
| `SESSION_COOKIE_SAMESITE` | Backend | `lax` locally, `none` in production |
| `SESSION_COOKIE_SECURE` | Backend | `false` locally, `true` in production |
| `SHOULDBE_USE_STUB` | Backend | `1` for offline scoring, `0` for real LLM scoring |
| `OPENAI_API_KEY` | Backend | Optional real OpenAI scoring |
| `ANTHROPIC_API_KEY` | Backend | Optional Anthropic scoring |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Backend | Optional Google sign-in |
| `POSTMARK_TOKEN` / `SHOULDBE_INBOX` | Backend | Optional inbound invite processing |
| `RESEND_API_KEY` / `RESEND_FROM` | Backend | Optional outbound email replies |
| `VITE_API_BASE_URL` | Frontend | Backend API base URL |

For deployed environments, set:

```env
SESSION_COOKIE_SAMESITE=none
SESSION_COOKIE_SECURE=true
```

Without those production cookie settings, cross-site API calls from the deployed frontend
will not include the session cookie and the API will respond with `401`.

## Running Tests

Run the backend test suite:

```bash
cd backend
source venv/bin/activate
pytest
```

Build the frontend:

```bash
cd frontend
npm run build
```

CI runs the backend tests, checks the backend health endpoint, and builds the frontend on
pushes and pull requests. See `.github/workflows/ci.yml`.

## Real LLM Scoring

ShouldBe works offline by default with a deterministic scoring stub. This is intentional:
the demo does not require an API key and will not fail because of a model provider outage.

To enable OpenAI scoring:

```env
SHOULDBE_USE_STUB=0
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-5-nano
OPENAI_API_KEY=sk-...
LLM_MAX_TOKENS=4000
```

`LLM_MAX_TOKENS` is the budget for one scoring call, and on a reasoning model it covers
the model's own reasoning as well as the answer — with the reasoning spent first. Sized
for the answer alone it starves the response: at 1200, gpt-5-nano used 1152 tokens
thinking and returned nothing. ShouldBe also caps reasoning effort (`LLM_EFFORT`) so the
thinking cannot consume the whole allowance. Measured usage at the default is ~950 tokens,
and you are billed for tokens used rather than for the cap.

If the AI provider fails, rate-limits, refuses, or runs out of output tokens, ShouldBe
records a neutral keep verdict and returns a specific warning to the UI instead of
silently hiding the failure.

## Scoring Rubric

The LLM does not decide the final verdict directly. It returns category scores and
reasoning; the backend calculates the final score from a fixed weighted rubric:

| Category | Weight |
|---|---:|
| Decision pressure | 35% |
| Collaboration depth | 25% |
| Interaction value | 20% |
| Meeting fit | 10% |
| Business impact | 10% |

Scores from 1 to 4 are treated as meetings that could become email. Scores from 5 to 10
are kept live. Ambiguous meetings are deliberately defended rather than over-flagged.

## Budget Guardrails

ShouldBe supports configurable monthly budgets by:

- User
- Team
- Department

The active budget scope controls the dashboard headline and the pre-analysis guardrail
check. Before a meeting is recorded, the backend projects the meeting cost against the
current monthly spend and warns when the meeting would cross:

- 50% budget usage
- 80% budget usage
- 100% budget usage
- Any over-budget state

The dashboard shows current spend, budget usage, and remaining meeting budget for the
active scope.

## Email Door

The Email Door lets a user invite ShouldBe to a calendar event like a coworker. Each user
receives a plus-addressed invite address such as:

```text
ledger+ab12cd@your-domain.example
```

The token routes the invite to the correct ledger. Users can also claim a company domain
so future invites organized by that domain are attributed correctly.

Inbound email is optional. When email is not configured, the manual analysis flow and
dashboard still work normally.

## People and Role Tiers

A calendar invite carries email addresses and no job titles, so ShouldBe cannot know what
a room costs until it is told who is in it. **Settings → People** is where that is
answered:

- **Your own role**, which prices every meeting you attend.
- **Anyone you add**, by address and tier, before they ever appear on an invite.
- **The unidentified worklist** — addresses already seen in your ledger that nobody has
  placed, busiest first.

Until an address is placed, its seat is billed at the floor tier (`IT-02`) and the seat is
recorded as a guess. The ledger marks those meetings as estimates rather than figures.

Naming someone corrects the past as well as the future: every meeting that guessed at them
is re-priced, and the dashboard totals move with it. Two rules keep that from becoming a
rewrite of history:

- Only seats that were *assumed* are ever re-priced. A seat whose tier was known when the
  meeting was priced keeps that price forever — which is the same reason editing an hourly
  rate never reaches backwards.
- Only the corrected seat takes a new rate. Every other seat in the room is re-summed at
  the rate stored on it.

Placing a person records a **tier**, never a salary. Rates are blended per tier and shared
by everyone in it, so no screen and no email can show one person's number.

## Deployment

The repository includes a Render blueprint in `render.yaml` for:

- Postgres database
- FastAPI backend service
- Static React frontend

Deployment instructions are in [DEPLOY.md](DEPLOY.md). Local integration details are in
[SETUP.local.md](SETUP.local.md). Operational troubleshooting is in [RUNBOOK.md](RUNBOOK.md).

## Useful Commands

```bash
# Backend
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --host localhost --port 8000
pytest
python -m app.seed

# Frontend
cd frontend
npm run dev
npm run build
```

## License

This project is released under the terms in [LICENSE](LICENSE).

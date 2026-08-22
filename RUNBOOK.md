# ShouldBe — local runbook

Everything here was run from a clean clone. Nothing below needs an API key, a domain, or
an internet connection.

## Prerequisites

| | Need | Check |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| Node | 18+ | `node --version` |

---

## One-time setup

```bash
# backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.seed          # guest user + a month of curated meetings

# frontend (new terminal)
cd frontend
npm install
cp .env.example .env
```

The stock `.env.example` files work as-is. **You do not have to edit a single variable to
run locally.**

---

## Run it — two terminals, every time

```bash
# terminal 1 — API on :8000
cd backend && source venv/bin/activate && uvicorn app.main:app --reload --port 8000

# terminal 2 — dashboard on :5173
cd frontend && npm run dev
```

Open <http://localhost:5173> and press **Continue as guest**.

> Use `localhost`, not `127.0.0.1` — Vite binds IPv6 loopback and `127.0.0.1:5173` will
> refuse the connection.

**Working:** the dashboard opens on `$8,372 — 34% over a $6,250 budget`, 13 meetings in the
ledger, and the all-hands standup flagged as the worst offender at `$800/session ·
$41,600/yr`.

---

## Variables you might actually change locally

The rest of `.env` is for deployment and can stay empty.

| Variable | Default | Change it when |
|---|---|---|
| `SHOULDBE_USE_STUB` | `1` | You have an LLM key and want real scoring — set `0` |
| `LLM_API_KEY` | *(empty)* | Same. Leave blank for the deterministic scoring stub |
| `SHOULDBE_TIMEZONE` | `America/Toronto` | You are demoing from another timezone |
| `SHOULDBE_MAX_BILLABLE_MINUTES` | `480` | You want a different per-meeting billing cap |
| `DATABASE_URL` | `sqlite:///./shouldbe.db` | Pointing at Postgres |
| `VITE_API_BASE_URL` *(frontend)* | `http://localhost:8000` | The API moves |

Everything left blank — `GOOGLE_*`, `POSTMARK_*`, `RESEND_*` — degrades gracefully. Google
sign-in returns a clear "not configured" message and guest entry still works; the inbound
webhook still parses and records invites, and the reply waits in the outbox rather than
being lost.

Postmark receives invites; Resend sends replies. They are independent — one can be broken
without touching the other.

If a reply did not arrive, `GET /api/outbox` says why. A row at `queued` with a `last_error`
is recoverable — unconfigured provider, unverified domain, rate limit, network — and will be
retried until it sends. A row at `failed` never will; only a malformed recipient gets there.

⚠️ Environment is read at process start. After editing `.env`, fully restart the backend —
`--reload` watches code, not variables.

---

## Other commands

```bash
cd backend && source venv/bin/activate

pytest -q                                     # 222 tests, ~1s
python -m app.seed                            # reset the guest's numbers before a demo
python -m app.services.ics_adapter file.ics   # score a saved .ics, no email needed
```

```bash
cd frontend
npm run build     # production build
npm run preview   # serve that build
```

No `PYTHONPATH=` prefix is needed for any of these — activating the venv and running from
`backend/` is enough.

---

## When something is wrong

| Symptom | Cause | Fix |
|---|---|---|
| `no such column: meetings.source_key` | Your DB predates a model change; this project uses create-all, not migrations | `rm backend/shouldbe.db && python -m app.seed` |
| Dashboard is empty | Seed never ran | `python -m app.seed` |
| Every API call 401s | No session — you never entered | Press "Continue as guest" |
| `Could not reach the ShouldBe API` | Backend is not running, or is on another port | Start terminal 1; check `VITE_API_BASE_URL` |
| Browser console shows a CORS error | `FRONTEND_ORIGIN` does not match where the UI is served | Set it to the exact origin, scheme and port included |
| `127.0.0.1:5173` refuses to connect | Vite binds IPv6 loopback | Use `localhost:5173` |
| Scores read generic / identical | The offline stub is on | Set `LLM_API_KEY` and `SHOULDBE_USE_STUB=0` |
| Real scoring broke mid-demo | Provider is down or rate-limited | `SHOULDBE_USE_STUB=1` and restart — the stub is never removed |

---

## Deploying

Everything above is local. Deploying to Render is its own guide — [DEPLOY.md](DEPLOY.md).

The short version of the part that catches people: on localhost the dashboard and the API
count as the same site, so the default `lax` session cookie is sent. On Render they are
different hosts and the browser drops it on every cross-site call — leave the defaults and
the deployed app answers 401 to everything, guest entry included, with nothing in the logs
to explain it. `render.yaml` already sets `SESSION_COOKIE_SAMESITE=none` and
`SESSION_COOKIE_SECURE=true`; don't undo them.

# ShouldBe — deploying to Render

Three services, one blueprint: a Postgres database, the FastAPI API, and the dashboard as
a static site. [`render.yaml`](render.yaml) describes all three, so this is mostly reading
URLs off a dashboard and pasting them back in.

Nothing here needs an LLM key, a domain, or email. Those are upgrades at the end — the
deploy is demo-ready without any of them.

---

## The one thing that will bite you

The dashboard and the API end up on **different hosts** (`shouldbe-web.onrender.com` and
`shouldbe-api.onrender.com`). That makes every API call cross-site, and a cross-site
request only carries the session cookie if the cookie is `SameSite=None; Secure`.

Leave the local defaults in place and the deployed app answers **401 to everything** —
guest entry included — with nothing in the logs to explain it. The blueprint already sets
`SESSION_COOKIE_SAMESITE=none` and `SESSION_COOKIE_SECURE=true`. Don't "fix" them back.

---

## 1. Push the branch

```bash
git push -u origin main
```

The blueprint can deploy any branch; choose the one you are submitting.

## 2. Create the blueprint

Render Dashboard → **New** → **Blueprint** → pick this repo → choose the branch.

Render reads `render.yaml` and offers to create `shouldbe-db`, `shouldbe-api`, and
`shouldbe-web`. It will prompt for every `sync: false` variable. **Leave them all blank
for now** — including `FRONTEND_ORIGIN`, `FRONTEND_URL`, and `VITE_API_BASE_URL`, which
you cannot know yet. Click apply.

The first API deploy takes a few minutes (psycopg2 and the LLM SDKs are the slow part).

## 3. Wire the two services to each other

This pairing is the one manual part: each service needs the other's URL, and neither URL
exists until Render assigns it. Copy them off the dashboard — **https, no
trailing slash**.

| Service | Variable | Value |
|---|---|---|
| `shouldbe-api` | `FRONTEND_ORIGIN` | the **web** URL, e.g. `https://shouldbe-web.onrender.com` |
| `shouldbe-api` | `FRONTEND_URL` | the same web URL |
| `shouldbe-web` | `VITE_API_BASE_URL` | the **api** URL, e.g. `https://shouldbe-api.onrender.com` |

> `VITE_API_BASE_URL` is inlined by Vite at **build** time. Changing it needs a redeploy
> of the static site, not a restart — "Clear build cache & deploy" if in doubt.

Redeploy both. Open the web URL and press **Continue as guest**.

**Working:** the dashboard opens over budget, with 13 meetings in the ledger and the
all-hands standup flagged as the worst offender. That data seeded itself — `render.yaml`
sets `SHOULDBE_SEED_ON_START=1`, which populates an empty database on boot and refuses to
touch one that already has meetings in it.

---

## 4. Optional upgrades, in the order worth doing them

Each is independent. The app degrades gracefully without all of them.

### Real LLM scoring

Set `OPENAI_API_KEY` on `shouldbe-api` and flip `SHOULDBE_USE_STUB` to `0`. If the
provider is slow or rate-limited mid-demo, flip it back to `1` and restart — the offline
stub is never removed.

### Google sign-in

1. Google Cloud Console → Credentials → OAuth 2.0 Client ID (Web application).
2. **Authorized redirect URI**: `https://<your-api-url>/api/auth/google/callback`
3. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` on `shouldbe-api`.

The scopes are `openid email profile` only — not calendar — so Google needs no
verification review and shows no "unverified app" wall.

> If sign-in fails with `redirect_uri_mismatch` and the URI *looks* right, check that it
> is `https` on both sides. The start command passes `--forwarded-allow-ips="*"` for
> exactly this reason: without it uvicorn ignores Render's `X-Forwarded-Proto`, builds the
> callback as `http://`, and Google rejects it.

### Inbound invites and replies

| | Where | Set |
|---|---|---|
| Postmark **receives** | MX on your invite subdomain → `inbound.postmarkapp.com` | `POSTMARK_TOKEN`, `POSTMARK_WEBHOOK_SECRET` |
| Resend **sends** | domain verified at resend.com/domains | `RESEND_API_KEY`, `RESEND_FROM` |

`SHOULDBE_INBOX` is no longer in that list because the blueprint now ships it as a
literal value — it is a public address, not a secret. Every user's invite address is
derived from it, so when it is blank the whole email door degrades to
`ledger+<token>@example.invalid` while the app otherwise looks fine. Change it in
`render.yaml` if you use a different domain; the API logs a warning at boot if it is
somehow empty on a deployed instance.

Postmark's inbound webhook URL is
`https://<your-api-url>/webhook/inbound-email?token=<POSTMARK_WEBHOOK_SECRET>`. The
endpoint is public and it sends email, so an unprotected one is a spam relay — set the
secret.

They are independent: one can be broken without touching the other. `GET /api/outbox`
says why a reply has not arrived.

---

## Costs and plans

`render.yaml` asks for paid tiers, which is what the sponsor credits are for:

| Service | Blueprint plan | Free alternative |
|---|---|---|
| `shouldbe-db` | `basic-256mb` | `free` — but expires after 30 days |
| `shouldbe-api` | `starter` | `free` — spins down after 15 idle minutes |
| `shouldbe-web` | static, always free | — |

**The API plan is the one that matters for a demo.** On `free`, the service sleeps after
15 minutes of no traffic and the next request waits ~50 seconds for a cold boot. That is
the difference between a judge seeing a dashboard and a judge seeing a spinner. To drop to
free anyway, change `plan:` in `render.yaml` and re-sync — and hit the URL a minute before
you present.

---

## When something is wrong

| Symptom | Cause | Fix |
|---|---|---|
| Every call 401s, guest entry included | Session cookie dropped as cross-site | `SESSION_COOKIE_SAMESITE=none`, `SESSION_COOKIE_SECURE=true` |
| CORS error in the browser console | `FRONTEND_ORIGIN` ≠ where the UI is served | Exact origin: scheme, host, no trailing slash |
| `Could not reach the ShouldBe API` | `VITE_API_BASE_URL` wrong, or baked in before you set it | Set it, then **redeploy** the static site |
| Build fails: `Can't load plugin: sqlalchemy.dialects:postgres` | An old checkout without the URL normalization | Deploy a branch that includes `app/data/db.py`'s `_normalize_url` |
| `redirect_uri_mismatch` on Google | Callback built as `http://` behind the proxy | Confirm `--forwarded-allow-ips="*"` is in the start command |
| Invite address reads `…@example.invalid` | `SHOULDBE_INBOX` blank on `shouldbe-api` | Set it (or re-sync the blueprint), restart the API |
| Dashboard is empty | Seed skipped, or the DB already had a guest row with no meetings | Render Shell on `shouldbe-api`: `python -m app.seed` |
| First request after a quiet spell errors | Stale pooled connection | Already handled by `pool_pre_ping`; if it persists, check the DB is not suspended |
| Numbers drifted from people clicking around | Shared guest user | Render Shell: `python -m app.seed` (destructive reset of guest data) |

`python -m app.seed` from the Render Shell is the deliberate reset. It wipes the guest's
meetings and rebuilds them through the real scoring pipeline, so the numbers stay
internally consistent.

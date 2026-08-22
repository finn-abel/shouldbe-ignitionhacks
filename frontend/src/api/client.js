// Every backend call lives here (doc 2 §3.4) — components never fetch directly.
// Dev talks to the backend cross-origin and relies on its CORS config (doc 4 task 4-C),
// which is the same shape as production; no Vite proxy, so dev and prod cannot diverge.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

/** FastAPI returns 422 as {detail: [{loc, msg}, ...]} and 4xx/5xx as {detail: "..."}. */
function readErrorDetail(body, status) {
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    if (typeof detail.message === 'string') return detail.message;
    if (typeof detail.reason === 'string') return detail.reason;
    if (typeof detail.error === 'string') return detail.error;
  }
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = first.loc?.filter((part) => part !== 'body').join(' → ');
    return field ? `${field}: ${first.msg}` : first.msg;
  }
  if (typeof body?.message === 'string') return body.message;
  if (typeof body?.error === 'string') return body.error;
  return `Request failed (${status}).`;
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      // The acting user lives in a session cookie, and the API is a different origin —
      // without this the cookie is never sent and every call comes back 401.
      credentials: 'include',
      ...options,
    });
  } catch (failure) {
    // A network-level failure, not an API error — usually the backend is not running.
    const reason = failure instanceof Error && failure.message ? ` ${failure.message}.` : '';
    throw new Error(`Could not reach the ShouldBe API at ${API_BASE_URL}.${reason}`);
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const failure = new Error(readErrorDetail(body, response.status));
    failure.status = response.status;
    failure.code = body?.detail?.code ?? body?.code;
    throw failure;
  }
  return body;
}

// --- entry (doc 2 §5.5) ---

/** Who this browser is acting as. Throws with status 401 when nobody has entered yet. */
export function getMe() {
  return request('/api/auth/me');
}

/** Continue as guest — a real, writable, pre-seeded user, not a restricted mode. */
export function enterAsGuest() {
  return request('/api/auth/guest', { method: 'POST' });
}

export function logout() {
  return request('/api/auth/logout', { method: 'POST' });
}

/** A full page navigation, not a fetch: the browser has to follow Google's redirects. */
export const GOOGLE_LOGIN_URL = `${API_BASE_URL}/api/auth/google/login`;

/** Door B: analyze a typed-in meeting and record it in the ledger. */
export function analyzeMeeting(meeting) {
  return request('/api/analyze', { method: 'POST', body: JSON.stringify(meeting) });
}

/** The acting user's ledger, newest first. */
export function listMeetings() {
  return request('/api/meetings');
}

export function getMeeting(id) {
  return request(`/api/meetings/${id}`);
}

/** The four dollar figures, the burn-rate series, and the budget headline.
 *  `period` scopes the figures and the series; the budget headline is always monthly. */
export function getStats({ bucket = 'day', period = 'month' } = {}) {
  return request(`/api/stats?bucket=${bucket}&period=${period}`);
}

export function getBudget() {
  return request('/api/budget');
}

export function updateBudget(config) {
  const body =
    typeof config === 'object' && config !== null
      ? config
      : { monthly_amount: config };
  return request('/api/budget', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export function checkBudgetGuardrail(meeting) {
  return request('/api/budget/guardrail', { method: 'POST', body: JSON.stringify(meeting) });
}

export function getTierRates() {
  return request('/api/tiers');
}

export function updateTierRates(rates) {
  return request('/api/tiers', { method: 'PUT', body: JSON.stringify(rates) });
}

// --- the people directory ---

/** Who is placed at which role tier, plus the addresses nobody has placed yet. */
export function getDirectory() {
  return request('/api/people');
}

/**
 * Place people at role tiers. Returns `{directory, repricing}` — saving a role and
 * correcting the meetings that guessed at that person are the same request, so the
 * response says how much the ledger moved.
 */
export function saveDirectory(people) {
  return request('/api/people', { method: 'PUT', body: JSON.stringify({ people }) });
}

/** Forget a directory entry. Meetings keep the cost they were priced at. */
export function forgetPerson(id) {
  return request(`/api/people/${id}`, { method: 'DELETE' });
}

/** Swap a flagged meeting for the drafted email (doc 2 §5.4). */
export function convertMeeting(id) {
  return request(`/api/meetings/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ status: 'converted' }),
  });
}

// --- the email door (doc 2 §5.2) ---

/** The address to invite ShouldBe from, plus any claimed company domain. */
export function getInboundRoute() {
  return request('/api/inbound-route');
}

/** Claim a company domain so colleagues' invites are attributed here. Null clears it. */
export function setInboundDomain(domain) {
  return request('/api/inbound-route', {
    method: 'PUT',
    body: JSON.stringify({ domain }),
  });
}

/** Queued and delivered replies — how you tell "not sent yet" from "never sent". */
export function listOutbox() {
  return request('/api/outbox');
}

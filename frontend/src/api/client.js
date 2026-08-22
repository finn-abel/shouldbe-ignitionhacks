// Every backend call lives here (doc 2 §3.4) — components never fetch directly.
// Dev talks to the backend cross-origin and relies on its CORS config (doc 4 task 4-C),
// which is the same shape as production; no Vite proxy, so dev and prod cannot diverge.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

/** FastAPI returns 422 as {detail: [{loc, msg}, ...]} and 4xx/5xx as {detail: "..."}. */
function readErrorDetail(body, status) {
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = first.loc?.filter((part) => part !== 'body').join(' → ');
    return field ? `${field}: ${first.msg}` : first.msg;
  }
  return `Request failed (${status}).`;
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
  } catch {
    // A network-level failure, not an API error — usually the backend is not running.
    throw new Error(`Could not reach the ShouldBe API at ${API_BASE_URL}.`);
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(readErrorDetail(body, response.status));
  return body;
}

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

/** The four dollar figures, the burn-rate series, and the budget headline. */
export function getStats({ bucket = 'day' } = {}) {
  return request(`/api/stats?bucket=${bucket}`);
}

// --- Endpoints whose backend arrives in later steps. Wired here so the client stays the
// --- one place that knows the API surface; nothing calls them yet.

/** Step 9. */
export function getBudget() {
  return request('/api/budget');
}

/** Step 9. */
export function updateBudget(monthlyAmount) {
  return request('/api/budget', {
    method: 'PUT',
    body: JSON.stringify({ monthly_amount: monthlyAmount }),
  });
}

/** Step 9. */
export function getTierRates() {
  return request('/api/tiers');
}

/** Step 9. */
export function updateTierRates(rates) {
  return request('/api/tiers', { method: 'PUT', body: JSON.stringify(rates) });
}

/** Step 10: swap a flagged meeting for the drafted email. */
export function convertMeeting(id) {
  return request(`/api/meetings/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ status: 'converted' }),
  });
}

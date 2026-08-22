import { useEffect, useState } from 'react';
import { getInboundRoute, setInboundDomain } from '../api/client.js';

/**
 * Door A's front end (doc 2 §5.2): the address to invite ShouldBe from.
 *
 * Two ways to be recognised, shown in the order most people need them:
 *
 * - The personal invite address always works. The `+tag` carries a routing token, so an
 *   invite sent to it lands on this ledger no matter which account sent it.
 * - Claiming the company domain is the zero-effort one — after it, a colleague who has
 *   never opened ShouldBe is attributed correctly just by inviting the plain address.
 *
 * Rendered inside the Settings form, so every control here is `type="button"`: a nested
 * <form> is invalid HTML and would submit the rates form instead.
 */
export default function EmailDoor() {
  const [route, setRoute] = useState(null);
  const [domain, setDomain] = useState('');
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const loaded = await getInboundRoute();
        setRoute(loaded);
        setDomain(loaded.domain ?? '');
      } catch (failure) {
        setError(failure.message);
      }
    })();
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(route.invite_address);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const saveDomain = async (next) => {
    setError(null);
    setStatus(null);
    try {
      const saved = await setInboundDomain(next);
      setRoute(saved);
      setDomain(saved.domain ?? '');
      setStatus(saved.domain ? `Invites from @${saved.domain} land here.` : 'Domain cleared.');
    } catch (failure) {
      // 422 is the public-provider refusal, 409 is someone else holding the domain. Both
      // arrive as a readable sentence from the API, so show it rather than a generic error.
      setError(failure.message);
    }
  };

  if (error && !route) {
    return <p className="notice notice--error" role="alert">{error}</p>;
  }
  if (!route) return null;

  return (
    <section className="panel panel--surface settings__email-door">
      <div className="panel__head">
        <div className="panel__title">
          <h2>Email door</h2>
          <p className="panel__hint">
            Invite ShouldBe to a meeting the way you would invite a coworker. It reads the
            invite, prices it, and replies to the organizer.
          </p>
        </div>
      </div>

      {!route.email_configured && (
        <p className="notice" role="status">
          Inbound email is not configured on this server yet, so the address below is a
          placeholder. Meetings analyzed another way still record normally.
        </p>
      )}

      <div className="settings__basis">
        <div>
          <span>Your invite address</span>
          <strong className="figure">{route.invite_address}</strong>
          <p>
            The tag is what puts the meeting on your ledger, so keep it when you paste the
            address. Add it as a guest on any calendar event.
          </p>
        </div>
        <button
          type="button"
          className="reference-action"
          onClick={copy}
          disabled={!route.email_configured}
        >
          {copied ? 'Copied' : 'Copy address'}
        </button>
      </div>

      <label className="field">
        <span className="field__label">
          Your company domain
          <span className="field__hint">optional — leave blank to use the address above</span>
        </span>
        <input
          className="field__input"
          type="text"
          autoComplete="off"
          spellCheck="false"
          placeholder="northwind.example"
          value={domain}
          onChange={(event) => setDomain(event.target.value)}
          aria-label="Company email domain"
        />
      </label>

      <p className="settings__privacy">
        Claim it and any invite organized from an address at that domain lands on your
        ledger, even from a colleague who has never opened ShouldBe. Public providers like
        gmail.com cannot be claimed — one person would capture every other user&apos;s invites.
      </p>

      <div className="settings__actions">
        <button
          type="button"
          className="reference-action"
          onClick={() => saveDomain(domain.trim() || null)}
        >
          {domain.trim() ? 'Claim domain' : 'Clear domain'}
        </button>
        {status && <span className="settings__status" role="status">{status}</span>}
        {error && <span className="notice notice--error" role="alert">{error}</span>}
      </div>
    </section>
  );
}

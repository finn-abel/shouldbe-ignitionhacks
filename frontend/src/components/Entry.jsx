import { GOOGLE_LOGIN_URL } from '../api/client.js';

/**
 * The two ways in (doc 2 §5.5). Guest is not a demo mode or a restricted tier — it
 * resolves to a real, writable, pre-seeded user, and it needs no OAuth at all.
 */
export default function Entry({ onGuest, pending, error }) {
  return (
    <>
      <header className="masthead masthead--entry">
        <img className="masthead__logo" src="/shouldbe-logo.svg" alt="ShouldBe" />
      </header>

      <main className="entry-page">
        <div className="entry__lede">
          <p className="eyebrow">Meeting spend management</p>
          <h1 className="entry__headline">
            Meetings are the most expensive thing a company does without ever seeing a bill.
          </h1>
          <p className="entry__body">
            ShouldBe prices every meeting from blended role rates, scores whether it needed
            to happen live, and writes the email that replaces it when it didn&apos;t.
          </p>
        </div>

        <div className="entry__doors">
          <p className="entry__doors-copy">Sign in for your own ledger, or use the seeded demo.</p>
          <a className="submit entry__google" href={GOOGLE_LOGIN_URL}>
            Sign in with Google
          </a>
          <button type="button" className="entry__guest" onClick={onGuest} disabled={pending}>
            <span>{pending ? 'Opening…' : 'Continue as guest'}</span>
            {!pending && <span className="entry__guest-note">(pre-loaded for demo)</span>}
          </button>
          <p className="entry__note">
            Google reads your name and email only. ShouldBe never reads your calendar.
          </p>
        </div>

        {error && (
          <p className="notice notice--error" role="alert">
            {error}
          </p>
        )}
      </main>

      <footer className="colophon">
        <div className="colophon__inner">
          <div className="colophon__brand">
            <strong>ShouldBe</strong>
            <span>Costed from blended role-tier rates. Never individual salaries.</span>
          </div>
          <dl className="colophon__facts">
            <div>
              <dt>Security</dt>
              <dd>Calendar permissions, data retention, and access notes go here.</dd>
            </div>
            <div>
              <dt>Methodology</dt>
              <dd>Scoring model, rate assumptions, and review cadence go here.</dd>
            </div>
            <div>
              <dt>Contact</dt>
              <dd>Support owner, team alias, or rollout channel goes here.</dd>
            </div>
          </dl>
        </div>
      </footer>
    </>
  );
}

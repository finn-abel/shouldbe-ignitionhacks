import { GOOGLE_LOGIN_URL } from '../api/client.js';

/**
 * The two ways in (doc 2 §5.5). Guest is not a demo mode or a restricted tier — it
 * resolves to a real, writable, pre-seeded user, and it needs no OAuth at all.
 */
export default function Entry({ onGuest, pending, error }) {
  return (
    <section className="entry">
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
        <a className="submit entry__google" href={GOOGLE_LOGIN_URL}>
          Sign in with Google
        </a>
        <button type="button" className="entry__guest" onClick={onGuest} disabled={pending}>
          {pending ? 'Opening…' : 'Continue as guest'}
        </button>
        <p className="entry__note">
          Google sign-in reads your name and email only — never your calendar. The guest
          account is shared, fully writable, and already has a month of meetings in it.
        </p>
      </div>

      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

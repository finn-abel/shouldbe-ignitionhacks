import { GOOGLE_LOGIN_URL } from '../api/client.js';
import Colophon from './Colophon.jsx';

const tickerRows = [
  { title: 'Weekly product sync', cost: '$3,420', tag: 'trim', tone: 'leak' },
  { title: 'Launch readiness', cost: '$1,180', tag: 'keep', tone: 'defend' },
  { title: 'Status readout', cost: '$860', tag: 'memo', tone: 'reclaim' },
  { title: 'Pipeline review', cost: '$2,640', tag: 'trim', tone: 'leak' },
  { title: 'Design critique', cost: '$740', tag: 'keep', tone: 'defend' },
  { title: 'Hiring standup', cost: '$520', tag: 'memo', tone: 'reclaim' },
  { title: 'Executive check-in', cost: '$4,220', tag: 'trim', tone: 'leak' },
  { title: 'Customer escalation', cost: '$1,540', tag: 'keep', tone: 'defend' },
  { title: 'Roadmap update', cost: '$930', tag: 'memo', tone: 'reclaim' },
  { title: 'Legal review', cost: '$1,760', tag: 'keep', tone: 'defend' },
  { title: 'Metrics readout', cost: '$680', tag: 'memo', tone: 'reclaim' },
  { title: 'Quarterly planning', cost: '$5,880', tag: 'trim', tone: 'leak' },
];

const tickerLoops = [0, 1];
const reversedTickerRows = [...tickerRows].reverse();

const entrySignals = [
  { label: 'This week', value: '$18.4k' },
  { label: 'Could be async', value: '42%' },
  { label: 'Recovered', value: '31 hrs' },
];

/**
 * The two ways in. Guest is not a demo mode or a restricted tier — it
 * resolves to a real, writable, pre-seeded user, and it needs no OAuth at all.
 */
export default function Entry({ onGuest, pending, error }) {
  return (
    <>
      <header className="masthead masthead--entry">
        <img className="masthead__logo" src="/shouldbe-logo.svg" alt="ShouldBe" />
      </header>

      <main className="entry-page">
        <section className="entry-stage" aria-labelledby="entry-title">
          <div className="entry-stage__motion" aria-hidden="true">
            <div className="entry-ticker entry-ticker--left">
              <div className="entry-ticker__track">
                {tickerLoops.map((loop) => (
                  <div className="entry-ticker__set" key={`left-loop-${loop}`}>
                    {tickerRows.map((row) => (
                      <div className="entry-ticker__row" key={`left-${loop}-${row.title}`}>
                        <span>{row.title}</span>
                        <strong className="figure">{row.cost}</strong>
                        <em className={`entry-ticker__tag entry-ticker__tag--${row.tone}`}>{row.tag}</em>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>

            <div className="entry-ticker entry-ticker--right">
              <div className="entry-ticker__track">
                {tickerLoops.map((loop) => (
                  <div className="entry-ticker__set" key={`right-loop-${loop}`}>
                    {reversedTickerRows.map((row) => (
                      <div className="entry-ticker__row" key={`right-${loop}-${row.title}`}>
                        <span>{row.title}</span>
                        <strong className="figure">{row.cost}</strong>
                        <em className={`entry-ticker__tag entry-ticker__tag--${row.tone}`}>{row.tag}</em>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="entry__stack">
            <div className="entry__lede">
              <p className="eyebrow">Meeting spend management</p>
              <h1 className="entry__headline" id="entry-title">
                Before another meeting lands, see the bill it is already writing.
              </h1>
              <p className="entry__body">
                ShouldBe turns every invite into a live cost signal, flags the meetings that
                should become async, and keeps the ones worth protecting.
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

            <dl className="entry__signals" aria-label="ShouldBe snapshot">
              {entrySignals.map((signal) => (
                <div className="entry__signal" key={signal.label}>
                  <dt>{signal.label}</dt>
                  <dd className="figure">{signal.value}</dd>
                </div>
              ))}
            </dl>
          </div>

          {error && (
            <p className="notice notice--error" role="alert">
              {error}
            </p>
          )}
        </section>
      </main>

      <Colophon />
    </>
  );
}

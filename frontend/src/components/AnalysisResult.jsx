import { useState } from 'react';
import { formatMoney, formatMoneyExact, hasAmount } from '../lib/format.js';
import { verdictOf } from '../lib/verdict.js';

/** The analysis of one meeting — the money first, the reasoning second, the replacement last. */
export default function AnalysisResult({ analysis }) {
  const [copied, setCopied] = useState(false);

  if (!analysis) {
    return (
      <aside className="result result--empty" aria-live="polite">
        <div>
          <p className="eyebrow">No analysis yet</p>
          <p className="result__placeholder">
            Describe a meeting and ShouldBe will price it, judge whether it needs to happen
            live, and write the email that replaces it when it should not.
          </p>
        </div>
        <dl className="result__empty-summary" aria-label="Analysis output">
          <div>
            <dt>Cost</dt>
            <dd>Occurrence and annualized exposure</dd>
          </div>
          <div>
            <dt>Score</dt>
            <dd>Necessity from 1 to 10</dd>
          </div>
          <div>
            <dt>Draft</dt>
            <dd>Replacement email when async wins</dd>
          </div>
        </dl>
      </aside>
    );
  }

  const verdict = verdictOf(analysis.verdict);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(analysis.alternative_email);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <aside className={`result result--${verdict.tone}`} aria-live="polite">
      <header className="result__head">
        {/* The call sits above the money on purpose. The figure is the evidence; this is
            the answer to the question the user actually asked. */}
        <p className={`verdict-line verdict-line--${verdict.tone}`}>{verdict.label}</p>
        <p className="eyebrow">This occurrence costs</p>
        <p className="result__figure figure">{formatMoney(analysis.cost)}</p>
        <p className="result__exact figure">{formatMoneyExact(analysis.cost)}</p>
      </header>

      {hasAmount(analysis.annualized_cost) && (
        <p className="result__annual">
          <span>Repeats {analysis.recurrence_freq?.toLowerCase()} —</span>{' '}
          <strong className="figure">{formatMoney(analysis.annualized_cost)}</strong> a year
        </p>
      )}

      <dl className="result__facts" aria-label="Analyzed meeting facts">
        <div>
          <dt>Attendees</dt>
          <dd className="figure">{analysis.attendee_count}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd className="figure">{analysis.duration_minutes}m</dd>
        </div>
        <div>
          <dt>Cadence</dt>
          <dd>{analysis.is_recurring ? analysis.recurrence_freq?.toLowerCase() : 'one-off'}</dd>
        </div>
      </dl>

      {/* The verdict badge used to sit here too. It is stated above the cost now, and
          saying it twice on one card reads as two findings rather than one. */}
      <div className="result__verdict result__verdict--score-only">
        <span className="score">
          <span className="score__value figure">{analysis.score}</span>
          <span className="score__scale">/10 necessity</span>
        </span>
        <span
          className="score__track"
          role="img"
          aria-label={`Necessity ${analysis.score} out of 10`}
        >
          <span className="score__fill" style={{ '--score': analysis.score }} />
        </span>
      </div>

      <p className="result__reasoning">{analysis.reasoning}</p>

      {analysis.alternative_email && (
        <section className="draft">
          <div className="draft__head">
            <p className="eyebrow">Send this instead</p>
            <button type="button" className="draft__copy" onClick={copy}>
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <pre className="draft__body">{analysis.alternative_email}</pre>
        </section>
      )}
    </aside>
  );
}

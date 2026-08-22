import { useState } from 'react';
import { formatMoney, formatMoneyExact, hasAmount } from '../lib/format.js';

const VERDICT = {
  email: { label: 'Should be an email', tone: 'leak' },
  keep: { label: 'Worth the room', tone: 'defend' },
};

/** The analysis of one meeting — the money first, the reasoning second, the replacement last. */
export default function AnalysisResult({ analysis }) {
  const [copied, setCopied] = useState(false);

  if (!analysis) {
    return (
      <aside className="result result--empty" aria-live="polite">
        <p className="eyebrow">No analysis yet</p>
        <p className="result__placeholder">
          Describe a meeting and ShouldBe will price it, judge whether it needs to happen
          live, and — if it doesn&apos;t — write the email that replaces it.
        </p>
      </aside>
    );
  }

  const verdict = VERDICT[analysis.verdict];
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

      <div className="result__verdict">
        <span className={`badge badge--${verdict.tone}`}>{verdict.label}</span>
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

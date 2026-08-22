import { useState } from 'react';
import { formatMoney, formatMoneyExact, hasAmount } from '../lib/format.js';
import { ASSUMED_TIER, tierLabel } from '../lib/tiers.js';
import { verdictOf } from '../lib/verdict.js';

const STATUS = { analyzed: 'On the books', held: 'Held', converted: 'Converted' };

// Mirrors the backend cap: no single meeting is charged for more than a working day.
const MAX_BILLABLE_MINUTES = 8 * 60;

/**
 * The ledger — every analyzed meeting as a costed transaction.
 * `keep` verdicts are listed too: this is total spend, and the verdict is an attribute
 * of the transaction rather than a filter on what appears.
 */
export default function Ledger({ meetings, onConvert, converting }) {
  const [openId, setOpenId] = useState(null);

  if (!meetings.length) {
    return <p className="ledger__empty">Nothing on the books yet.</p>;
  }

  // The demo drill-down: the recurring meeting bleeding the most money per year.
  const worstOffender = meetings
    .filter((m) => m.is_recurring && hasAmount(m.annualized_cost) && m.status !== 'converted')
    .sort((a, b) => Number(b.annualized_cost) - Number(a.annualized_cost))[0];

  return (
    <ul className="ledger">
      {meetings.map((meeting) => {
        const verdict = verdictOf(meeting.verdict);
        const isWorst = meeting.id === worstOffender?.id;
        const isOpen = meeting.id === openId;

        return (
          <li
            key={meeting.id}
            className={`entry entry--${verdict.tone} ${isWorst ? 'entry--worst' : ''} ${
              meeting.status === 'converted' ? 'entry--converted' : ''
            }`}
          >
            <button
              type="button"
              className="entry__row"
              aria-expanded={isOpen}
              onClick={() => setOpenId(isOpen ? null : meeting.id)}
            >
              <span className="entry__title">
                <span className="entry__name">{meeting.title}</span>
                {isWorst && <span className="entry__flag">worst offender</span>}
              </span>

              <span className="entry__meta">
                <span className="entry__status">{STATUS[meeting.status]}</span>
              </span>

              <span className="entry__money">
                {/* Directly above the occurrence cost, and stated rather than badged:
                    the row's whole point is the call, and the figure is what backs it. */}
                <span className={`verdict-line verdict-line--${verdict.tone}`}>
                  {verdict.label}
                </span>
                <span className="entry__cost figure">{formatMoneyExact(meeting.cost)}</span>
                {hasAmount(meeting.annualized_cost) && (
                  <span className="entry__annual figure">
                    {formatMoney(meeting.annualized_cost)}/yr
                  </span>
                )}
              </span>
            </button>

            {isOpen && (
              <div className="entry__detail">
                <p className="entry__reasoning">{meeting.reasoning}</p>
                <dl className="entry__facts">
                  <div>
                    <dt>Attendees</dt>
                    <dd className="figure">{meeting.attendee_count}</dd>
                  </div>
                  <div>
                    <dt>Duration</dt>
                    <dd className="figure">
                      {meeting.duration_minutes}m
                      {meeting.duration_minutes > MAX_BILLABLE_MINUTES && (
                        <span className="entry__capped">
                          {' '}· billed {MAX_BILLABLE_MINUTES}m
                        </span>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Necessity</dt>
                    <dd className="figure">{meeting.score}/10</dd>
                  </div>
                  <div>
                    <dt>Repeats</dt>
                    <dd className="figure">
                      {meeting.is_recurring ? (meeting.recurrence_freq?.toLowerCase() ?? "yes") : "no"}
                    </dd>
                  </div>
                </dl>
                {meeting.unidentified_count > 0 && (
                  <p className="entry__estimate">
                    {meeting.unidentified_count} attendee
                    {meeting.unidentified_count === 1 ? '' : 's'} unidentified — billed at{' '}
                    {tierLabel(ASSUMED_TIER)}, so this is a floor. Give them roles under
                    Settings → People and this meeting re-prices itself.
                  </p>
                )}
                {meeting.alternative_email && (
                  <div className="draft">
                    <div className="draft__head">
                      <p className="eyebrow">Send this instead</p>
                      {meeting.status !== 'converted' && (
                        <button
                          type="button"
                          className="convert"
                          disabled={converting === meeting.id}
                          onClick={() => onConvert(meeting)}
                        >
                          {converting === meeting.id ? 'Converting…' : 'Convert to email'}
                        </button>
                      )}
                    </div>
                    <pre className="draft__body">{meeting.alternative_email}</pre>
                    {meeting.status === 'converted' && (
                      <p className="draft__reclaimed">
                        Converted — {formatMoneyExact(meeting.reclaimed_savings)} never spent.
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

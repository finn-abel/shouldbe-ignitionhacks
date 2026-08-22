import { useState } from 'react';
import { formatMoney, formatMoneyExact } from '../lib/format.js';

const VERDICT = {
  email: { label: 'Should be an email', tone: 'leak' },
  keep: { label: 'Worth the room', tone: 'defend' },
};

const STATUS = { analyzed: 'On the books', held: 'Held', converted: 'Converted' };

/**
 * The ledger — every analyzed meeting as a costed transaction (doc 2 §4.4).
 * `keep` verdicts are listed too: this is total spend, and the verdict is an attribute
 * of the transaction rather than a filter on what appears.
 */
export default function Ledger({ meetings }) {
  const [openId, setOpenId] = useState(null);

  if (!meetings.length) {
    return <p className="ledger__empty">Nothing on the books yet.</p>;
  }

  // The demo drill-down: the recurring meeting bleeding the most money per year.
  const worstOffender = meetings
    .filter((m) => m.is_recurring && m.annualized_cost && m.status !== 'converted')
    .sort((a, b) => Number(b.annualized_cost) - Number(a.annualized_cost))[0];

  return (
    <ul className="ledger">
      {meetings.map((meeting) => {
        const verdict = VERDICT[meeting.verdict];
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
                {meeting.title}
                {isWorst && <span className="entry__flag">worst offender</span>}
              </span>

              <span className="entry__meta">
                <span className={`badge badge--${verdict.tone}`}>{verdict.label}</span>
                <span className="entry__status">{STATUS[meeting.status]}</span>
              </span>

              <span className="entry__money">
                <span className="entry__cost figure">{formatMoneyExact(meeting.cost)}</span>
                {meeting.annualized_cost && (
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
                    <dd className="figure">{meeting.duration_minutes}m</dd>
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
                {meeting.alternative_email && (
                  <div className="draft">
                    <p className="eyebrow">Send this instead</p>
                    <pre className="draft__body">{meeting.alternative_email}</pre>
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

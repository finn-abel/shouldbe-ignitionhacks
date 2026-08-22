import { useCallback, useEffect, useState } from 'react';
import BurnRateChart from './BurnRateChart.jsx';
import Ledger from './Ledger.jsx';
import { convertMeeting, getStats, listMeetings } from '../api/client.js';
import { formatMoney, formatMoneyExact, hasAmount } from '../lib/format.js';

const BUCKETS = ['day', 'week'];

const PERIODS = [
  { key: 'month', label: 'This month' },
  { key: 'all', label: 'All time' },
];

/** The four dollar concepts of doc 2 §6, kept visibly distinct. */
const TILES = [
  { key: 'necessary_spend', label: 'Necessary', note: 'worth the room', tone: 'ink' },
  { key: 'avoidable_spend', label: 'Avoidable', note: 'flagged, held anyway', tone: 'leak' },
  { key: 'reclaimed_savings', label: 'Reclaimed', note: 'never spent', tone: 'reclaim' },
];

export default function Dashboard({ refreshKey }) {
  const [bucket, setBucket] = useState('day');
  const [period, setPeriod] = useState('month');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [converting, setConverting] = useState(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [stats, meetings] = await Promise.all([
        getStats({ bucket, period }),
        listMeetings(),
      ]);
      setData({ stats, meetings });
    } catch (failure) {
      setError(failure.message);
    }
  }, [bucket, period]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  /**
   * Convert a flagged meeting (doc 2 §5.4).
   *
   * The row flips immediately so the click has an answer, but every dollar comes back
   * from the server. The browser deriving money is the one thing this app must not do:
   * an earlier version nudged the totals here and got it subtly wrong — the chart nudge
   * compared a raw date against a Monday bucket and silently did nothing, and the
   * over-budget percentage was never recomputed at all, so the headline disagreed with
   * the tiles until the refetch landed. Optimism belongs on the action, not on the
   * arithmetic. On failure the pre-click snapshot goes back.
   */
  const convert = async (meeting) => {
    const snapshot = data;
    setConverting(meeting.id);
    setError(null);

    setData((current) => ({
      ...current,
      meetings: current.meetings.map((row) =>
        row.id === meeting.id
          ? { ...row, status: 'converted', reclaimed_savings: meeting.cost }
          : row,
      ),
    }));

    try {
      await convertMeeting(meeting.id);
      await load();
    } catch (failure) {
      setData(snapshot);
      setError(failure.message);
    } finally {
      setConverting(null);
    }
  };

  if (error) return <p className="notice notice--error" role="alert">{error}</p>;
  if (!data) return <p className="dashboard__loading">Reading the ledger…</p>;

  const { stats, meetings } = data;
  const { budget } = stats;
  const over = budget.is_over_budget;
  const usagePercent = Math.max(0, Math.min(100, Number(budget.usage_percent ?? 0)));
  const budgetWarn = !over && Number(budget.threshold ?? 0) >= 80;
  const budgetScopeLabel = budget.scope_name
    ? `${budget.scope_name} ${budget.scope_type}`
    : 'Current';
  const actionableMeetings = meetings
    .filter((meeting) => meeting.verdict === 'email' && meeting.status !== 'converted');
  const convertedMeetings = meetings.filter((meeting) => meeting.status === 'converted');
  const defendedMeetings = meetings.filter((meeting) => meeting.verdict === 'keep');
  const annualExposure = actionableMeetings.reduce(
    (sum, meeting) => sum + Number(meeting.annualized_cost ?? 0),
    0,
  );
  const priorityMeetings = [...actionableMeetings]
    .sort((a, b) => Number(b.annualized_cost ?? b.cost ?? 0) - Number(a.annualized_cost ?? a.cost ?? 0))
    .slice(0, 3);
  const largestExposure = priorityMeetings.find((meeting) => hasAmount(meeting.annualized_cost));

  return (
    <div className="dashboard">
      <section
        className={`dashboard-hero ${over ? 'dashboard-hero--over' : ''} ${
          budgetWarn ? 'dashboard-hero--warn' : ''
        }`}
      >
        <div className={`headline ${over ? 'headline--over' : ''}`}>
          <p className="eyebrow">{budgetScopeLabel} meeting spend this month</p>
          <p className="headline__figure figure">{formatMoney(budget.month_spend)}</p>

          {budget.monthly_amount === null ? (
            <p className="headline__verdict">No budget set yet.</p>
          ) : (
            <>
              <p className="headline__verdict">
                <strong className="figure">
                  {Math.round(budget.usage_percent ?? 0)}%
                </strong>{' '}
                used of a {formatMoney(budget.monthly_amount)} budget
                <span className="headline__delta figure">
                  {over ? '+' : ''}
                  {formatMoneyExact(budget.difference)}
                </span>
              </p>
              <div className="budget-meter" style={{ '--budget-usage': usagePercent }}>
                <span className="budget-meter__fill" />
                {[50, 80, 100].map((mark) => (
                  <span
                    key={mark}
                    className="budget-meter__mark"
                    style={{ '--budget-mark': mark }}
                  >
                    {mark}%
                  </span>
                ))}
              </div>
              <p className="headline__remaining">
                {over ? 'Over budget by' : 'Remaining budget'}{' '}
                <strong className="figure">
                  {formatMoneyExact(
                    over ? Math.abs(Number(budget.remaining_amount ?? 0)) : budget.remaining_amount,
                  )}
                </strong>
              </p>
            </>
          )}
        </div>

        <dl className="dashboard-signals" aria-label="Operating snapshot">
          <div className="dashboard-signal dashboard-signal--leak">
            <dt>Open review</dt>
            <dd className="figure">{actionableMeetings.length}</dd>
            <p>async candidates still on the ledger</p>
          </div>
          <div className="dashboard-signal dashboard-signal--reclaim">
            <dt>Recovered</dt>
            <dd className="figure">{formatMoney(stats.reclaimed_savings)}</dd>
            <p>{convertedMeetings.length} converted to email</p>
          </div>
          <div className="dashboard-signal dashboard-signal--defend">
            <dt>Protected</dt>
            <dd className="figure">{defendedMeetings.length}</dd>
            <p>meetings judged worth the room</p>
          </div>
        </dl>
      </section>

      <section className="money">
        <div className="tiles__head">
          <p className="eyebrow">
            {period === 'month' ? 'This month' : 'All time'} — spend and savings
          </p>
          <div className="chips">
            {PERIODS.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                className="chip"
                aria-pressed={period === key}
                onClick={() => setPeriod(key)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <section className={`tiles ${converting ? 'tiles--settling' : ''}`}>
          <div className="tile tile--total">
            <p className="tile__label">Total spend</p>
            <p className="tile__figure figure">{formatMoney(stats.total_spend)}</p>
            <p className="tile__note">every meeting that happened</p>
          </div>
          {TILES.map(({ key, label, note, tone }) => (
            <div className={`tile tile--${tone}`} key={key}>
              <p className="tile__label">{label}</p>
              <p className="tile__figure figure">{formatMoney(stats[key])}</p>
              <p className="tile__note">{note}</p>
            </div>
          ))}
        </section>
      </section>

      <div className="dashboard-board">
        <section className="panel panel--surface panel--chart">
          <div className="panel__head">
            <h2>Burn rate</h2>
            <div className="chips">
              {BUCKETS.map((option) => (
                <button
                  key={option}
                  type="button"
                  className="chip"
                  aria-pressed={bucket === option}
                  onClick={() => setBucket(option)}
                >
                  by {option}
                </button>
              ))}
            </div>
          </div>
          <BurnRateChart buckets={stats.spend_over_time} bucket={bucket} />
        </section>

        <section className="panel panel--surface panel--queue">
          <div className="panel__head">
            <h2>Attention queue</h2>
            <p className="panel__count figure">{formatMoney(annualExposure)}/yr open</p>
          </div>

          {priorityMeetings.length ? (
            <>
              <ol className="review-list">
                {priorityMeetings.map((meeting) => (
                  <li className="review-item" key={meeting.id}>
                    <span className="review-item__title">{meeting.title}</span>
                    <span className="review-item__meta">
                      <span className="figure">{formatMoneyExact(meeting.cost)}</span>
                      {hasAmount(meeting.annualized_cost) && (
                        <span className="figure">{formatMoney(meeting.annualized_cost)}/yr</span>
                      )}
                    </span>
                  </li>
                ))}
              </ol>

              {largestExposure && (
                <p className="queue-note">
                  Largest recurring exposure: <strong>{largestExposure.title}</strong>
                </p>
              )}
            </>
          ) : (
            <p className="queue-empty">
              No open async candidates. New analyses that should become email will land here.
            </p>
          )}
        </section>
      </div>

      <section className="panel panel--surface panel--ledger">
        <div className="panel__head">
          <h2>The ledger</h2>
          <div className="panel__meta">
            <p className="panel__count figure">{meetings.length} meetings</p>
            <p className="panel__hint">Open a row for reasoning, recurrence, and replacement email.</p>
          </div>
        </div>
        <Ledger meetings={meetings} onConvert={convert} converting={converting} />
      </section>
    </div>
  );
}

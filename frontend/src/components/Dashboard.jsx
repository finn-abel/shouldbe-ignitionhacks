import { useCallback, useEffect, useState } from 'react';
import BurnRateChart from './BurnRateChart.jsx';
import Ledger from './Ledger.jsx';
import { convertMeeting, getStats, listMeetings } from '../api/client.js';
import { formatMoney, formatMoneyExact } from '../lib/format.js';

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

  return (
    <div className="dashboard">
      <section className={`headline ${over ? 'headline--over' : ''}`}>
        <p className="eyebrow">Meeting spend this month</p>
        <p className="headline__figure figure">{formatMoney(budget.month_spend)}</p>

        {budget.monthly_amount === null ? (
          <p className="headline__verdict">No budget set yet.</p>
        ) : (
          <p className="headline__verdict">
            <strong className="figure">
              {Math.abs(Math.round(budget.percent_over ?? 0))}%
            </strong>{' '}
            {over ? 'over' : 'under'} a {formatMoney(budget.monthly_amount)} budget
            <span className="headline__delta figure">
              {over ? '+' : ''}
              {formatMoneyExact(budget.difference)}
            </span>
          </p>
        )}
      </section>

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

      <section className="panel">
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

      <section className="panel">
        <div className="panel__head">
          <h2>The ledger</h2>
          <p className="panel__count figure">{meetings.length} meetings</p>
        </div>
        <Ledger meetings={meetings} onConvert={convert} converting={converting} />
      </section>
    </div>
  );
}

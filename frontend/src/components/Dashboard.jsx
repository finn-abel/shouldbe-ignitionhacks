import { useCallback, useEffect, useState } from 'react';
import BurnRateChart from './BurnRateChart.jsx';
import Ledger from './Ledger.jsx';
import { convertMeeting, getStats, listMeetings } from '../api/client.js';
import { formatMoney, formatMoneyExact } from '../lib/format.js';

const BUCKETS = ['day', 'week'];

/** The four dollar concepts of doc 2 §6, kept visibly distinct. */
const TILES = [
  { key: 'necessary_spend', label: 'Necessary', note: 'worth the room', tone: 'ink' },
  { key: 'avoidable_spend', label: 'Avoidable', note: 'flagged, held anyway', tone: 'leak' },
  { key: 'reclaimed_savings', label: 'Reclaimed', note: 'never spent', tone: 'reclaim' },
];

export default function Dashboard({ refreshKey }) {
  const [bucket, setBucket] = useState('day');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [converting, setConverting] = useState(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [stats, meetings] = await Promise.all([getStats({ bucket }), listMeetings()]);
      setData({ stats, meetings });
    } catch (failure) {
      setError(failure.message);
    }
  }, [bucket]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  /**
   * Convert a flagged meeting (doc 2 §5.4). The row and the three affected figures move
   * at once so the action feels instant, then the server's own numbers replace them —
   * this is a local nudge to already-derived totals, never a re-derivation of the money
   * model in the browser. On failure the snapshot goes back and the error is shown.
   */
  const convert = async (meeting) => {
    const snapshot = data;
    const cost = Number(meeting.cost);
    setConverting(meeting.id);
    setError(null);

    setData((current) => ({
      meetings: current.meetings.map((row) =>
        row.id === meeting.id
          ? { ...row, status: 'converted', reclaimed_savings: meeting.cost }
          : row,
      ),
      stats: {
        ...current.stats,
        total_spend: Number(current.stats.total_spend) - cost,
        avoidable_spend: Number(current.stats.avoidable_spend) - cost,
        reclaimed_savings: Number(current.stats.reclaimed_savings) + cost,
        spend_over_time: current.stats.spend_over_time.map((point) =>
          point.period === meeting.created_at.slice(0, 10)
            ? { ...point, amount: Number(point.amount) - cost }
            : point,
        ),
        budget: {
          ...current.stats.budget,
          month_spend: Number(current.stats.budget.month_spend) - cost,
        },
      },
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

      <section className="tiles">
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

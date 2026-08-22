import { useEffect, useState } from 'react';
import { getBudget, getTierRates, updateBudget, updateTierRates } from '../api/client.js';
import { formatMoney } from '../lib/format.js';

const TIERS = [
  { key: 'ic', label: 'IC', note: 'engineers, designers, analysts' },
  { key: 'senior', label: 'Senior', note: 'staff and senior specialists' },
  { key: 'manager', label: 'Manager', note: 'people and program leads' },
  { key: 'exec', label: 'Exec', note: 'directors and above' },
];

/**
 * The cost basis and the budget (doc 2 §4.2, §4.3).
 * Rates are per role tier and blended by design — an individual's pay is not
 * representable in this shape, which is the point (doc 1's privacy stance).
 */
export default function Settings({ onSaved }) {
  const [rates, setRates] = useState(null);
  const [budget, setBudget] = useState('');
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [loadedRates, loadedBudget] = await Promise.all([getTierRates(), getBudget()]);
        setRates(loadedRates);
        setBudget(loadedBudget.monthly_amount ?? '');
      } catch (failure) {
        setError(failure.message);
      }
    })();
  }, []);

  const save = async (event) => {
    event.preventDefault();
    setError(null);
    setStatus(null);
    try {
      const [savedRates] = await Promise.all([
        updateTierRates(
          Object.fromEntries(TIERS.map(({ key }) => [key, Number(rates[key]) || 0])),
        ),
        updateBudget(Number(budget) || 0),
      ]);
      setRates(savedRates);
      setStatus('Saved.');
      onSaved?.();
    } catch (failure) {
      setError(failure.message);
    }
  };

  if (error && !rates) return <p className="notice notice--error" role="alert">{error}</p>;
  if (!rates) return <p className="dashboard__loading">Loading settings…</p>;

  const blendedHour = TIERS.reduce((sum, { key }) => sum + (Number(rates[key]) || 0), 0);

  return (
    <form className="settings" onSubmit={save}>
      <section className="panel">
        <div className="panel__head">
          <h2>Monthly meeting budget</h2>
        </div>
        <label className="field">
          <span className="field__label">
            What this team should spend on meetings each month
          </span>
          <div className="money-input">
            <span aria-hidden="true">$</span>
            <input
              className="field__input figure"
              type="number"
              min="0"
              step="100"
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
              aria-label="Monthly meeting budget in dollars"
            />
          </div>
        </label>
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2>Role-tier rates</h2>
          <p className="panel__count figure">
            {formatMoney(blendedHour)}/hr with one of each
          </p>
        </div>

        <p className="settings__privacy">
          <strong>Blended role rates only — never individual salaries.</strong> A meeting is
          costed from the loaded hourly rate of each tier in the room. No screen and no email
          in ShouldBe ever shows one person&apos;s number.
        </p>

        <div className="rates">
          {TIERS.map(({ key, label, note }) => (
            <label className="rate" key={key}>
              <span className="rate__label">
                {label}
                <span className="rate__note">{note}</span>
              </span>
              <div className="money-input money-input--compact">
                <span aria-hidden="true">$</span>
                <input
                  className="field__input figure"
                  type="number"
                  min="0"
                  step="5"
                  value={rates[key]}
                  onChange={(event) =>
                    setRates((prev) => ({ ...prev, [key]: event.target.value }))
                  }
                  aria-label={`${label} loaded hourly rate in dollars`}
                />
                <span className="rate__unit">/hr</span>
              </div>
            </label>
          ))}
        </div>

        <p className="settings__caveat">
          New rates price meetings analyzed from now on. Meetings already in the ledger keep
          what they cost — the ledger records what happened, it does not re-price it.
        </p>
      </section>

      {error && <p className="notice notice--error" role="alert">{error}</p>}

      <div className="settings__actions">
        <button className="submit" type="submit">Save settings</button>
        {status && <span className="settings__status" role="status">{status}</span>}
      </div>
    </form>
  );
}

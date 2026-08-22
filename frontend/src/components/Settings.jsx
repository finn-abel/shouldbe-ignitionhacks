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

  /** A field holds a usable amount only if it is non-empty and a real number. */
  const amountOf = (value) => {
    const text = String(value ?? '').trim();
    if (text === '') return null;
    const amount = Number(text);
    return Number.isFinite(amount) && amount >= 0 ? amount : null;
  };

  const save = async (event) => {
    event.preventDefault();
    setError(null);
    setStatus(null);

    // Every tier must carry a real rate. Coercing a blank to 0 would silently make a
    // whole role free and understate every meeting priced afterwards.
    const blankRate = TIERS.find(({ key }) => amountOf(rates[key]) === null);
    if (blankRate) {
      setError(`Give ${blankRate.label} an hourly rate before saving.`);
      return;
    }

    // A blank budget means "not set", which is a different thing from a budget of zero:
    // zero cannot be exceeded by a percentage and reads as permanently over budget. Leave
    // it alone rather than writing a number the user never typed.
    const monthlyAmount = amountOf(budget);
    if (String(budget ?? '').trim() !== '' && monthlyAmount === null) {
      setError('The monthly budget must be a positive amount.');
      return;
    }

    try {
      const savedRates = await updateTierRates(
        Object.fromEntries(TIERS.map(({ key }) => [key, amountOf(rates[key])])),
      );
      if (monthlyAmount !== null) await updateBudget(monthlyAmount);

      setRates(savedRates);
      setStatus(monthlyAmount === null ? 'Rates saved. No budget set.' : 'Saved.');
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
            <span className="field__hint">leave blank for no budget</span>
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

import { useEffect, useState } from 'react';
import { getBudget, getTierRates, updateBudget, updateTierRates } from '../api/client.js';
import EmailDoor from './EmailDoor.jsx';
import { formatMoney, formatMoneyExact } from '../lib/format.js';

const TIERS = [
  {
    key: 'ic',
    label: 'IT-02',
    note: 'intermediate delivery, analysis, development',
    salary: '$85,854-$105,080',
    rate: '48.96',
  },
  {
    key: 'senior',
    label: 'IT-03',
    note: 'senior specialist, technical lead',
    salary: '$101,343-$125,914',
    rate: '58.27',
  },
  {
    key: 'manager',
    label: 'IT-04',
    note: 'manager, architect, specialized expert',
    salary: '$116,037-$144,434',
    rate: '66.79',
  },
  {
    key: 'exec',
    label: 'EX-03 / DG',
    note: 'Director General reference level',
    salary: '$172,548-$202,918',
    rate: '96.27',
  },
];

const FEDERAL_REFERENCE_RATES = Object.fromEntries(TIERS.map(({ key, rate }) => [key, rate]));
const LEGACY_PLACEHOLDER_RATES = { ic: '75', senior: '110', manager: '150', exec: '250' };
const FEDERAL_HOURS = '1,950 hrs/year';

const isLegacyPlaceholderRates = (loadedRates) =>
  TIERS.every(({ key }) => Number(loadedRates[key]) === Number(LEGACY_PLACEHOLDER_RATES[key]));

/**
 * The cost basis and the budget (doc 2 §4.2, §4.3).
 * Rates are per role tier and blended by design — an individual's pay is not
 * representable in this shape, which is the point (doc 1's privacy stance).
 */
export default function Settings({ theme, onThemeChange, onSaved }) {
  const [rates, setRates] = useState(null);
  const [budget, setBudget] = useState('');
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [loadedRates, loadedBudget] = await Promise.all([getTierRates(), getBudget()]);
        if (isLegacyPlaceholderRates(loadedRates)) {
          setRates(FEDERAL_REFERENCE_RATES);
          setStatus('Federal reference rates loaded. Save settings to apply.');
        } else {
          setRates(loadedRates);
        }
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

  const useFederalReferenceRates = () => {
    setRates((prev) => ({ ...prev, ...FEDERAL_REFERENCE_RATES }));
    setError(null);
    setStatus('Federal reference rates loaded. Save settings to apply.');
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
  const monthlyAmount = amountOf(budget);
  const budgetLabel = String(budget ?? '').trim() === '' ? 'Unset' : formatMoney(monthlyAmount);

  return (
    <form className="settings" onSubmit={save} noValidate>
      <header className="settings-command">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>Govern the cost model without exposing salary data.</h1>
          <p>
            Tune the operating budget, theme, and blended federal reference rates used
            to price meetings from now on.
          </p>
        </div>
        <dl className="settings-summary" aria-label="Current settings summary">
          <div>
            <dt>Theme</dt>
            <dd>{theme === 'dark' ? 'Dark' : 'Light'}</dd>
          </div>
          <div>
            <dt>Budget</dt>
            <dd className="figure">{budgetLabel}</dd>
          </div>
          <div>
            <dt>Rate basis</dt>
            <dd>IT + DG</dd>
          </div>
        </dl>
      </header>

      <div className="settings-grid">
        <section className="panel panel--surface settings__theme">
          <div className="panel__head">
            <h2>Appearance</h2>
          </div>
          <div className="theme-switch" role="group" aria-label="Theme">
            <button
              type="button"
              className="theme-switch__option"
              aria-pressed={theme === 'light'}
              onClick={() => onThemeChange('light')}
            >
              Light
            </button>
            <button
              type="button"
              className="theme-switch__option"
              aria-pressed={theme === 'dark'}
              onClick={() => onThemeChange('dark')}
            >
              Dark
            </button>
          </div>
        </section>

        <section className="panel panel--surface settings__budget">
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
                step="0.01"
                inputMode="decimal"
                value={budget}
                onChange={(event) => setBudget(event.target.value)}
                aria-label="Monthly meeting budget in dollars"
              />
            </div>
          </label>
        </section>
      </div>

      <section className="panel panel--surface settings__rates">
        <div className="panel__head">
          <div className="panel__title">
            <h2>Federal pay-scale rates</h2>
            <p className="panel__hint">Midpoint of public salary bands converted to hourly rates.</p>
          </div>
          <p className="panel__count figure">
            {formatMoney(blendedHour)}/hr with one of each
          </p>
        </div>

        <div className="settings__basis">
          <div>
            <span>Reference basis</span>
            <strong>IT-02, IT-03, IT-04, and EX-03 / Director General</strong>
            <p>
              Gross annual pay divided by {FEDERAL_HOURS}. Benefits, at-risk pay,
              overtime, and overhead are not included.
            </p>
          </div>
          <button type="button" className="reference-action" onClick={useFederalReferenceRates}>
            Use federal reference rates
          </button>
        </div>

        <p className="settings__privacy">
          <strong>Blended role rates only — never individual salaries.</strong> A meeting is
          costed from the configured hourly rate of each tier in the room. No screen and no email
          in ShouldBe ever shows one person&apos;s number.
        </p>

        <div className="rates">
          {TIERS.map(({ key, label, note, salary, rate }) => (
            <label className="rate" key={key}>
              <span className="rate__label">
                <span className="rate__name">{label}</span>
                <span className="rate__note">{note}</span>
                <span className="rate__salary">{salary} annual range</span>
              </span>
              <div className="money-input money-input--compact">
                <span aria-hidden="true">$</span>
                <input
                  className="field__input figure"
                  type="number"
                  min="0"
                  step="0.01"
                  inputMode="decimal"
                  value={rates[key]}
                  onChange={(event) =>
                    setRates((prev) => ({ ...prev, [key]: event.target.value }))
                  }
                  aria-label={`${label} hourly reference rate in dollars`}
                />
                <span className="rate__unit">/hr</span>
              </div>
              <span className="rate__default figure">
                Ref {formatMoneyExact(rate)}/hr
              </span>
            </label>
          ))}
        </div>

        <div className="settings__caveat">
          <p>
            New rates price meetings analyzed from now on. Meetings already in the ledger keep
            what they cost — the ledger records what happened, it does not re-price it.
          </p>
          <p>
            Source references:{' '}
            <a href="https://fedpay.ca/blog/it-group-salary-federal-government" target="_blank" rel="noreferrer">
              FedPay IT group
            </a>
            {' '}and{' '}
            <a href="https://fedpay.ca/salary/ex" target="_blank" rel="noreferrer">
              FedPay EX
            </a>.
          </p>
        </div>
      </section>

      <EmailDoor />

      {error && <p className="notice notice--error" role="alert">{error}</p>}

      <div className="settings__actions panel--surface">
        <button className="submit" type="submit">Save settings</button>
        {status && <span className="settings__status" role="status">{status}</span>}
      </div>
    </form>
  );
}

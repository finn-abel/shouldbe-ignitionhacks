import { useEffect, useState } from 'react';
import { getBudget, getTierRates, updateBudget, updateTierRates } from '../api/client.js';
import EmailDoor from './EmailDoor.jsx';
import People from './People.jsx';
import { TIERS } from '../lib/tiers.js';
import { formatMoney, formatMoneyExact } from '../lib/format.js';

const FEDERAL_REFERENCE_RATES = Object.fromEntries(TIERS.map(({ key, rate }) => [key, rate]));
const LEGACY_PLACEHOLDER_RATES = { ic: '75', senior: '110', manager: '150', exec: '250' };
const FEDERAL_HOURS = '1,950 hrs/year';
const BUDGET_SCOPES = [
  { key: 'user', label: 'User', defaultName: 'Personal' },
  { key: 'team', label: 'Team', defaultName: 'Team' },
  { key: 'department', label: 'Department', defaultName: 'Department' },
];

const EMPTY_BUDGETS = Object.fromEntries(
  BUDGET_SCOPES.map(({ key, defaultName }) => [
    key,
    { scope_type: key, scope_name: defaultName, monthly_amount: '' },
  ]),
);

const isLegacyPlaceholderRates = (loadedRates) =>
  TIERS.every(({ key }) => Number(loadedRates[key]) === Number(LEGACY_PLACEHOLDER_RATES[key]));

function readBudgetConfig(loadedBudget) {
  const next = {
    user: { ...EMPTY_BUDGETS.user, monthly_amount: loadedBudget.monthly_amount ?? '' },
    team: { ...EMPTY_BUDGETS.team },
    department: { ...EMPTY_BUDGETS.department },
  };

  for (const budget of loadedBudget.budgets ?? []) {
    if (!next[budget.scope_type]) continue;
    next[budget.scope_type] = {
      scope_type: budget.scope_type,
      scope_name: budget.scope_name,
      monthly_amount: budget.monthly_amount ?? '',
    };
  }

  return {
    budgets: next,
    activeScope: loadedBudget.active_scope_type ?? 'user',
  };
}

/**
 * The operational cost basis and routing setup: budget guardrails, blended role
 * rates, people placement, and the email door.
 */
export default function Configuration({ onSaved }) {
  const [rates, setRates] = useState(null);
  const [budgets, setBudgets] = useState(EMPTY_BUDGETS);
  const [activeScope, setActiveScope] = useState('user');
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [loadedRates, loadedBudget] = await Promise.all([getTierRates(), getBudget()]);
        if (isLegacyPlaceholderRates(loadedRates)) {
          setRates(FEDERAL_REFERENCE_RATES);
          setStatus('Federal reference rates loaded. Save configuration to apply.');
        } else {
          setRates(loadedRates);
        }
        const config = readBudgetConfig(loadedBudget);
        setBudgets(config.budgets);
        setActiveScope(config.activeScope);
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
    setStatus('Federal reference rates loaded. Save configuration to apply.');
  };

  const setBudgetField = (scope, key, value) => {
    setBudgets((prev) => ({
      ...prev,
      [scope]: { ...prev[scope], [key]: value },
    }));
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

    const invalidBudget = BUDGET_SCOPES.find(({ key }) => {
      const row = budgets[key] ?? EMPTY_BUDGETS[key];
      return String(row.monthly_amount ?? '').trim() !== '' && amountOf(row.monthly_amount) === null;
    });
    if (invalidBudget) {
      const row = budgets[invalidBudget.key] ?? EMPTY_BUDGETS[invalidBudget.key];
      setError(`${row.scope_name || invalidBudget.defaultName} budget must be a positive amount.`);
      return;
    }

    const budgetRows = BUDGET_SCOPES.map(({ key, defaultName }) => {
      const row = budgets[key] ?? EMPTY_BUDGETS[key];
      const amount = amountOf(row.monthly_amount);
      return {
        scope_type: key,
        scope_name: String(row.scope_name || defaultName).trim(),
        monthly_amount: amount,
        is_active: activeScope === key,
      };
    });

    try {
      const savedRates = await updateTierRates(
        Object.fromEntries(TIERS.map(({ key }) => [key, amountOf(rates[key])])),
      );
      const activeBudget = budgetRows.find((row) => row.scope_type === activeScope) ?? budgetRows[0];
      const savedBudget = await updateBudget({
        active_scope_type: activeBudget.scope_type,
        active_scope_name: activeBudget.scope_name,
        monthly_amount: budgetRows.find((row) => row.scope_type === 'user')?.monthly_amount ?? null,
        budgets: budgetRows,
      });

      setRates(savedRates);
      const config = readBudgetConfig(savedBudget);
      setBudgets(config.budgets);
      setActiveScope(config.activeScope);
      setStatus('Saved.');
      onSaved?.();
    } catch (failure) {
      setError(failure.message);
    }
  };

  if (error && !rates) return <p className="notice notice--error" role="alert">{error}</p>;
  if (!rates) return <p className="dashboard__loading">Loading configuration...</p>;

  const blendedHour = TIERS.reduce((sum, { key }) => sum + (Number(rates[key]) || 0), 0);
  const activeBudget = budgets[activeScope] ?? EMPTY_BUDGETS.user;
  const activeAmount = amountOf(activeBudget.monthly_amount);
  const budgetLabel =
    String(activeBudget.monthly_amount ?? '').trim() === '' ? 'Unset' : formatMoney(activeAmount);

  return (
    <form className="settings configuration" onSubmit={save} noValidate>
      <header className="settings-command">
        <div>
          <p className="eyebrow">Configuration</p>
          <h1>Govern the cost model without exposing salary data.</h1>
          <p>
            Tune the operating budget, blended federal reference rates, people directory,
            and email routing used to price meetings from now on.
          </p>
        </div>
        <dl className="settings-summary" aria-label="Current configuration summary">
          <div>
            <dt>Guardrail</dt>
            <dd className="figure">{budgetLabel}</dd>
          </div>
          <div>
            <dt>Blended</dt>
            <dd className="figure">{formatMoney(blendedHour)}/hr</dd>
          </div>
          <div>
            <dt>Rate basis</dt>
            <dd>IT + DG</dd>
          </div>
        </dl>
      </header>

      <section className="panel panel--surface settings__budget">
        <div className="panel__head">
          <h2>Monthly meeting budgets</h2>
        </div>
        <div className="budget-rows">
          {BUDGET_SCOPES.map(({ key, label, defaultName }) => {
            const row = budgets[key] ?? EMPTY_BUDGETS[key];
            return (
              <div className="budget-row" key={key}>
                <label className="field budget-row__name">
                  <span className="field__label">{label}</span>
                  <input
                    className="field__input"
                    value={row.scope_name}
                    disabled={key === 'user'}
                    onChange={(event) => setBudgetField(key, 'scope_name', event.target.value)}
                    placeholder={defaultName}
                    aria-label={`${label} budget name`}
                  />
                </label>
                <label className="field budget-row__amount">
                  <span className="field__label">Monthly</span>
                  <div className="money-input">
                    <span aria-hidden="true">$</span>
                    <input
                      className="field__input figure"
                      type="number"
                      min="0"
                      step="0.01"
                      inputMode="decimal"
                      value={row.monthly_amount}
                      onChange={(event) =>
                        setBudgetField(key, 'monthly_amount', event.target.value)
                      }
                      aria-label={`${label} monthly meeting budget in dollars`}
                    />
                  </div>
                </label>
                <button
                  type="button"
                  className="scope-action"
                  aria-pressed={activeScope === key}
                  onClick={() => setActiveScope(key)}
                >
                  Active
                </button>
              </div>
            );
          })}
        </div>
      </section>

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
          <strong>Blended role rates only - never individual salaries.</strong> A meeting is
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
            what they cost - the ledger records what happened, it does not re-price it.
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

      <People onRepriced={onSaved} />

      <EmailDoor />

      {error && <p className="notice notice--error" role="alert">{error}</p>}

      <div className="settings__actions panel--surface">
        <button className="submit" type="submit">Save configuration</button>
        {status && <span className="settings__status" role="status">{status}</span>}
      </div>
    </form>
  );
}

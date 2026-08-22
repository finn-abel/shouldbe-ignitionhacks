import { useState } from 'react';

const TIERS = [
  { key: 'ic', label: 'IT-02', note: 'delivery / analysis' },
  { key: 'senior', label: 'IT-03', note: 'senior specialist' },
  { key: 'manager', label: 'IT-04', note: 'manager / architect' },
  { key: 'exec', label: 'EX-03 / DG', note: 'director general' },
];

const DURATIONS = [15, 30, 45, 60, 90];
const FREQUENCIES = ['DAILY', 'WEEKLY', 'BIWEEKLY', 'MONTHLY'];

const EMPTY = {
  title: '',
  description: '',
  duration_minutes: 30,
  organizer_email: '',
  is_recurring: true,
  recurrence_freq: 'WEEKLY',
};

const EMPTY_ATTENDEES = { ic: 8, senior: 0, manager: 1, exec: 0 };

/**
 * Door B — the manual form (doc 2 §5.1). It only collects and submits: the cost is
 * computed by the backend and never duplicated here, so the number on screen is always
 * the number in the ledger.
 */
export default function AnalyzeForm({ onAnalyzed, pending, error, notice }) {
  const [fields, setFields] = useState(EMPTY);
  const [attendees, setAttendees] = useState(EMPTY_ATTENDEES);

  const headcount = Object.values(attendees).reduce((sum, n) => sum + n, 0);
  const cadence = fields.is_recurring ? fields.recurrence_freq.toLowerCase() : 'one-off';

  const set = (key) => (event) => {
    const target = event.target;
    setFields((prev) => ({
      ...prev,
      [key]: target.type === 'checkbox' ? target.checked : target.value,
    }));
  };

  const setTier = (key, next) =>
    setAttendees((prev) => ({ ...prev, [key]: Math.max(0, next) }));

  const submit = (event) => {
    event.preventDefault();
    onAnalyzed({
      ...fields,
      duration_minutes: Number(fields.duration_minutes),
      attendees,
      recurrence_freq: fields.is_recurring ? fields.recurrence_freq : null,
    });
  };

  return (
    <form className="sheet" onSubmit={submit} noValidate>
      <div className="sheet__head">
        <p className="eyebrow">Meeting details</p>
        <h2>What are you about to spend?</h2>
      </div>

      <dl className="sheet__summary" aria-label="Current meeting assumptions">
        <div>
          <dt>People</dt>
          <dd className="figure">{headcount}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd className="figure">{fields.duration_minutes}m</dd>
        </div>
        <div>
          <dt>Cadence</dt>
          <dd>{cadence}</dd>
        </div>
      </dl>

      <label className="field">
        <span className="field__label">Title</span>
        <input
          className="field__input"
          value={fields.title}
          onChange={set('title')}
          placeholder="Weekly Engineering Standup"
          required
          autoFocus
        />
      </label>

      <label className="field">
        <span className="field__label">
          Agenda <span className="field__hint">optional — it sharpens the verdict</span>
        </span>
        <textarea
          className="field__input field__input--area"
          value={fields.description}
          onChange={set('description')}
          rows={2}
          placeholder="Round the room on what everyone is working on."
        />
      </label>

      <fieldset className="field">
        <legend className="field__label">Duration</legend>
        <div className="chips">
          {DURATIONS.map((minutes) => (
            <button
              key={minutes}
              type="button"
              className="chip"
              aria-pressed={Number(fields.duration_minutes) === minutes}
              onClick={() => setFields((prev) => ({ ...prev, duration_minutes: minutes }))}
            >
              {minutes}m
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="field">
        <legend className="field__label">
          Who is in the room
          <span className="field__hint figure">{headcount} attending</span>
        </legend>
        <div className="tiers">
          {TIERS.map(({ key, label, note }) => (
            <div className="tier" key={key}>
              <span className="tier__label">
                <span className="tier__name">{label}</span>
                <span className="tier__note">{note}</span>
              </span>
              <div className="stepper">
                <button
                  type="button"
                  className="stepper__button"
                  onClick={() => setTier(key, attendees[key] - 1)}
                  aria-label={`One fewer ${label}`}
                >
                  −
                </button>
                <input
                  className="stepper__value figure"
                  type="number"
                  min="0"
                  value={attendees[key]}
                  onChange={(event) => setTier(key, Number(event.target.value) || 0)}
                  aria-label={`${label} attendees`}
                />
                <button
                  type="button"
                  className="stepper__button"
                  onClick={() => setTier(key, attendees[key] + 1)}
                  aria-label={`One more ${label}`}
                >
                  +
                </button>
              </div>
            </div>
          ))}
        </div>
      </fieldset>

      <div className="field field--row">
        <label className="toggle">
          <input type="checkbox" checked={fields.is_recurring} onChange={set('is_recurring')} />
          <span>This repeats</span>
        </label>
        {fields.is_recurring && (
          <label className="toggle__select">
            <span className="visually-hidden">How often it repeats</span>
            <select
              className="field__input field__input--select"
              value={fields.recurrence_freq}
              onChange={set('recurrence_freq')}
            >
              {FREQUENCIES.map((freq) => (
                <option key={freq} value={freq}>
                  {freq.toLowerCase()}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}

      {!error && notice?.message && (
        <p className="notice notice--warning" role="alert">
          {notice.message}
        </p>
      )}

      <button className="submit" type="submit" disabled={pending || !fields.title.trim()}>
        {pending ? 'Analyzing…' : 'Analyze this meeting'}
      </button>
    </form>
  );
}

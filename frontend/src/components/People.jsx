import { useEffect, useRef, useState } from 'react';
import { forgetPerson, getDirectory, saveDirectory } from '../api/client.js';
import { ASSUMED_TIER, TIERS, tierLabel } from '../lib/tiers.js';
import { formatMoneyExact } from '../lib/format.js';

const UNASSIGNED = '';

/**
 * The people directory — who is in the room, and what their time is priced at.
 *
 * An emailed invite carries addresses and no roles, so every attendee ShouldBe has never
 * been told about is billed at the floor rate. That is a systematic understatement: a room
 * of directors reads exactly like a room of juniors. This screen is the fix, in three
 * parts that are deliberately in this order:
 *
 * 1. **Your role** — the one answer every user has, and the one that makes their own
 *    meetings price correctly.
 * 2. **Unidentified** — the worklist. Addresses seen in real meetings that nobody has
 *    placed, busiest first, because the person in eleven meetings is the one actually
 *    moving the ledger.
 * 3. **Placed** — everyone already known, editable.
 *
 * Saving is one request: placing a person and correcting the meetings that guessed at
 * them are the same act, so the panel reports what the ledger did in response.
 *
 * Rendered inside the Configuration form, so every control is `type="button"` — a nested
 * <form> is invalid HTML and would submit the rates form instead.
 */
export default function People({ onRepriced }) {
  const [directory, setDirectory] = useState(null);
  // Staged edits, keyed by address. Kept separate from `directory` so the panel always
  // shows what is saved next to what is about to change.
  const [staged, setStaged] = useState({});
  const [peopleScrollbar, setPeopleScrollbar] = useState({
    top: 0,
    height: 1,
    visible: false,
  });
  const [newEmail, setNewEmail] = useState('');
  const [newTier, setNewTier] = useState(ASSUMED_TIER);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const peopleListRef = useRef(null);

  const syncPeopleScrollbar = () => {
    const list = peopleListRef.current;
    if (!list) return;

    const maxScroll = Math.max(0, list.scrollHeight - list.clientHeight);
    const visible = maxScroll > 1;
    const height = visible ? Math.max(0.12, list.clientHeight / list.scrollHeight) : 1;
    const top = visible ? (list.scrollTop / maxScroll) * (1 - height) : 0;

    setPeopleScrollbar((prev) =>
      prev.visible === visible &&
      Math.abs(prev.height - height) < 0.001 &&
      Math.abs(prev.top - top) < 0.001
        ? prev
        : { visible, height, top },
    );
  };

  const load = async () => {
    try {
      setDirectory(await getDirectory());
    } catch (failure) {
      setError(failure.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const frame = window.requestAnimationFrame(syncPeopleScrollbar);
    window.addEventListener('resize', syncPeopleScrollbar);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', syncPeopleScrollbar);
    };
  });

  if (error && !directory) {
    return <p className="notice notice--error" role="alert">{error}</p>;
  }
  if (!directory) return null;

  const stage = (email, tier) => {
    setStatus(null);
    setStaged((prev) => ({ ...prev, [email]: tier }));
  };

  const tierOf = (email, saved) => staged[email] ?? saved ?? UNASSIGNED;

  const addPerson = () => {
    const email = newEmail.trim().toLowerCase();
    if (!email.includes('@')) {
      setError('Enter an email address to place someone.');
      return;
    }
    setError(null);
    stage(email, newTier);
    setNewEmail('');
  };

  const save = async () => {
    // Only rows that actually carry a tier. An unanswered "Unassigned" is not a claim
    // that someone is an IC — it is the absence of one, and saving it as a role would
    // turn a visible gap into an invisible wrong number.
    const people = Object.entries(staged)
      .filter(([, tier]) => tier !== UNASSIGNED)
      .map(([email, tier]) => ({ email, tier }));

    if (!people.length) {
      setError('Give someone a role first.');
      return;
    }

    setError(null);
    setStatus(null);
    setSaving(true);
    try {
      const saved = await saveDirectory(people);
      setDirectory(saved.directory);
      setStaged({});

      const { meetings_repriced: repriced, cost_delta: delta } = saved.repricing;
      setStatus(
        repriced
          ? `Placed ${people.length} · re-priced ${repriced} meeting${repriced === 1 ? '' : 's'} ` +
            `· ${Number(delta) >= 0 ? '+' : ''}${formatMoneyExact(delta)}`
          : `Placed ${people.length}. No meeting was priced on a guess about them.`,
      );
      // The dashboard figures just moved underneath whatever it is showing.
      if (repriced) onRepriced?.();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setSaving(false);
    }
  };

  const forget = async (person) => {
    setError(null);
    setStatus(null);
    try {
      await forgetPerson(person.id);
      await load();
      setStatus(`${person.email} removed. Meetings keep the cost they were priced at.`);
    } catch (failure) {
      setError(failure.message);
    }
  };

  const roleSelect = (email, saved, label) => (
    <select
      className="field__input field__input--select"
      value={tierOf(email, saved)}
      onChange={(event) => stage(email, event.target.value)}
      aria-label={label}
    >
      <option value={UNASSIGNED}>Unassigned</option>
      {TIERS.map(({ key, label: tierName, note }) => (
        <option key={key} value={key}>
          {tierName} — {note}
        </option>
      ))}
    </select>
  );

  const { me, self_email: selfEmail, people, unidentified } = directory;
  const pending = Object.entries(staged).filter(([, tier]) => tier !== UNASSIGNED);
  // Staged additions are people who are neither already placed nor on the worklist.
  const known = new Set(people.map((person) => person.email));
  const seen = new Set(unidentified.map((row) => row.email));
  const added = pending.filter(([email]) => !known.has(email) && !seen.has(email));
  const hasPeopleList = unidentified.length > 0 || people.length > 0 || added.length > 0;

  const scrollPeopleList = (event) => {
    const list = peopleListRef.current;
    if (!list) return;
    if (list.scrollHeight <= list.clientHeight) return;
    event.preventDefault();
    event.stopPropagation();
    list.scrollTop += event.deltaY;
    syncPeopleScrollbar();
  };

  const jumpPeopleList = (clientY, track) => {
    const list = peopleListRef.current;
    if (!list) return;

    const maxScroll = Math.max(0, list.scrollHeight - list.clientHeight);
    if (!maxScroll) return;

    const ratio = Math.min(1, Math.max(0, (clientY - track.top) / track.height));
    list.scrollTop = ratio * maxScroll;
    syncPeopleScrollbar();
  };

  const dragPeopleScrollbar = (event) => {
    const track = event.currentTarget.getBoundingClientRect();
    event.preventDefault();
    jumpPeopleList(event.clientY, track);

    const move = (moveEvent) => jumpPeopleList(moveEvent.clientY, track);
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
    };

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
  };

  return (
    <section className="panel panel--surface settings__people">
      <div className="panel__head">
        <div className="panel__title">
          <h2>People</h2>
          <p className="panel__hint">
            An invite carries addresses, not job titles. Anyone ShouldBe has not been told
            about is billed at {tierLabel(ASSUMED_TIER)} — the floor — so an unplaced room
            always costs less on paper than it did in the room.
          </p>
        </div>
        <p className="panel__count figure">
          {people.length} placed · {unidentified.length} unidentified
        </p>
      </div>

      <div className="people-row people-row--self">
        <div className="people-row__who">
          <span className="people-row__name">Your role</span>
          <span className="people-row__email">{selfEmail}</span>
        </div>
        {roleSelect(selfEmail, me?.tier, 'Your own role tier')}
        <span className="people-row__note">
          Applies wherever you are an attendee.
        </span>
      </div>

      {/* The empty directory is the state every account starts in, and it is exactly
          when `hasPeopleList` is false — so this is the other arm of that condition, not
          a check nested inside it. Without it the panel is a heading, one row and a blank
          form, which reads as broken rather than as new. */}
      {!hasPeopleList && (
        <p className="people-empty">
          Nobody placed yet. Set your own role above, add a colleague below, or invite
          ShouldBe to a meeting — every address on that invite shows up here waiting for a
          role, and the ledger re-prices itself once you give them one.
        </p>
      )}

      {hasPeopleList && (
        <div className="people-list">
          <div
            className="people-list__scrollbar"
            aria-hidden="true"
            onPointerDown={dragPeopleScrollbar}
          >
            <span
              className="people-list__thumb"
              style={{
                '--people-scroll-top': `${peopleScrollbar.top * 100}%`,
                '--people-scroll-height': `${peopleScrollbar.height * 100}%`,
                opacity: peopleScrollbar.visible ? 1 : 0.42,
              }}
            />
          </div>
          <div
            className="people-list__viewport"
            ref={peopleListRef}
            role="region"
            aria-label="People role lists"
            tabIndex={0}
            onWheel={scrollPeopleList}
            onScroll={syncPeopleScrollbar}
          >
            <div className="people-list__inner">
              {unidentified.length > 0 && (
                <>
                  <p className="people-heading">
                    <span className="badge badge--leak">Unidentified</span>
                    These addresses are in your ledger with no role, so their time is billed at the
                    floor. Naming them corrects every meeting that guessed.
                  </p>
                  <div className="people-rows">
                    {unidentified.map(({ email, meeting_count: count }) => (
                      <div className="people-row people-row--unknown" key={email}>
                        <div className="people-row__who">
                          <span className="people-row__email">{email}</span>
                          <span className="people-row__meta figure">
                            in {count} meeting{count === 1 ? '' : 's'}
                          </span>
                        </div>
                        {roleSelect(email, undefined, `Role tier for ${email}`)}
                        <span className="people-row__note">
                          billed {tierLabel(ASSUMED_TIER)}
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {(people.length > 0 || added.length > 0) && (
                <>
                  <p className="people-heading">
                    <span className="badge badge--defend">Placed</span>
                    Priced at their tier from here on. Changing a role does not re-price meetings
                    that already knew it — the ledger records what happened.
                  </p>
                  <div className="people-rows">
                    {people.map((person) => (
                      <div className="people-row" key={person.email}>
                        <div className="people-row__who">
                          <span className="people-row__email">{person.email}</span>
                          {person.is_self && <span className="people-row__meta">you</span>}
                          {person.display_name && (
                            <span className="people-row__meta">{person.display_name}</span>
                          )}
                        </div>
                        {roleSelect(person.email, person.tier, `Role tier for ${person.email}`)}
                        <button
                          type="button"
                          className="people-row__forget"
                          onClick={() => forget(person)}
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                    {added.map(([email, tier]) => (
                      <div className="people-row people-row--pending" key={email}>
                        <div className="people-row__who">
                          <span className="people-row__email">{email}</span>
                          <span className="people-row__meta">not saved yet</span>
                        </div>
                        {roleSelect(email, tier, `Role tier for ${email}`)}
                        <span className="people-row__note">pending</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="people-add">
        <label className="field">
          <span className="field__label">
            Add someone
            <span className="field__hint">before they ever appear on an invite</span>
          </span>
          <input
            className="field__input"
            type="email"
            autoComplete="off"
            spellCheck="false"
            placeholder="name@yourcompany.com"
            value={newEmail}
            onChange={(event) => setNewEmail(event.target.value)}
            aria-label="Email address to add"
          />
        </label>
        <label className="field">
          <span className="field__label">Role</span>
          <select
            className="field__input field__input--select"
            value={newTier}
            onChange={(event) => setNewTier(event.target.value)}
            aria-label="Role tier for the new person"
          >
            {TIERS.map(({ key, label, note }) => (
              <option key={key} value={key}>
                {label} — {note}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="reference-action" onClick={addPerson}>
          Add
        </button>
      </div>

      <p className="settings__privacy">
        <strong>A role, never a salary.</strong> Placing someone says which blended tier
        their time is priced at. The rate is shared by everyone in that tier, so no screen
        and no email in ShouldBe can show one person&apos;s number.
      </p>

      <div className="settings__actions">
        <button
          type="button"
          className="submit"
          disabled={saving || !pending.length}
          onClick={save}
        >
          {/* Counting only when there is something to count: interpolating an empty
              count left the label reading "Save  roles", with the gap still in it. */}
          {saving
            ? 'Saving…'
            : pending.length
              ? `Save ${pending.length} role${pending.length === 1 ? '' : 's'}`
              : 'Save roles'}
        </button>
        {status && <span className="settings__status" role="status">{status}</span>}
        {error && <span className="notice notice--error" role="alert">{error}</span>}
      </div>
    </section>
  );
}

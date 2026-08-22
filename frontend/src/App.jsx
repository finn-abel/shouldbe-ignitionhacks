import { useEffect, useState } from 'react';
import AnalysisResult from './components/AnalysisResult.jsx';
import AnalyzeForm from './components/AnalyzeForm.jsx';
import Dashboard from './components/Dashboard.jsx';
import Entry from './components/Entry.jsx';
import Settings from './components/Settings.jsx';
import { analyzeMeeting, enterAsGuest, getMe, logout } from './api/client.js';
import './styles/app.css';

const VIEWS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'analyze', label: 'Analyze a meeting' },
  { key: 'settings', label: 'Settings' },
];

/** Google redirects back with ?auth_error=... rather than stranding the browser. */
function readAuthError() {
  const reason = new URLSearchParams(window.location.search).get('auth_error');
  if (!reason) return null;
  window.history.replaceState({}, '', window.location.pathname);
  return reason === 'missing_profile'
    ? 'Google did not return a profile. Try again, or continue as guest.'
    : `Google sign-in failed (${reason}). Try again, or continue as guest.`;
}

export default function App() {
  const [user, setUser] = useState(null);
  const [checkingEntry, setCheckingEntry] = useState(true);
  const [entryError, setEntryError] = useState(readAuthError);
  const [view, setView] = useState('dashboard');
  const [analysis, setAnalysis] = useState(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  // Bumped after each analysis so the dashboard re-reads a ledger it knows has changed.
  const [ledgerVersion, setLedgerVersion] = useState(0);

  useEffect(() => {
    getMe()
      .then(setUser)
      .catch((failure) => {
        // 401 simply means nobody has entered yet; anything else is worth showing.
        if (failure.status !== 401) setEntryError(failure.message);
      })
      .finally(() => setCheckingEntry(false));
  }, []);

  const continueAsGuest = async () => {
    setPending(true);
    setEntryError(null);
    try {
      setUser(await enterAsGuest());
    } catch (failure) {
      setEntryError(failure.message);
    } finally {
      setPending(false);
    }
  };

  const signOut = async () => {
    await logout().catch(() => {});
    setUser(null);
    setAnalysis(null);
    setView('dashboard');
  };

  const analyze = async (meeting) => {
    setPending(true);
    setError(null);
    try {
      setAnalysis(await analyzeMeeting(meeting));
      setLedgerVersion((version) => version + 1);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setPending(false);
    }
  };

  if (checkingEntry) return null;

  if (!user) {
    return <Entry onGuest={continueAsGuest} pending={pending} error={entryError} />;
  }

  return (
    <>
      <header className="masthead">
        <p className="masthead__mark">ShouldBe</p>
        <p className="masthead__tagline">
          Meetings are the most expensive thing a company does without ever seeing a bill.
        </p>
        <nav className="masthead__nav" aria-label="Views">
          {VIEWS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className="tab"
              aria-current={view === key ? 'page' : undefined}
              onClick={() => setView(key)}
            >
              {label}
            </button>
          ))}
          <span className="whoami">
            {user.display_name}
            <button type="button" className="whoami__out" onClick={signOut}>
              sign out
            </button>
          </span>
        </nav>
      </header>

      <main className={view === 'analyze' ? 'workbench' : 'stage'}>
        {view === 'dashboard' && <Dashboard refreshKey={ledgerVersion} />}
        {view === 'analyze' && (
          <>
            <AnalyzeForm onAnalyzed={analyze} pending={pending} error={error} />
            <AnalysisResult analysis={analysis} />
          </>
        )}
        {view === 'settings' && (
          <Settings onSaved={() => setLedgerVersion((version) => version + 1)} />
        )}
      </main>

      <footer className="colophon">
        <span>Costed from blended role-tier rates — never individual salaries.</span>
      </footer>
    </>
  );
}

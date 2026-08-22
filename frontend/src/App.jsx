import { useEffect, useState } from 'react';
import AnalysisResult from './components/AnalysisResult.jsx';
import AnalyzeForm from './components/AnalyzeForm.jsx';
import Colophon from './components/Colophon.jsx';
import Dashboard from './components/Dashboard.jsx';
import Entry from './components/Entry.jsx';
import Settings from './components/Settings.jsx';
import { analyzeMeeting, enterAsGuest, getMe, logout } from './api/client.js';
import './styles/app.css';

const PRIMARY_VIEWS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'analyze', label: 'Analyze' },
];

const THEME_KEY = 'shouldbe-theme';
const PRIMARY_VIEW_INDEX = Object.fromEntries(PRIMARY_VIEWS.map((view, index) => [view.key, index]));

function readTheme() {
  return window.localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light';
}

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
  const [notice, setNotice] = useState(null);
  const [theme, setTheme] = useState(readTheme);
  // Bumped after each analysis so the dashboard re-reads a ledger it knows has changed.
  const [ledgerVersion, setLedgerVersion] = useState(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

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
    setNotice(null);
    setView('dashboard');
  };

  const chooseView = (nextView) => {
    setView(nextView);
  };

  const analyze = async (meeting) => {
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await analyzeMeeting(meeting);
      setAnalysis(result);
      setNotice(
        result.analysis_notice
          ? { message: result.analysis_notice, code: result.analysis_error_code }
          : null,
      );
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

  const primaryIndex = PRIMARY_VIEW_INDEX[view];
  const isPrimaryView = primaryIndex !== undefined;

  return (
    <>
      <header className="masthead">
        <button
          type="button"
          className="masthead__home"
          aria-label="Go to dashboard"
          onClick={() => chooseView('dashboard')}
        >
          <img className="masthead__logo" src="/shouldbe-logo.svg" alt="ShouldBe" />
        </button>
        <nav className="screen-overlay" aria-label="Primary views">
          {PRIMARY_VIEWS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className="screen-overlay__tab"
              aria-current={view === key ? 'page' : undefined}
              onClick={() => chooseView(key)}
            >
              {label}
            </button>
          ))}
        </nav>
        <nav className="masthead__nav" aria-label="Settings and account">
          <button
            type="button"
            className="tab tab--icon"
            aria-current={view === 'settings' ? 'page' : undefined}
            aria-label="Settings"
            onClick={() => chooseView('settings')}
          >
            <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z" />
              <path d="M19.4 15a1.8 1.8 0 0 0 .36 1.98l.04.04a2.16 2.16 0 0 1-3.05 3.05l-.04-.04a1.8 1.8 0 0 0-1.98-.36 1.8 1.8 0 0 0-1.1 1.65V21.5a2.16 2.16 0 0 1-4.32 0v-.18a1.8 1.8 0 0 0-1.1-1.65 1.8 1.8 0 0 0-1.98.36l-.04.04a2.16 2.16 0 0 1-3.05-3.05l.04-.04A1.8 1.8 0 0 0 4.6 15a1.8 1.8 0 0 0-1.65-1.1H2.8a2.16 2.16 0 0 1 0-4.32h.18A1.8 1.8 0 0 0 4.6 8.48a1.8 1.8 0 0 0-.36-1.98l-.04-.04a2.16 2.16 0 0 1 3.05-3.05l.04.04a1.8 1.8 0 0 0 1.98.36 1.8 1.8 0 0 0 1.1-1.65V2a2.16 2.16 0 0 1 4.32 0v.18a1.8 1.8 0 0 0 1.1 1.65 1.8 1.8 0 0 0 1.98-.36l.04-.04a2.16 2.16 0 0 1 3.05 3.05l-.04.04a1.8 1.8 0 0 0-.36 1.98 1.8 1.8 0 0 0 1.65 1.1h.18a2.16 2.16 0 0 1 0 4.32h-.18A1.8 1.8 0 0 0 19.4 15Z" />
            </svg>
          </button>
          <span className="whoami">
            <span className="whoami__bubble">
              <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M20 21a8 8 0 1 0-16 0" />
                <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z" />
              </svg>
              {user.display_name}
            </span>
            <button type="button" className="whoami__out" onClick={signOut} aria-label="Sign out">
              <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <path d="m16 17 5-5-5-5" />
                <path d="M21 12H9" />
              </svg>
            </button>
          </span>
        </nav>
      </header>

      <main className="page-shell">
        {isPrimaryView ? (
          <>
            <div className="screens" style={{ '--screen-index': primaryIndex }}>
              <div className="screens__track">
                <section
                  className="screens__page"
                  aria-hidden={view !== 'dashboard'}
                  inert={view !== 'dashboard' ? true : undefined}
                >
                  <div className="stage">
                    <Dashboard refreshKey={ledgerVersion} />
                  </div>
                </section>
                <section
                  className="screens__page"
                  aria-hidden={view !== 'analyze'}
                  inert={view !== 'analyze' ? true : undefined}
                >
                  <section className="analysis-page" aria-labelledby="analysis-title">
                    <header className="analysis-command">
                      <div>
                        <p className="eyebrow">Analyze a meeting</p>
                        <h1 id="analysis-title">Price the room before it reaches the calendar.</h1>
                        <p>
                          Enter the meeting shape once. ShouldBe prices the occurrence from your
                          blended federal rate basis, scores the necessity, and records the decision.
                        </p>
                      </div>
                      <dl className="analysis-rail" aria-label="Analysis workflow">
                        <div>
                          <dt>1</dt>
                          <dd>Cost</dd>
                        </div>
                        <div>
                          <dt>2</dt>
                          <dd>Score</dd>
                        </div>
                        <div>
                          <dt>3</dt>
                          <dd>Record</dd>
                        </div>
                      </dl>
                    </header>

                    <div className="workbench">
                      <AnalyzeForm
                        onAnalyzed={analyze}
                        pending={pending}
                        error={error}
                        notice={notice}
                      />
                      <AnalysisResult analysis={analysis} />
                    </div>
                  </section>
                </section>
              </div>
            </div>
          </>
        ) : (
          <div className="stage">
            <Settings
              theme={theme}
              onThemeChange={setTheme}
              onSaved={() => setLedgerVersion((version) => version + 1)}
            />
          </div>
        )}
      </main>

      <Colophon />
    </>
  );
}

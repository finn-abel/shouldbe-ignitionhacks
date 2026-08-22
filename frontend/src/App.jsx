import { useState } from 'react';
import AnalysisResult from './components/AnalysisResult.jsx';
import AnalyzeForm from './components/AnalyzeForm.jsx';
import Dashboard from './components/Dashboard.jsx';
import { analyzeMeeting } from './api/client.js';
import './styles/app.css';

const VIEWS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'analyze', label: 'Analyze a meeting' },
];

export default function App() {
  const [view, setView] = useState('dashboard');
  const [analysis, setAnalysis] = useState(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  // Bumped after each analysis so the dashboard re-reads a ledger it knows has changed.
  const [ledgerVersion, setLedgerVersion] = useState(0);

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
        </nav>
      </header>

      <main className={view === 'analyze' ? 'workbench' : 'stage'}>
        {view === 'dashboard' ? (
          <Dashboard refreshKey={ledgerVersion} />
        ) : (
          <>
            <AnalyzeForm onAnalyzed={analyze} pending={pending} error={error} />
            <AnalysisResult analysis={analysis} />
          </>
        )}
      </main>

      <footer className="colophon">
        <span>Costed from blended role-tier rates — never individual salaries.</span>
      </footer>
    </>
  );
}

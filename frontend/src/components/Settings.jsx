export default function Settings({ theme, onThemeChange }) {
  return (
    <section className="settings" aria-labelledby="settings-title">
      <header className="settings-command">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 id="settings-title">Set how ShouldBe feels in your browser.</h1>
          <p>
            Keep personal interface preferences here. Operational cost and routing controls
            now live in Configuration.
          </p>
        </div>
        <dl className="settings-summary settings-summary--compact" aria-label="Current settings summary">
          <div>
            <dt>Theme</dt>
            <dd>{theme === 'dark' ? 'Dark' : 'Light'}</dd>
          </div>
          <div>
            <dt>Configuration</dt>
            <dd>Separate</dd>
          </div>
          <div>
            <dt>Scope</dt>
            <dd>This browser</dd>
          </div>
        </dl>
      </header>

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
    </section>
  );
}

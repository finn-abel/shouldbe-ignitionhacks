const REPO_URL = 'https://github.com/finn-abel/shouldbe-ignitionhacks';

/**
 * The footer. Every claim here is checkable against the code that makes it true:
 *
 * - the OAuth scopes are `app/routes/auth.py:GOOGLE_SCOPES`
 * - the rubric weights are `app/services/scoring.py:RUBRIC_CATEGORIES`
 * - the rate basis is `app/services/costing.py:DEFAULT_TIER_RATES`
 *
 * Three of these panels used to read "…notes go here". Placeholder text under a heading
 * like "Security" is worse than no panel at all: it occupies the place a reader looks for
 * the answer and tells them nothing, on the one subject where a spend tool has to be
 * specific. If a claim here stops being true, delete the panel rather than soften it.
 */
export default function Colophon() {
  return (
    <footer className="colophon">
      <div className="colophon__inner">
        <div className="colophon__brand">
          <strong>ShouldBe</strong>
          <span>Costed from blended role-tier rates. Never individual salaries.</span>
        </div>
        <dl className="colophon__facts">
          <div>
            <dt>Access</dt>
            <dd>
              Google sign-in requests <code>openid email profile</code> and nothing else —
              ShouldBe cannot read your calendar. Meetings arrive only when you invite it
              to one, or type one in.
            </dd>
          </div>
          <div>
            <dt>Scoring rubric</dt>
            <dd>
              Decision pressure 35%, collaboration depth 25%, interaction value 20%,
              meeting fit 10%, business impact 10%. Live time carries the burden of proof:
              an invite that shows no reason to be live scores as an email.
            </dd>
          </div>
          <div>
            <dt>Rate basis</dt>
            <dd>
              Federal pay-scale midpoints — IT-02, IT-03, IT-04 and EX-03 / Director
              General — over a 1,950-hour year. Blended per tier, editable in settings,
              and applied to meetings priced from then on.
            </dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>
              Built for Ignition Hacks V.7.{' '}
              <a href={REPO_URL} target="_blank" rel="noreferrer">
                Read the code
              </a>{' '}
              — every figure above is a constant you can check.
            </dd>
          </div>
        </dl>
      </div>
    </footer>
  );
}

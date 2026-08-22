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
            <dt>Security</dt>
            <dd>Calendar permissions, data retention, and access notes go here.</dd>
          </div>
          <div>
            <dt>Scoring Rubric</dt>
            <dd>
              Decision pressure 35%, collaboration depth 25%, interaction value 20%,
              meeting fit 10%, business impact 10%.
            </dd>
          </div>
          <div>
            <dt>Methodology</dt>
            <dd>Rate assumptions, policy owner, and review cadence go here.</dd>
          </div>
          <div>
            <dt>Contact</dt>
            <dd>Support owner, team alias, or rollout channel goes here.</dd>
          </div>
        </dl>
      </div>
    </footer>
  );
}

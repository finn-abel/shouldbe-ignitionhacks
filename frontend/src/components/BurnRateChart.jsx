import { useMemo, useState } from 'react';
import { formatMoney, formatMoneyExact } from '../lib/format.js';

const VIEW = { w: 720, h: 200, padX: 8, padTop: 22, padBottom: 26 };

const dayLabel = (iso) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });

/**
 * Meeting spend over time — one series, so no legend: the heading names it.
 * Drawn as inline SVG rather than pulled from a chart library, to hold the bundle
 * budget and to let the marks wear the same tokens as the rest of the page.
 */
export default function BurnRateChart({ buckets, bucket }) {
  const [hovered, setHovered] = useState(null);

  const geometry = useMemo(() => {
    if (!buckets?.length) return null;

    const values = buckets.map((b) => Number(b.amount));
    const peak = Math.max(...values, 1);
    const { w, h, padX, padTop, padBottom } = VIEW;
    const plot = h - padTop - padBottom;
    const step = buckets.length > 1 ? (w - padX * 2) / (buckets.length - 1) : 0;

    const points = buckets.map((b, i) => ({
      ...b,
      value: values[i],
      x: buckets.length > 1 ? padX + i * step : w / 2,
      y: padTop + plot - (values[i] / peak) * plot,
    }));

    const peakPoint = points[values.indexOf(Math.max(...values))];
    return { points, peak, peakPoint, baseline: padTop + plot, step };
  }, [buckets]);

  if (!geometry) {
    return (
      <p className="chart__empty">
        No spend recorded yet. Analyze a meeting and it lands here.
      </p>
    );
  }

  const { points, peak, peakPoint, baseline } = geometry;
  const line = points.map((p) => `${p.x},${p.y}`).join(' ');
  const area = `${points[0].x},${baseline} ${line} ${points.at(-1).x},${baseline}`;
  const active = hovered === null ? null : points[hovered];

  return (
    <figure className="chart">
      <svg
        className="chart__svg"
        viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Meeting spend by ${bucket}. Peak ${formatMoney(peak)} on ${dayLabel(peakPoint.period)}.`}
        onMouseLeave={() => setHovered(null)}
      >
        {/* Recessive solid hairlines — never dashed. */}
        {[0, 0.5, 1].map((fraction) => {
          const y = VIEW.padTop + (baseline - VIEW.padTop) * fraction;
          return <line key={fraction} className="chart__grid" x1="0" x2={VIEW.w} y1={y} y2={y} />;
        })}

        <polygon className="chart__area" points={area} />
        <polyline className="chart__line" points={line} />

        {active && (
          <line className="chart__crosshair" x1={active.x} x2={active.x} y1={VIEW.padTop} y2={baseline} />
        )}

        {points.map((p, i) => (
          <circle
            key={p.period}
            className={`chart__dot ${i === hovered ? 'is-active' : ''}`}
            cx={p.x}
            cy={p.y}
            r={i === hovered ? 5 : 3}
          />
        ))}

        {/* Generous invisible hit targets, wider than the marks themselves. */}
        {points.map((p, i) => (
          <rect
            key={`hit-${p.period}`}
            className="chart__hit"
            x={p.x - (geometry.step || VIEW.w) / 2}
            y="0"
            width={geometry.step || VIEW.w}
            height={VIEW.h}
            onMouseEnter={() => setHovered(i)}
          />
        ))}
      </svg>

      <div className="chart__scale">
        <span className="figure">{formatMoney(peak)}</span>
        <span className="figure">{dayLabel(points[0].period)}</span>
        <span className="figure">{dayLabel(points.at(-1).period)}</span>
      </div>

      {active && (
        <p className="chart__tooltip" role="status">
          <span>{dayLabel(active.period)}</span>
          <strong className="figure">{formatMoneyExact(active.amount)}</strong>
        </p>
      )}

      {/* The chart's data, readable by anyone who cannot read the chart. */}
      <figcaption className="visually-hidden">
        <table>
          <caption>Meeting spend per {bucket}</caption>
          <tbody>
            {points.map((p) => (
              <tr key={p.period}>
                <th scope="row">{dayLabel(p.period)}</th>
                <td>{formatMoneyExact(p.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </figcaption>
    </figure>
  );
}

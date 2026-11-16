import { useState } from "react";

// A plain column chart for one series of counts.
// items: [{ label, value, tip }]   tip is the tooltip's first line.
export default function ColumnChart({ items, unit, tickEvery = 1, height = 180, summary }) {
  const [hover, setHover] = useState(null);
  const [asTable, setAsTable] = useState(false);

  const width = 640;
  const pad = { top: 12, right: 8, bottom: 24, left: 30 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const max = Math.max(1, ...items.map((item) => item.value));
  // Whole-number steps: these are counts, so "1.5 violations" must never appear.
  const step = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].find((s) => max / s <= 4) || 2000;
  const top = Math.ceil(max / step) * step;
  const ticks = [];
  for (let value = 0; value <= top; value += step) ticks.push(value);

  const slot = plotW / items.length;
  const barW = Math.min(24, Math.max(3, slot - 2)); // capped, with a gap between neighbours
  const y = (value) => pad.top + plotH - (value / top) * plotH;
  const empty = items.every((item) => item.value === 0);

  return (
    <div className="chart">
      <div className="chart-tools">
        <button className="link small" onClick={() => setAsTable(!asTable)}>
          {asTable ? "Show chart" : "Show as table"}
        </button>
      </div>

      {asTable ? (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>{summary}</th>
                <th className="num">{unit}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.label}>
                  <td>{item.tip}</td>
                  <td className="num">{item.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="chart-plot">
          <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${summary}: column chart of ${unit}`}>
            {ticks.map((value) => (
              <g key={value}>
                <line className="grid" x1={pad.left} x2={width - pad.right} y1={y(value)} y2={y(value)} />
                <text className="tick" x={pad.left - 6} y={y(value)} textAnchor="end" dominantBaseline="middle">
                  {value}
                </text>
              </g>
            ))}
            {items.map((item, index) => {
              const x = pad.left + slot * index + (slot - barW) / 2;
              const barH = (item.value / top) * plotH;
              const r = Math.min(4, barW / 2, barH);
              const base = pad.top + plotH;
              return (
                <g key={item.label}>
                  {item.value > 0 && (
                    // Rounded at the data end, square on the baseline.
                    <path
                      className={`bar ${hover === index ? "on" : ""}`}
                      d={`M${x},${base} V${base - barH + r} Q${x},${base - barH} ${x + r},${base - barH}
                          H${x + barW - r} Q${x + barW},${base - barH} ${x + barW},${base - barH + r} V${base} Z`}
                    />
                  )}
                  {index % tickEvery === 0 && (
                    <text className="tick" x={x + barW / 2} y={height - 7} textAnchor="middle">
                      {item.label}
                    </text>
                  )}
                  {/* The whole column slot is the hover target, not just the bar. */}
                  <rect
                    className="hit"
                    x={pad.left + slot * index}
                    y={pad.top}
                    width={slot}
                    height={plotH}
                    tabIndex={0}
                    aria-label={`${item.tip}: ${item.value} ${unit}`}
                    onMouseEnter={() => setHover(index)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(index)}
                    onBlur={() => setHover(null)}
                  />
                </g>
              );
            })}
          </svg>
          {hover !== null && (
            <div
              className="tooltip"
              style={{
                left: `${((pad.left + slot * (hover + 0.5)) / width) * 100}%`,
                top: `${(y(items[hover].value) / height) * 100}%`,
              }}
            >
              <div className="muted small">{items[hover].tip}</div>
              <strong>{items[hover].value}</strong> {unit}
            </div>
          )}
          {empty && <div className="chart-empty muted">Nothing recorded in this period.</div>}
        </div>
      )}
    </div>
  );
}

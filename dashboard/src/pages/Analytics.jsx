import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { duration, when } from "../format.js";
import ColumnChart from "../components/ColumnChart.jsx";
import HotspotMap from "../components/HotspotMap.jsx";

const RANGES = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
];

const hourName = (hour) => {
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h} ${hour < 12 ? "am" : "pm"}`;
};
const percent = (share) => (share == null ? "–" : `${Math.round(share * 100)}%`);

export default function Analytics({ onSessionEnded }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    setData(null);
    api
      .analytics(days)
      .then((result) => {
        if (current) {
          setData(result);
          setError("");
        }
      })
      .catch((problem) => {
        if (!current) return;
        if (problem.status === 401) onSessionEnded();
        else setError(problem.message);
      });
    return () => {
      current = false;
    };
  }, [days, onSessionEnded]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Analytics</h1>
          <p className="page-sub">Where and when wrong parking happens, and which plates keep coming back.</p>
        </div>
        <div className="segmented" role="group" aria-label="Period">
          {RANGES.map((range) => (
            <button
              key={range.days}
              className={days === range.days ? "active" : ""}
              aria-pressed={days === range.days}
              onClick={() => setDays(range.days)}
            >
              {range.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!data && !error && <div className="center muted">Loading…</div>}

      {data && (
        <>
          <div className="tiles">
            <Tile value={data.summary.violations} label="Violations" note="Rejected alerts not counted" />
            <Tile value={data.summary.pending} label="Waiting for review" />
            <Tile value={data.summary.high_impact} label="High traffic impact" />
            <Tile
              value={percent(data.summary.rejected_share)}
              label="Alerts rejected"
              note={
                data.summary.rejected_share == null
                  ? "None reviewed yet"
                  : `${data.summary.rejected} of ${data.summary.rejected + data.summary.confirmed} reviewed`
              }
            />
            <Tile value={percent(data.summary.plates_read_share)} label="Plates read" />
            <Tile
              value={data.summary.median_parked_seconds == null ? "–" : duration(data.summary.median_parked_seconds)}
              label="Typical time parked"
              note="Median, vehicles that have left"
            />
          </div>

          <div className="card">
            <h2>Hotspots</h2>
            <div className="hotspots">
              <HotspotMap spots={data.hotspots} />
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Camera</th>
                      <th className="num">Violations</th>
                      <th className="num">High impact</th>
                      <th>Busiest hour</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.hotspots.map((spot) => (
                      <tr key={spot.camera_name}>
                        <td>{spot.camera_name}</td>
                        <td className="num">{spot.violations}</td>
                        <td className="num">{spot.high_impact}</td>
                        <td>{spot.busiest_hour == null ? "–" : hourName(spot.busiest_hour)}</td>
                      </tr>
                    ))}
                    {data.hotspots.length === 0 && (
                      <tr>
                        <td colSpan={4} className="muted">
                          No violations in this period.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="two">
            <div className="card">
              <h2>Violations by hour of day</h2>
              <ColumnChart
                summary="Hour of day"
                unit="violations"
                tickEvery={3}
                items={data.by_hour.map((value, hour) => ({
                  label: hourName(hour),
                  tip: `${hourName(hour)} to ${hourName((hour + 1) % 24)}`,
                  value,
                }))}
              />
            </div>
            <div className="card">
              <h2>Violations per day, last {data.by_day.length} days</h2>
              <ColumnChart
                summary="Day"
                unit="violations"
                tickEvery={Math.ceil(data.by_day.length / 7)}
                items={data.by_day.map((day) => {
                  const date = new Date(`${day.date}T12:00:00`);
                  return {
                    label: date.toLocaleDateString(undefined, { day: "numeric", month: "short" }),
                    tip: date.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }),
                    value: day.count,
                  };
                })}
              />
            </div>
          </div>

          <div className="two">
            <div className="card">
              <h2>Repeat offenders</h2>
              <p className="muted small">
                Plates caught more than once. A plate read automatically can be a misread, so check
                the photos before treating two alerts as the same vehicle.
              </p>
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Plate</th>
                      <th className="num">Times</th>
                      <th>Where</th>
                      <th>Last seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.repeat_offenders.map((offender) => (
                      <tr key={offender.plate_text}>
                        <td>
                          <Link to={`/violations/${offender.last_id}`} className="plate-inline">
                            {offender.plate_text}
                          </Link>
                          {!offender.officer_checked && <div className="muted small">Not checked by an officer</div>}
                        </td>
                        <td className="num">{offender.violations}</td>
                        <td>{offender.cameras.join(", ")}</td>
                        <td>{when(offender.last_seen)}</td>
                      </tr>
                    ))}
                    {data.repeat_offenders.length === 0 && (
                      <tr>
                        <td colSpan={4} className="muted">
                          No plate has been caught twice in this period.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card">
              <h2>Why alerts were rejected</h2>
              <p className="muted small">
                Where the system gets it wrong. Counts every alert that is rejected now, in any period.
              </p>
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Reason</th>
                      <th className="num">Alerts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.reject_reasons.map((row) => (
                      <tr key={row.reason}>
                        <td>{row.reason}</td>
                        <td className="num">{row.count}</td>
                      </tr>
                    ))}
                    {data.reject_reasons.length === 0 && (
                      <tr>
                        <td colSpan={2} className="muted">
                          No alerts have been rejected.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function Tile({ value, label, note }) {
  return (
    <div className="card tile">
      <div className="tile-value">{value}</div>
      <div className="tile-label">{label}</div>
      {note && <div className="muted small">{note}</div>}
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { ago, duration, vehicleName, when } from "../format.js";
import { useLiveEvents } from "../useLiveEvents.js";
import StatusBadge from "../components/StatusBadge.jsx";
import ImpactBadge from "../components/ImpactBadge.jsx";
import Icon from "../components/Icon.jsx";

const TILES = [
  { tab: "Pending", label: "Waiting for review", icon: "clock", tone: "amber" },
  { tab: "Confirmed", label: "Confirmed, action due", icon: "flag", tone: "red" },
  { tab: "Action Taken", label: "Action taken", icon: "check", tone: "green" },
  { tab: "All", label: "All alerts", icon: "inbox", tone: "" },
];

const searchable = (v) =>
  [v.code, v.plate_text, v.camera_name, v.zone_name, v.vehicle_class].filter(Boolean).join(" ").toLowerCase();

const TABS = ["Pending", "Confirmed", "Action Taken", "Rejected", "All"];
const EMPTY = {
  Pending: "No alerts waiting. New ones appear here by themselves.",
  Confirmed: "Nothing confirmed and waiting for action.",
  "Action Taken": "No completed violations yet.",
  Rejected: "No rejected alerts.",
  All: "No violations recorded yet.",
};

export default function Queue({ onSessionEnded, onWaiting }) {
  const [tab, setTab] = useState("Pending");
  const [items, setItems] = useState(null);
  const [counts, setCounts] = useState({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(null);
  const [query, setQuery] = useState("");
  const [impact, setImpact] = useState("");
  const [now, setNow] = useState(Date.now());
  const tabRef = useRef(tab);
  tabRef.current = tab;

  const load = useCallback(
    async (which) => {
      try {
        // The waiting list puts whatever is holding up traffic most at the top.
        const data = await api.violations(
          which === "All" ? "" : which,
          which === "Pending" ? "impact" : "newest",
        );
        // Ignore a reply for a tab the officer has already left.
        if (which !== tabRef.current) return;
        setItems(data.items);
        setCounts(data.counts);
        onWaiting?.(data.counts.Pending ?? 0);
        setError("");
      } catch (problem) {
        if (problem.status === 401) onSessionEnded();
        else setError(problem.message);
      }
    },
    [onSessionEnded, onWaiting],
  );

  useEffect(() => {
    setItems(null);
    load(tab);
  }, [tab, load]);

  // Keeps "5 min ago" moving without reloading anything.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(null), 8000);
    return () => clearTimeout(timer);
  }, [notice]);

  const live = useLiveEvents((kind, data) => {
    if (kind === "violation_created") setNotice(data);
    load(tabRef.current);
  });

  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
  const countFor = (name) => (name === "All" ? total : counts[name] ?? 0);

  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const shown = items?.filter(
    (v) =>
      (!impact || v.impact?.level === impact) &&
      words.every((word) => searchable(v).includes(word)),
  );
  const filtering = words.length > 0 || impact !== "";

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Alerts</h1>
          <p className="page-sub">Vehicles parked too long in a no-parking zone, waiting for an officer.</p>
        </div>
        <span className={`live ${live ? "on" : "off"}`} title="Whether new alerts arrive by themselves">
          <span className="dot" />
          {live ? "Live" : "Reconnecting…"}
        </span>
      </div>

      <div className="tiles">
        {TILES.map((tile) => (
          <button
            key={tile.tab}
            className="card tile"
            style={{ font: "inherit", color: "inherit", textAlign: "left", cursor: "pointer" }}
            onClick={() => setTab(tile.tab)}
            aria-label={`${tile.label}: ${countFor(tile.tab)}. Show these.`}
          >
            <span className="tile-top">
              <span className="tile-label">{tile.label}</span>
              <span className={`tile-icon ${tile.tone}`}>
                <Icon name={tile.icon} />
              </span>
            </span>
            <span className="tile-value">{countFor(tile.tab)}</span>
          </button>
        ))}
      </div>

      <div className="tabs" role="tablist">
        {TABS.map((name) => (
          <button
            key={name}
            role="tab"
            aria-selected={tab === name}
            className={`tab ${tab === name ? "active" : ""}`}
            onClick={() => setTab(name)}
          >
            {name}
            <span className={`count ${name === "Pending" && countFor(name) ? "hot" : ""}`}>
              {countFor(name)}
            </span>
          </button>
        ))}
      </div>

      <div className="toolbar">
        <div className="search">
          <Icon name="search" />
          <label htmlFor="search" className="sr-only">
            Search alerts
          </label>
          <input
            id="search"
            type="search"
            placeholder="Search plate, code, camera or zone"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <label htmlFor="impact" className="sr-only">
          Traffic impact
        </label>
        <select id="impact" value={impact} onChange={(event) => setImpact(event.target.value)}>
          <option value="">Any traffic impact</option>
          <option value="High">High impact</option>
          <option value="Medium">Medium impact</option>
          <option value="Low">Low impact</option>
        </select>
        {filtering && shown && (
          <span className="muted small">
            {shown.length} of {items.length} shown{" "}
            <button className="link" onClick={() => { setQuery(""); setImpact(""); }}>
              Clear
            </button>
          </span>
        )}
      </div>

      {notice && (
        <div className="toast" role="status">
          <Icon name="alerts" />
          <span>
            New alert <strong className="code">{notice.code}</strong>
          </span>
          {notice.id && <Link to={`/violations/${notice.id}`}>Open</Link>}
        </div>
      )}
      {error && (
        <div className="alert error" role="alert">
          {error}{" "}
          <button className="link" onClick={() => load(tab)}>
            Try again
          </button>
        </div>
      )}

      {items === null && !error && (
        <div className="list" aria-label="Loading">
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      )}
      {items && items.length === 0 && (
        <div className="card empty muted">
          <Icon name="inbox" className="empty-icon" />
          {EMPTY[tab]}
        </div>
      )}
      {items && items.length > 0 && shown.length === 0 && (
        <div className="card empty muted">
          <Icon name="search" className="empty-icon" />
          Nothing here matches your search.
        </div>
      )}

      {tab === "Pending" && shown && shown.length > 0 && shown.some((v) => v.impact) && (
        <p className="muted small sort-note">Worst traffic impact first.</p>
      )}

      {shown && shown.length > 0 && (
        <ul className="list">
          {shown.map((v) => (
            <li key={v.id}>
              <Link
                to={`/violations/${v.id}`}
                className={`row card ${v.impact ? `impact-${v.impact.level.toLowerCase()}` : ""}`}
              >
                {v.photo_url ? (
                  <img className="thumb" src={v.photo_url} alt="" loading="lazy" />
                ) : (
                  <div className="thumb none">No photo</div>
                )}
                <div className="row-main">
                  <div className="row-title">
                    {vehicleName(v.vehicle_class)}
                    <span className="muted"> · {v.camera_name}</span>
                  </div>
                  <div className="muted small">
                    {v.zone_name ? `${v.zone_name} · ` : ""}
                    Plate: {v.plate_text ? <strong className="plate-inline">{v.plate_text}</strong> : "not readable"}
                  </div>
                  <div className="muted small">
                    {v.ended_at
                      ? `Left after ${duration(v.duration_seconds)}`
                      : `Parked ${duration(v.parked_seconds)} when alerted · still there`}
                  </div>
                </div>
                <div className="row-side">
                  <StatusBadge status={v.status} />
                  <ImpactBadge impact={v.impact} />
                  <div className="small" title={when(v.started_at)}>
                    {ago(v.started_at, now)}
                  </div>
                  <div className="muted small code">{v.code}</div>
                </div>
                <Icon name="chevron" className="icon chevron" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

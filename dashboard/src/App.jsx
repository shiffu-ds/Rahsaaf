import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api.js";
import { currentTheme, saveTheme } from "./theme.js";
import Icon from "./components/Icon.jsx";
import Login from "./pages/Login.jsx";
import Queue from "./pages/Queue.jsx";
import Violation from "./pages/Violation.jsx";
import Analytics from "./pages/Analytics.jsx";
import Account from "./pages/Account.jsx";

const initials = (name) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");

export default function App() {
  // undefined = still checking, null = logged out, object = logged in.
  const [officer, setOfficer] = useState(undefined);
  const navigate = useNavigate();
  const location = useLocation();
  const [theme, setTheme] = useState(currentTheme);
  // How many alerts are waiting; shown beside "Alerts" on every page.
  const [waiting, setWaiting] = useState(0);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    saveTheme(next);
    setTheme(next);
  };

  useEffect(() => {
    if (!officer) return;
    api
      .violations("Pending")
      .then((data) => setWaiting(data.counts.Pending ?? 0))
      .catch(() => {});
  }, [officer, location.pathname]);

  useEffect(() => {
    document.title = waiting ? `(${waiting}) RahSaaf` : "RahSaaf";
  }, [waiting]);

  useEffect(() => {
    api.me().then(setOfficer).catch(() => setOfficer(null));
  }, []);

  // Any page can call this when the server says the session has ended.
  const onSessionEnded = useCallback(() => setOfficer(null), []);

  const logout = async () => {
    await api.logout().catch(() => {});
    setOfficer(null);
    navigate("/login");
  };

  if (officer === undefined) return <div className="center muted">Loading…</div>;

  if (officer === null) {
    return (
      <Routes>
        <Route path="/login" element={<Login onLogin={setOfficer} />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true">P</span>
          <span>
            RahSaaf
            <small>Parking enforcement</small>
          </span>
        </Link>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end title="Alerts">
            <Icon name="alerts" />
            <span className="label">Alerts</span>
            {waiting > 0 && (
              <span className="nav-count" aria-label={`${waiting} waiting`}>
                {waiting}
              </span>
            )}
          </NavLink>
          <NavLink to="/analytics" title="Analytics">
            <Icon name="chart" />
            <span className="label">Analytics</span>
          </NavLink>
          <NavLink to="/account" title="Account">
            <Icon name="user" />
            <span className="label">Account</span>
          </NavLink>
        </nav>
        <div className="side-foot">
          <button className="side-button" onClick={toggleTheme} title="Switch between light and dark">
            <Icon name={theme === "dark" ? "sun" : "moon"} />
            <span className="label">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
          </button>
          <button className="side-button" onClick={logout} title="Log out">
            <Icon name="logout" />
            <span className="label">Log out</span>
          </button>
          <div className="user">
            <span className="avatar" aria-hidden="true">{initials(officer.name)}</span>
            <div style={{ minWidth: 0 }}>
              <div className="user-name">{officer.name}</div>
              <div className="user-role">{officer.role === "admin" ? "Admin" : "Officer"}</div>
            </div>
          </div>
        </div>
      </aside>
      <main className="page">
        <Routes>
          <Route path="/" element={<Queue onSessionEnded={onSessionEnded} onWaiting={setWaiting} />} />
          <Route
            path="/violations/:id"
            element={<Violation onSessionEnded={onSessionEnded} />}
          />
          <Route path="/analytics" element={<Analytics onSessionEnded={onSessionEnded} />} />
          <Route
            path="/account"
            element={<Account officer={officer} onSessionEnded={onSessionEnded} />}
          />
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<div className="center muted">Page not found.</div>} />
        </Routes>
      </main>
    </div>
  );
}

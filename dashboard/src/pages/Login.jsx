import { useState } from "react";
import { api } from "../api.js";
import Icon from "../components/Icon.jsx";

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await api.login(username, password));
    } catch (problem) {
      setError(problem.message);
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <section className="login-hero" aria-hidden="true">
        <div className="brand">
          <span className="brand-mark">P</span>
          RahSaaf
        </div>
        <div>
          <h1>Clear roads start with clear evidence.</h1>
          <p>Wrongly parked vehicles are spotted by camera and sent to an officer with a photo, a clip and the location.</p>
          <ul className="login-points">
            <li><Icon name="alerts" /> Alerts arrive live, worst traffic impact first</li>
            <li><Icon name="shield" /> Every decision is made by an officer and recorded</li>
            <li><Icon name="chart" /> Hotspots and repeat offenders over time</li>
          </ul>
        </div>
        <div className="login-foot">The system gives evidence. It issues no fines.</div>
      </section>
      <div className="login-side">
      <form className="card login" onSubmit={submit}>
        <h1>Sign in</h1>
        <p className="muted login-sub">Use the login your admin gave you.</p>

        <label htmlFor="username">Username</label>
        <input
          id="username"
          autoComplete="username"
          autoFocus
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          required
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />

        {error && (
          <div className="alert error" role="alert">
            {error}
          </div>
        )}

        <button className="button primary wide" disabled={busy}>
          {busy ? "Logging in…" : "Log in"}
        </button>
      </form>
      </div>
    </div>
  );
}

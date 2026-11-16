import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { when } from "../format.js";

const MIN_PASSWORD = 10;

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    if (next !== again) {
      setMessage({ kind: "error", text: "The two new passwords do not match." });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await api.changePassword(current, next);
      setMessage({ kind: "info", text: "Password changed. Other devices using this login were logged out." });
      setCurrent("");
      setNext("");
      setAgain("");
    } catch (problem) {
      setMessage({ kind: "error", text: problem.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card narrow" onSubmit={submit}>
      <h2>Change your password</h2>
      <label htmlFor="current">Current password</label>
      <input id="current" type="password" autoComplete="current-password" value={current}
        onChange={(event) => setCurrent(event.target.value)} required />
      <label htmlFor="next">New password (at least {MIN_PASSWORD} characters)</label>
      <input id="next" type="password" autoComplete="new-password" minLength={MIN_PASSWORD} value={next}
        onChange={(event) => setNext(event.target.value)} required />
      <label htmlFor="again">New password again</label>
      <input id="again" type="password" autoComplete="new-password" minLength={MIN_PASSWORD} value={again}
        onChange={(event) => setAgain(event.target.value)} required />
      {message && (
        <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>
          {message.text}
        </div>
      )}
      <div className="actions">
        <button className="button primary" disabled={busy}>{busy ? "Saving…" : "Change password"}</button>
      </div>
    </form>
  );
}

function Logins({ me, onSessionEnded }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ name: "", username: "", password: "", role: "officer" });
  const [resetFor, setResetFor] = useState(null);
  const [resetPassword, setResetPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    async (call) => {
      setBusy(true);
      setError("");
      try {
        setData(await call());
        return true;
      } catch (problem) {
        if (problem.status === 401) onSessionEnded();
        else setError(problem.message);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [onSessionEnded],
  );

  useEffect(() => {
    run(() => api.officers());
  }, [run]);

  const add = async (event) => {
    event.preventDefault();
    if (await run(() => api.addOfficer(form))) {
      setForm({ name: "", username: "", password: "", role: "officer" });
    }
  };

  const reset = async (event) => {
    event.preventDefault();
    if (await run(() => api.resetOfficerPassword(resetFor.id, resetPassword))) {
      setResetFor(null);
      setResetPassword("");
    }
  };

  const field = (key) => ({
    value: form[key],
    onChange: (event) => setForm({ ...form, [key]: event.target.value }),
  });

  return (
    <>
      {error && <div className="alert error" role="alert">{error}</div>}

      <section className="card">
        <h2>Logins</h2>
        {!data ? (
          <p className="muted">Loading…</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Name</th><th>Username</th><th>Role</th><th>State</th><th><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody>
                {data.officers.map((officer) => (
                  <tr key={officer.id} className={officer.active ? "" : "off"}>
                    <td>{officer.name}{officer.id === me.id && <span className="muted"> (you)</span>}</td>
                    <td className="code">{officer.username}</td>
                    <td>{officer.role === "admin" ? "Admin" : "Officer"}</td>
                    <td>{officer.active ? "Active" : "Disabled"}</td>
                    <td className="table-actions">
                      {officer.id !== me.id && (
                        <>
                          <button className="link" disabled={busy}
                            onClick={() => { setResetFor(officer); setResetPassword(""); }}>
                            Reset password
                          </button>
                          <button className="link" disabled={busy}
                            onClick={() => run(() => api.setOfficerActive(officer.id, !officer.active))}>
                            {officer.active ? "Disable" : "Enable"}
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small">
          A disabled login is logged out at once and cannot log in. Logins are never deleted, so
          the history of decisions keeps its names.
        </p>

        {resetFor && (
          <form className="narrow" onSubmit={reset}>
            <label htmlFor="reset">New password for {resetFor.name} (at least {MIN_PASSWORD} characters)</label>
            <input id="reset" type="password" autoComplete="new-password" minLength={MIN_PASSWORD}
              value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} required autoFocus />
            <div className="actions">
              <button className="button primary" disabled={busy}>Set password</button>
              <button type="button" className="button ghost" onClick={() => setResetFor(null)}>Cancel</button>
            </div>
          </form>
        )}
      </section>

      <form className="card narrow" onSubmit={add}>
        <h2>Add a login</h2>
        <label htmlFor="name">Full name</label>
        <input id="name" maxLength={80} required {...field("name")} />
        <label htmlFor="new-username">Username (3–32 letters, digits, dot, dash or underscore)</label>
        <input id="new-username" autoComplete="off" pattern="[A-Za-z0-9_.\-]{3,32}" required {...field("username")} />
        <label htmlFor="new-password">Password (at least {MIN_PASSWORD} characters)</label>
        <input id="new-password" type="password" autoComplete="new-password" minLength={MIN_PASSWORD} required {...field("password")} />
        <label htmlFor="role">Role</label>
        <select id="role" {...field("role")}>
          <option value="officer">Officer: reviews alerts</option>
          <option value="admin">Admin: also manages logins</option>
        </select>
        <div className="actions">
          <button className="button primary" disabled={busy}>Add login</button>
        </div>
      </form>

      {data && data.log.length > 0 && (
        <section className="card">
          <h2>Recent changes to logins</h2>
          <ul className="plain">
            {data.log.map((entry, index) => (
              <li key={index}>
                <span className="muted small">{when(entry.created_at)}</span>{" "}
                {entry.actor === entry.target
                  ? `${entry.actor} ${entry.action}`
                  : `${entry.actor}: ${entry.target} ${entry.action}`}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

export default function Account({ officer, onSessionEnded }) {
  return (
    <div className="stack">
      <div className="page-head">
        <h1>Account</h1>
        <span className="muted">
          {officer.name} · {officer.role === "admin" ? "Admin" : "Officer"}
        </span>
      </div>
      <ChangePassword />
      {officer.role === "admin" && <Logins me={officer} onSessionEnded={onSessionEnded} />}
    </div>
  );
}

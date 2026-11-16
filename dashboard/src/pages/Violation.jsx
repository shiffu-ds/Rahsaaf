import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";
import Icon from "../components/Icon.jsx";
import { duration, mapLink, vehicleName, when } from "../format.js";
import { useLiveEvents } from "../useLiveEvents.js";
import StatusBadge from "../components/StatusBadge.jsx";
import ImpactBadge from "../components/ImpactBadge.jsx";

const BUTTON = {
  Confirmed: { label: "Confirm violation", style: "primary" },
  "Action Taken": { label: "Mark action taken", style: "primary" },
  Rejected: { label: "Reject…", style: "danger" },
  Reopened: { label: "Reopen", style: "ghost" },
};

export default function Violation({ onSessionEnded }) {
  const { id } = useParams();
  const [violation, setViolation] = useState(null);
  const [reasons, setReasons] = useState([]);
  const [error, setError] = useState("");
  const [missing, setMissing] = useState(false);

  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  const [editingPlate, setEditingPlate] = useState(false);
  const [plateInput, setPlateInput] = useState("");
  const [plateError, setPlateError] = useState("");

  const fail = useCallback(
    (problem, show) => {
      if (problem.status === 401) onSessionEnded();
      else if (problem.status === 404) setMissing(true);
      else show(problem.message);
    },
    [onSessionEnded],
  );

  const load = useCallback(() => {
    api
      .violation(id)
      .then((data) => {
        setViolation(data);
        setError("");
      })
      .catch((problem) => fail(problem, setError));
  }, [id, fail]);

  useEffect(() => {
    setViolation(null);
    setMissing(false);
    load();
    api.reviewOptions().then((o) => setReasons(o.reject_reasons)).catch(() => {});
  }, [load]);

  // Another officer may act on the same violation, and the clip arrives a few
  // seconds after the alert. Reload when the server says this one changed.
  useLiveEvents((kind, data) => {
    if (kind === "connected" || String(data.id) === String(id)) load();
  });

  const decide = async (decision) => {
    setBusy(true);
    setFormError("");
    try {
      setViolation(await api.review(id, decision, decision === "Rejected" ? reason : null, note));
      setRejecting(false);
      setReason("");
      setNote("");
    } catch (problem) {
      fail(problem, setFormError);
      // The status may have changed under us; show what is true now.
      if (problem.status === 400) load();
    } finally {
      setBusy(false);
    }
  };

  const savePlate = async () => {
    setBusy(true);
    setPlateError("");
    try {
      setViolation(await api.correctPlate(id, plateInput));
      setEditingPlate(false);
    } catch (problem) {
      fail(problem, setPlateError);
    } finally {
      setBusy(false);
    }
  };

  if (missing) {
    return (
      <div className="card empty">
        This violation does not exist. <Link to="/">Back to the list</Link>
      </div>
    );
  }
  if (error && !violation) {
    return (
      <div className="alert error" role="alert">
        {error}{" "}
        <button className="link" onClick={load}>
          Try again
        </button>
      </div>
    );
  }
  if (!violation) return <div className="center muted">Loading…</div>;

  const v = violation;
  const hasPosition = v.latitude != null && v.longitude != null;
  const alert = v.alerts[v.alerts.length - 1];
  const needsNote = reason === "Other";

  return (
    <>
      <Link to="/" className="back">
        <Icon name="back" /> All alerts
      </Link>
      <div className="page-head">
        <h1>
          {vehicleName(v.vehicle_class)} <span className="muted code">{v.code}</span>
        </h1>
        <div className="head-badges">
          <ImpactBadge impact={v.impact} long />
          <StatusBadge status={v.status} />
        </div>
      </div>

      {v.other_violations_for_plate > 0 && (
        <div className="alert info" role="status">
          This plate has {v.other_violations_for_plate} other violation
          {v.other_violations_for_plate === 1 ? "" : "s"} on record. Check the photos match before
          treating it as a repeat offender.
        </div>
      )}

      <div className="detail">
        <section className="evidence">
          <div className="card media">
            {v.photo_url ? (
              <a href={v.photo_url} target="_blank" rel="noreferrer" title="Open full size">
                <img src={v.photo_url} alt={`Photo of the ${vehicleName(v.vehicle_class)} when the alert was raised`} />
              </a>
            ) : (
              <div className="empty muted">No photo was stored.</div>
            )}
          </div>
          <div className="card media">
            <h2>Clip</h2>
            {v.clip_url ? (
              <>
                <video key={v.clip_url} src={v.clip_url} controls preload="metadata" />
                <a className="small" href={v.clip_url} download>
                  Download clip
                </a>
              </>
            ) : (
              <p className="muted small">
                Not received yet. The clip arrives a few seconds after the alert.
              </p>
            )}
          </div>
        </section>

        <section className="side">
          <div className="card">
            <h2>Details</h2>
            <dl className="facts">
              <dt>Vehicle</dt>
              <dd>
                {vehicleName(v.vehicle_class)}
                {v.confidence ? (
                  <span className="muted"> ({Math.round(v.confidence * 100)}% sure)</span>
                ) : null}
              </dd>
              <dt>Plate</dt>
              <dd>
                {!editingPlate && (
                  <>
                    {v.plate_text ? (
                      <span className="plate">{v.plate_text}</span>
                    ) : (
                      <span className="muted">Not readable</span>
                    )}{" "}
                    <button
                      className="link small"
                      onClick={() => {
                        setPlateInput(v.plate_text || "");
                        setPlateError("");
                        setEditingPlate(true);
                      }}
                    >
                      {v.plate_text ? "Correct" : "Enter plate"}
                    </button>
                    {v.plate_text && v.plate_source === "auto" && (
                      <div className="muted small">
                        Read automatically
                        {v.plate_confidence != null
                          ? `, ${Math.min(99, Math.round(v.plate_confidence * 100))}% sure`
                          : ""}
                        . Check it against the photo before acting.
                      </div>
                    )}
                    {v.plate_source === "officer" && (
                      <div className="muted small">Entered by an officer.</div>
                    )}
                  </>
                )}
                {editingPlate && (
                  <div className="plate-edit">
                    <label htmlFor="plate" className="sr-only">
                      Number plate
                    </label>
                    <input
                      id="plate"
                      value={plateInput}
                      maxLength={12}
                      autoFocus
                      placeholder="e.g. LEA 1234"
                      onChange={(event) => setPlateInput(event.target.value.toUpperCase())}
                    />
                    <div className="actions">
                      <button className="button primary" disabled={busy} onClick={savePlate}>
                        Save
                      </button>
                      <button className="button ghost" disabled={busy} onClick={() => setEditingPlate(false)}>
                        Cancel
                      </button>
                    </div>
                    <div className="muted small">Leave empty if the plate cannot be read.</div>
                    {plateError && (
                      <div className="alert error" role="alert">
                        {plateError}
                      </div>
                    )}
                  </div>
                )}
                {v.plate_url && (
                  <img
                    className="plate-photo"
                    src={v.plate_url}
                    alt="Close-up of the number plate as the camera saw it"
                  />
                )}
              </dd>
              <dt>Place</dt>
              <dd>
                {v.camera_name}
                {v.zone_name ? ` (${v.zone_name})` : ""}
                {hasPosition && (
                  <div>
                    <a href={mapLink(v.latitude, v.longitude)} target="_blank" rel="noreferrer">
                      Open in Google Maps
                    </a>
                  </div>
                )}
              </dd>
              <dt>Alert raised</dt>
              <dd>{when(v.started_at)}</dd>
              <dt>Parked</dt>
              <dd>
                {v.ended_at
                  ? `${duration(v.duration_seconds)} in total, left ${when(v.ended_at)}`
                  : `${duration(v.parked_seconds)} when alerted; still there at last report`}
              </dd>
              <dt>Phone alert</dt>
              <dd>
                {!alert && <span className="muted">Not sent yet</span>}
                {alert && alert.success === 1 && "Delivered"}
                {alert && alert.success !== 1 && (
                  <span className="bad">Failed: {alert.error}</span>
                )}
              </dd>
            </dl>
          </div>

          {v.impact && (
            <div className="card">
              <h2>Traffic impact</h2>
              <p className="impact-line">
                <ImpactBadge impact={v.impact} long />
              </p>
              <dl className="facts">
                <dt>Lane blocked</dt>
                <dd>{Math.round((v.impact.lane_blocked ?? 0) * 100)}% of the vehicle is in the driving lane</dd>
                <dt>Queue</dt>
                <dd>
                  {v.impact.queued_vehicles ?? 0} vehicle{v.impact.queued_vehicles === 1 ? "" : "s"} standing behind it
                </dd>
                <dt>Traffic flow</dt>
                <dd>
                  {v.impact.baseline_ready
                    ? `${Math.round((v.impact.flow_drop ?? 0) * 100)}% below normal for this road`
                    : "Not measured: normal flow for this road is not known yet"}
                </dd>
              </dl>
              <p className="muted small">The worst level recorded while the vehicle was parked.</p>
            </div>
          )}

          <div className="card">
            <h2>Decision</h2>
            {v.allowed_decisions.length === 0 && (
              <p className="muted">This violation is closed. No further decision is possible.</p>
            )}

            {!rejecting && v.allowed_decisions.length > 0 && (
              <>
                <label htmlFor="note">Note (optional)</label>
                <textarea
                  id="note"
                  rows={2}
                  maxLength={1000}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="For example: challan number, or what you saw"
                />
                <div className="actions">
                  {v.allowed_decisions.map((decision) => {
                    const button = BUTTON[decision];
                    const onClick =
                      decision === "Rejected" ? () => setRejecting(true) : () => decide(decision);
                    return (
                      <button
                        key={decision}
                        className={`button ${button.style}`}
                        disabled={busy}
                        onClick={onClick}
                      >
                        {button.label}
                      </button>
                    );
                  })}
                </div>
              </>
            )}

            {rejecting && (
              <>
                <label htmlFor="reason">Why is this not a violation?</label>
                <select id="reason" value={reason} onChange={(event) => setReason(event.target.value)}>
                  <option value="">Choose a reason…</option>
                  {reasons.map((text) => (
                    <option key={text}>{text}</option>
                  ))}
                </select>
                <label htmlFor="reject-note">Note {needsNote ? "(required)" : "(optional)"}</label>
                <textarea
                  id="reject-note"
                  rows={2}
                  maxLength={1000}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
                <div className="actions">
                  <button
                    className="button danger"
                    disabled={busy || !reason || (needsNote && !note.trim())}
                    onClick={() => decide("Rejected")}
                  >
                    Reject alert
                  </button>
                  <button className="button ghost" disabled={busy} onClick={() => setRejecting(false)}>
                    Cancel
                  </button>
                </div>
              </>
            )}

            {formError && (
              <div className="alert error" role="alert">
                {formError}
              </div>
            )}
          </div>

          <div className="card">
            <h2>History</h2>
            <ol className="timeline">
              <li>
                <div className="t-title">Alert raised by the system</div>
                <div className="muted small">{when(v.started_at)}</div>
              </li>
              {v.reviews.map((r) => (
                <li key={r.id}>
                  <div className="t-title">
                    <StatusBadge status={r.decision} /> by {r.officer_name}
                  </div>
                  <div className="muted small">{when(r.created_at)}</div>
                  {r.reason && <div className="small">Reason: {r.reason}</div>}
                  {r.note && <div className="small note">“{r.note}”</div>}
                </li>
              ))}
            </ol>
            {v.reviews.length === 0 && <p className="muted small">No officer has reviewed this yet.</p>}
          </div>
        </section>
      </div>
    </>
  );
}

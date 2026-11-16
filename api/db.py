"""SQLite storage for cameras, violations and the alert log."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    latitude    REAL,
    longitude   REAL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS violations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    code             TEXT UNIQUE NOT NULL,
    -- Chosen by the camera worker. If the worker has to resend a report
    -- (say the reply was lost), this is how the duplicate is recognised.
    client_ref       TEXT UNIQUE NOT NULL,
    camera_id        INTEGER NOT NULL REFERENCES cameras(id),
    zone_id          TEXT,
    zone_name        TEXT,
    vehicle_class    TEXT,
    confidence       REAL,
    parked_seconds   REAL,
    started_at       TEXT NOT NULL,
    ended_at         TEXT,
    duration_seconds REAL,
    plate_text       TEXT,
    photo_file       TEXT,
    clip_file        TEXT,
    status           TEXT NOT NULL DEFAULT 'Pending',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS officers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    username       TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash  TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'officer' CHECK (role IN ('admin', 'officer')),
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL
);

-- Every decision an officer makes. Rows are only ever added: the triggers
-- below make the database itself refuse to change or delete one, so the
-- history can be trusted as a record of who decided what, and when.
CREATE TABLE IF NOT EXISTS reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    violation_id  INTEGER NOT NULL REFERENCES violations(id),
    officer_id    INTEGER NOT NULL REFERENCES officers(id),
    decision      TEXT NOT NULL,
    reason        TEXT,
    note          TEXT,
    created_at    TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS reviews_no_update BEFORE UPDATE ON reviews
BEGIN SELECT RAISE(ABORT, 'reviews are add-only'); END;

CREATE TRIGGER IF NOT EXISTS reviews_no_delete BEFORE DELETE ON reviews
BEGIN SELECT RAISE(ABORT, 'reviews are add-only'); END;

-- Who created, disabled or re-enabled a login, or reset its password.
-- Add-only, like reviews.
CREATE TABLE IF NOT EXISTS officer_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id    INTEGER NOT NULL REFERENCES officers(id),
    target_id   INTEGER NOT NULL REFERENCES officers(id),
    action      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS officer_log_no_update BEFORE UPDATE ON officer_log
BEGIN SELECT RAISE(ABORT, 'officer_log is add-only'); END;

CREATE TRIGGER IF NOT EXISTS officer_log_no_delete BEFORE DELETE ON officer_log
BEGIN SELECT RAISE(ABORT, 'officer_log is add-only'); END;

CREATE TABLE IF NOT EXISTS alert_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    violation_id  INTEGER NOT NULL REFERENCES violations(id),
    channel       TEXT NOT NULL,
    success       INTEGER NOT NULL,
    attempts      INTEGER NOT NULL,
    error         TEXT,
    created_at    TEXT NOT NULL
);
"""


#: What an officer may decide, and the status the violation takes as a result.
DECISION_STATUS = {
    "Confirmed": "Confirmed",
    "Rejected": "Rejected",
    "Action Taken": "Action Taken",
    "Reopened": "Pending",
}

#: From each status, the decisions that make sense. "Action Taken" is final.
ALLOWED_DECISIONS = {
    "Pending": ("Confirmed", "Rejected"),
    "Confirmed": ("Action Taken", "Rejected", "Reopened"),
    "Rejected": ("Reopened",),
    "Action Taken": (),
}

#: A rejection must say why. These reasons also show where the system goes
#: wrong, which is what the next round of training needs.
REJECT_REASONS = (
    "Not a vehicle",
    "Vehicle was not parked (traffic or signal)",
    "Vehicle is outside the no-parking zone",
    "Exempt vehicle (ambulance, police, official)",
    "Duplicate of another alert",
    "Other",
)

STATUSES = tuple(ALLOWED_DECISIONS)


#: Columns added after the first version. An existing database gets any that
#: are missing when the server starts, so no data has to be thrown away.
_ADDED_COLUMNS = {
    "violations": [
        ("plate_confidence", "REAL"),
        ("plate_file", "TEXT"),
        # 'auto' = read by the system, 'officer' = typed in by a person.
        ("plate_source", "TEXT"),
        # How much the vehicle held up traffic: the worst level seen.
        ("impact_score", "REAL"),
        ("impact_level", "TEXT"),
        ("impact_parts", "TEXT"),
        # Where the vehicle's box was in the picture: "x1,y1,x2,y2", each 0 to 1.
        # Lets rejected alerts at one spot be turned into an ignore area.
        ("box", "TEXT"),
    ],
}


class ReviewError(Exception):
    """A review that cannot be recorded; the message is safe to show."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            for table, columns in _ADDED_COLUMNS.items():
                existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                for name, kind in columns:
                    if name not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")

    @contextmanager
    def _connect(self):
        """A connection that commits on success, rolls back on error, and closes."""
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ---------------------------------------------------------------- cameras

    def upsert_camera(self, name: str, latitude: float | None, longitude: float | None) -> int:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO cameras (name, latitude, longitude, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     latitude  = COALESCE(excluded.latitude, latitude),
                     longitude = COALESCE(excluded.longitude, longitude)""",
                (name, latitude, longitude, utc_now()),
            )
            return conn.execute("SELECT id FROM cameras WHERE name = ?", (name,)).fetchone()["id"]

    # ------------------------------------------------------------- violations

    def create_violation(self, fields: dict) -> tuple[dict, bool]:
        """Insert a violation. Returns (row, created).

        ``created`` is False when a report with the same ``client_ref`` was
        already stored; the existing row is returned and nothing is changed.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")  # one writer at a time: codes stay unique
            existing = conn.execute(
                "SELECT id FROM violations WHERE client_ref = ?", (fields["client_ref"],)
            ).fetchone()
            if existing:
                return self.get_violation(existing["id"]), False

            day = fields["started_at"][:10].replace("-", "")
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM violations WHERE code LIKE ?", (f"PV-{day}-%",)
            ).fetchone()["n"]
            code = f"PV-{day}-{count + 1:04d}"

            cursor = conn.execute(
                """INSERT INTO violations
                   (code, client_ref, camera_id, zone_id, zone_name, vehicle_class,
                    confidence, parked_seconds, started_at, created_at,
                    plate_text, plate_confidence, plate_source,
                    impact_score, impact_level, impact_parts, box)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    code,
                    fields["client_ref"],
                    fields["camera_id"],
                    fields.get("zone_id"),
                    fields.get("zone_name"),
                    fields.get("vehicle_class"),
                    fields.get("confidence"),
                    fields.get("parked_seconds"),
                    fields["started_at"],
                    utc_now(),
                    fields.get("plate_text"),
                    fields.get("plate_confidence") if fields.get("plate_text") else None,
                    "auto" if fields.get("plate_text") else None,
                    fields.get("impact_score"),
                    fields.get("impact_level"),
                    fields.get("impact_parts"),
                    fields.get("box"),
                ),
            )
            violation_id = cursor.lastrowid
        return self.get_violation(violation_id), True

    def set_violation_files(
        self,
        violation_id: int,
        photo_file: str | None = None,
        clip_file: str | None = None,
        plate_file: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE violations SET
                     photo_file = COALESCE(?, photo_file),
                     clip_file  = COALESCE(?, clip_file),
                     plate_file = COALESCE(?, plate_file)
                   WHERE id = ?""",
                (photo_file, clip_file, plate_file, violation_id),
            )

    def end_violation(self, client_ref: str, ended_at: str, duration_seconds: float) -> dict | None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE violations SET ended_at = ?, duration_seconds = ? WHERE client_ref = ?",
                (ended_at, duration_seconds, client_ref),
            )
        return self.get_violation_by_ref(client_ref)

    def raise_impact(
        self, client_ref: str, score: float, level: str, parts: str | None
    ) -> dict | None:
        """Record a higher traffic impact. A lower one is ignored: the stored
        value is the worst the violation caused, not the latest reading."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE violations
                   SET impact_score = ?, impact_level = ?, impact_parts = ?
                   WHERE client_ref = ? AND COALESCE(impact_score, -1) < ?""",
                (score, level, parts, client_ref, score),
            )
        return self.get_violation_by_ref(client_ref)

    def count_other_violations_for_plate(self, plate_text: str, violation_id: int) -> int:
        with self._connect() as conn:
            return conn.execute(
                """SELECT COUNT(*) AS n FROM violations
                   WHERE plate_text = ? AND id != ? AND status != 'Rejected'""",
                (plate_text, violation_id),
            ).fetchone()["n"]

    def all_violations(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(_SELECT)]

    def not_a_vehicle_boxes(self, camera_name: str | None = None) -> list[dict]:
        """Boxes of alerts that stand rejected as "Not a vehicle".

        Only alerts that recorded a box are returned. An alert that was
        reopened after the rejection is no longer Rejected and is left out.
        """
        query = """SELECT v.code, v.box, v.zone_id, c.name AS camera_name
                   FROM violations v JOIN cameras c ON c.id = v.camera_id
                   WHERE v.status = 'Rejected' AND v.box IS NOT NULL
                     AND (SELECT r.reason FROM reviews r
                          WHERE r.violation_id = v.id AND r.decision = 'Rejected'
                          ORDER BY r.id DESC LIMIT 1) = 'Not a vehicle'"""
        args: tuple = ()
        if camera_name:
            query += " AND c.name = ?"
            args = (camera_name,)
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query + " ORDER BY v.id", args)]

    def reject_reason_counts(self) -> list[dict]:
        """Why alerts that are rejected right now were rejected."""
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """SELECT r.reason, COUNT(*) AS count
                       FROM reviews r JOIN violations v ON v.id = r.violation_id
                       WHERE v.status = 'Rejected' AND r.decision = 'Rejected'
                         AND r.id = (SELECT MAX(id) FROM reviews
                                     WHERE violation_id = v.id AND decision = 'Rejected')
                       GROUP BY r.reason ORDER BY count DESC"""
                )
            ]

    def get_violation(self, violation_id: int) -> dict | None:
        return self._one("v.id = ?", violation_id)

    def get_violation_by_ref(self, client_ref: str) -> dict | None:
        return self._one("v.client_ref = ?", client_ref)

    def list_violations(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        by_impact: bool = False,
    ) -> list[dict]:
        query = _SELECT
        params: list = []
        if status:
            query += " WHERE v.status = ?"
            params.append(status)
        # Worst traffic impact first when asked; unmeasured ones come last.
        order = "COALESCE(v.impact_score, -1) DESC, v.id DESC" if by_impact else "v.id DESC"
        query += f" ORDER BY {order} LIMIT ? OFFSET ?"
        params += [limit, offset]
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    def count_by_status(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        with self._connect() as conn:
            for row in conn.execute("SELECT status, COUNT(*) AS n FROM violations GROUP BY status"):
                counts[row["status"]] = row["n"]
        return counts

    # ---------------------------------------------------------------- officers

    def create_officer(self, name: str, username: str, password_hash: str, role: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO officers (name, username, password_hash, role, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, username, password_hash, role, utc_now()),
            )
            return cursor.lastrowid

    def set_officer_password(self, username: str, password_hash: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE officers SET password_hash = ? WHERE username = ?",
                (password_hash, username),
            )
            return cursor.rowcount > 0

    def set_officer_password_by_id(self, officer_id: int, password_hash: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE officers SET password_hash = ? WHERE id = ?", (password_hash, officer_id))

    def set_officer_active(self, officer_id: int, active: bool) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE officers SET active = ? WHERE id = ?", (int(active), officer_id))

    def count_active_admins(self) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM officers WHERE role = 'admin' AND active = 1"
            ).fetchone()[0]

    def log_officer_change(self, actor_id: int, target_id: int, action: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO officer_log (actor_id, target_id, action, created_at) VALUES (?, ?, ?, ?)",
                (actor_id, target_id, action, utc_now()),
            )

    def list_officer_log(self, limit: int = 30) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """SELECT l.action, l.created_at, a.name AS actor, t.name AS target
                       FROM officer_log l
                       JOIN officers a ON a.id = l.actor_id
                       JOIN officers t ON t.id = l.target_id
                       ORDER BY l.id DESC LIMIT ?""",
                    (limit,),
                )
            ]

    def get_officer(self, officer_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM officers WHERE id = ?", (officer_id,)).fetchone()
        return dict(row) if row else None

    def get_officer_by_username(self, username: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM officers WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def list_officers(self) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT id, name, username, role, active, created_at FROM officers ORDER BY id"
                )
            ]

    # ----------------------------------------------------------------- reviews

    def record_review(
        self,
        violation_id: int,
        officer_id: int,
        decision: str,
        reason: str | None,
        note: str | None,
    ) -> dict | None:
        """Record a decision and move the violation to its new status.

        Both happen in one transaction, so a violation's status always matches
        its latest review. Returns None if the violation does not exist.
        """
        if decision not in DECISION_STATUS:
            raise ReviewError(f"Unknown decision. Allowed: {', '.join(DECISION_STATUS)}")
        if decision == "Rejected":
            if reason not in REJECT_REASONS:
                raise ReviewError("A rejection needs one of the listed reasons")
            if reason == "Other" and not (note or "").strip():
                raise ReviewError('Reason "Other" needs a note explaining it')
        else:
            reason = None

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM violations WHERE id = ?", (violation_id,)
            ).fetchone()
            if row is None:
                return None
            allowed = ALLOWED_DECISIONS.get(row["status"], ())
            if decision not in allowed:
                options = ", ".join(allowed) or "none; it is closed"
                raise ReviewError(
                    f'A violation that is "{row["status"]}" cannot be marked '
                    f'"{decision}". Allowed: {options}.'
                )
            conn.execute(
                """INSERT INTO reviews (violation_id, officer_id, decision, reason, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (violation_id, officer_id, decision, reason, (note or "").strip() or None, utc_now()),
            )
            conn.execute(
                "UPDATE violations SET status = ? WHERE id = ?",
                (DECISION_STATUS[decision], violation_id),
            )
        return self.get_violation(violation_id)

    def correct_plate(self, violation_id: int, officer_id: int, plate_text: str | None) -> dict | None:
        """An officer sets, changes or clears the plate. Recorded in the history.

        The status does not change: correcting a plate is not a decision about
        whether the violation is real.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT plate_text FROM violations WHERE id = ?", (violation_id,)
            ).fetchone()
            if row is None:
                return None
            old = row["plate_text"]
            if old == plate_text:
                raise ReviewError("That is already the plate on record")
            conn.execute(
                """INSERT INTO reviews (violation_id, officer_id, decision, reason, note, created_at)
                   VALUES (?, ?, 'Plate corrected', NULL, ?, ?)""",
                (violation_id, officer_id, f"{old or 'not read'} → {plate_text or 'not readable'}", utc_now()),
            )
            conn.execute(
                """UPDATE violations
                   SET plate_text = ?, plate_confidence = NULL, plate_source = 'officer'
                   WHERE id = ?""",
                (plate_text, violation_id),
            )
        return self.get_violation(violation_id)

    def list_reviews(self, violation_id: int) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """SELECT r.id, r.decision, r.reason, r.note, r.created_at,
                              o.name AS officer_name, o.username AS officer_username
                       FROM reviews r JOIN officers o ON o.id = r.officer_id
                       WHERE r.violation_id = ? ORDER BY r.id""",
                    (violation_id,),
                )
            ]

    def _one(self, where: str, value) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(f"{_SELECT} WHERE {where}", (value,)).fetchone()
        return dict(row) if row else None

    # -------------------------------------------------------------- alert log

    def log_alert(
        self, violation_id: int, channel: str, success: bool, attempts: int, error: str | None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO alert_log
                   (violation_id, channel, success, attempts, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (violation_id, channel, int(success), attempts, error, utc_now()),
            )

    def list_alerts(self, violation_id: int) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM alert_log WHERE violation_id = ? ORDER BY id", (violation_id,)
                )
            ]


_SELECT = """
SELECT v.*, c.name AS camera_name, c.latitude, c.longitude
FROM violations v JOIN cameras c ON c.id = v.camera_id
"""

"""RahSaaf API server.

    uv run uvicorn api.main:app --host 127.0.0.1 --port 8000

Three groups of routes:

* ``/internal/...``  the camera worker reports violations here.
* ``/api/...``       the dashboard reads and reviews them; needs a login.
* everything else    the dashboard's own pages, once it has been built.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import secrets

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from api import analytics, auth
from api.alerts import send_violation_alert
from api.config import Settings, load_settings
from api.db import ALLOWED_DECISIONS, REJECT_REASONS, STATUSES, Database, ReviewError, utc_now
from api.events import EventLog
from api.media import make_browser_playable

logger = logging.getLogger(__name__)

MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_CLIP_BYTES = 50 * 1024 * 1024
_REF = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_EVIDENCE_NAME = re.compile(r"^PV-\d{8}-\d{4}(\.jpg|\.mp4|_plate\.jpg)$")
_PLATE = re.compile(r"^[A-Z0-9]{2,10}$")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


_PASSWORD = Field(min_length=auth.MIN_PASSWORD_LENGTH, max_length=256)


class NewOfficerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    password: str = _PASSWORD
    role: str = Field(default="officer", pattern=r"^(officer|admin)$")


class ActiveRequest(BaseModel):
    active: bool


class ResetPasswordRequest(BaseModel):
    password: str = _PASSWORD


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = _PASSWORD


class PlateRequest(BaseModel):
    #: Empty means "the plate cannot be read".
    plate_text: str = Field(default="", max_length=20)


class ReviewRequest(BaseModel):
    decision: str = Field(max_length=32)
    reason: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=1000)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.database_path)
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    secret = auth.load_or_create_secret(
        settings.secret_key, settings.database_path.with_name("secret.key")
    )
    limiter = auth.LoginLimiter()
    events = EventLog()

    app = FastAPI(title="RahSaaf", version="0.5.0")
    app.state.settings = settings
    app.state.db = db
    app.state.events = events
    app.state.login_limiter = limiter

    # ------------------------------------------------------------ who may call

    def require_worker(request: Request) -> None:
        """Only the camera worker may report violations.

        With a shared key configured, the key is required. Without one, only
        requests from this same machine are accepted.
        """
        if settings.internal_api_key:
            given = request.headers.get("x-internal-key", "")
            if not secrets.compare_digest(given, settings.internal_api_key):
                raise HTTPException(status_code=401, detail="Invalid internal key")
            return
        host = request.client.host if request.client else ""
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "testclient"
        if not local:
            raise HTTPException(status_code=403, detail="Internal endpoint")

    def current_officer(request: Request) -> dict:
        token = request.cookies.get(auth.COOKIE_NAME, "")
        session = auth.read_session(token, secret) if token else None
        officer = db.get_officer(session[0]) if session else None
        if officer is None or not officer["active"]:
            raise HTTPException(status_code=401, detail="Not logged in")
        # A session opened before the password was changed no longer counts.
        if session[1] != auth.password_stamp(officer["password_hash"]):
            raise HTTPException(status_code=401, detail="Not logged in")
        return officer

    def current_admin(officer: dict = Depends(current_officer)) -> dict:
        if officer["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only an admin can do this")
        return officer

    def start_session(response: Response, officer: dict) -> None:
        response.set_cookie(
            auth.COOKIE_NAME,
            auth.create_session_token(
                officer["id"], secret, settings.session_hours, auth.password_stamp(officer["password_hash"])
            ),
            max_age=int(settings.session_hours * 3600),
            httponly=True,  # page scripts cannot read it
            samesite="strict",  # never sent on requests started by other sites
            secure=settings.cookie_secure,
            path="/",
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if settings.cookie_secure:
            # Tell the browser to use HTTPS for this address from now on.
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    def require_json(request: Request) -> None:
        """Changes must arrive as JSON.

        A web page on another site can make a browser send a form to this
        server with the officer's login cookie attached, but it cannot send
        JSON without the browser first asking this server's permission. This,
        with the SameSite cookie, stops other sites acting as the officer.
        """
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(status_code=415, detail="Send JSON")

    # ----------------------------------------------------------------- helpers

    async def save_upload(upload: UploadFile, name: str, limit: int) -> str:
        target = settings.evidence_dir / name
        written = 0
        try:
            with target.open("wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    written += len(chunk)
                    if written > limit:
                        raise HTTPException(status_code=413, detail="File too large")
                    handle.write(chunk)
        except HTTPException:
            target.unlink(missing_ok=True)
            raise
        if written == 0:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Empty file")
        return name

    def check_ref(client_ref: str) -> str:
        if not _REF.match(client_ref):
            raise HTTPException(status_code=400, detail="Invalid client_ref")
        return client_ref

    def check_impact(score: float | None, level: str, parts: str) -> dict:
        """Validate a traffic-impact report; {} when none was sent."""
        if score is None:
            return {}
        if not 0 <= score <= 1 or level not in ("Low", "Medium", "High"):
            raise HTTPException(status_code=400, detail="Invalid impact")
        cleaned = None
        if parts:
            try:
                parsed = json.loads(parts)
            except ValueError:
                parsed = None
            if not isinstance(parsed, dict) or len(parts) > 1000:
                raise HTTPException(status_code=400, detail="Invalid impact_parts")
            cleaned = json.dumps(parsed)
        return {"impact_score": score, "impact_level": level, "impact_parts": cleaned}

    def public(violation: dict) -> dict:
        """What the dashboard receives: the row plus links to its evidence."""
        out = {k: v for k, v in violation.items() if k != "client_ref"}
        for key, field in (
            ("photo_url", "photo_file"),
            ("clip_url", "clip_file"),
            ("plate_url", "plate_file"),
        ):
            name = violation.get(field)
            out[key] = f"/api/evidence/{name}" if name else None
        parts = out.pop("impact_parts", None)
        out["impact"] = (
            {"score": out["impact_score"], "level": out["impact_level"], **json.loads(parts or "{}")}
            if out.get("impact_score") is not None
            else None
        )
        out["allowed_decisions"] = list(ALLOWED_DECISIONS.get(violation["status"], ()))
        return out

    def detail(violation: dict) -> dict:
        """Everything the violation page shows."""
        out = public(violation)
        out["reviews"] = db.list_reviews(violation["id"])
        out["alerts"] = db.list_alerts(violation["id"])
        # How many other times this plate has been caught. Shown as a warning
        # sign of a repeat offender, never as proof: plates can be misread.
        out["other_violations_for_plate"] = (
            db.count_other_violations_for_plate(violation["plate_text"], violation["id"])
            if violation["plate_text"]
            else 0
        )
        return out

    def officer_view(officer: dict) -> dict:
        return {k: officer[k] for k in ("id", "name", "username", "role")}

    def announce(kind: str, violation: dict) -> None:
        events.publish(kind, {"id": violation["id"], "code": violation["code"], "status": violation["status"]})

    # ------------------------------------------------------------- worker side

    @app.post("/internal/violations", status_code=201, dependencies=[Depends(require_worker)])
    async def report_violation(
        background: BackgroundTasks,
        client_ref: str = Form(...),
        camera_name: str = Form(...),
        latitude: float | None = Form(None),
        longitude: float | None = Form(None),
        zone_id: str = Form(""),
        zone_name: str = Form(""),
        vehicle_class: str = Form("vehicle"),
        confidence: float = Form(0.0),
        parked_seconds: float = Form(0.0),
        started_at: str = Form(""),
        plate_text: str = Form(""),
        plate_confidence: float | None = Form(None),
        impact_score: float | None = Form(None),
        impact_level: str = Form(""),
        impact_parts: str = Form(""),
        box: str = Form(""),
        photo: UploadFile = File(...),
        plate_photo: UploadFile | None = File(None),
    ):
        check_ref(client_ref)
        camera_name = camera_name.strip()[:100]
        if not camera_name:
            raise HTTPException(status_code=400, detail="camera_name is required")
        if latitude is not None and not -90 <= latitude <= 90:
            raise HTTPException(status_code=400, detail="latitude out of range")
        if longitude is not None and not -180 <= longitude <= 180:
            raise HTTPException(status_code=400, detail="longitude out of range")

        plate = re.sub(r"[^A-Z0-9]", "", plate_text.upper())
        if plate and not _PLATE.match(plate):
            raise HTTPException(status_code=400, detail="plate_text is not a plate")
        if plate_confidence is not None and not 0 <= plate_confidence <= 1:
            raise HTTPException(status_code=400, detail="plate_confidence out of range")

        impact = check_impact(impact_score, impact_level, impact_parts)

        if box:
            try:
                x1, y1, x2, y2 = (float(part) for part in box.split(","))
            except ValueError:
                raise HTTPException(status_code=400, detail="box must be four numbers")
            if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
                raise HTTPException(status_code=400, detail="box out of range")
            box = f"{x1:.4f},{y1:.4f},{x2:.4f},{y2:.4f}"

        camera_id = db.upsert_camera(camera_name, latitude, longitude)
        violation, created = db.create_violation(
            {
                "client_ref": client_ref,
                "camera_id": camera_id,
                "zone_id": zone_id[:50] or None,
                "zone_name": zone_name[:100] or None,
                "vehicle_class": vehicle_class[:30],
                "confidence": confidence,
                "parked_seconds": parked_seconds,
                "started_at": started_at or utc_now(),
                "plate_text": plate or None,
                "plate_confidence": plate_confidence,
                "box": box or None,
                **impact,
            }
        )
        if created:
            photo_file = await save_upload(photo, f"{violation['code']}.jpg", MAX_PHOTO_BYTES)
            plate_file = None
            if plate_photo is not None:
                plate_file = await save_upload(
                    plate_photo, f"{violation['code']}_plate.jpg", MAX_PHOTO_BYTES
                )
            db.set_violation_files(violation["id"], photo_file=photo_file, plate_file=plate_file)
            announce("violation_created", violation)
            # Sent after the reply, so a slow Telegram never holds up the worker.
            background.add_task(send_violation_alert, db, settings, violation["id"])
        return {"id": violation["id"], "code": violation["code"]}

    @app.post("/internal/violations/{client_ref}/ended", dependencies=[Depends(require_worker)])
    def report_ended(client_ref: str, duration_seconds: float = Form(...), ended_at: str = Form("")):
        check_ref(client_ref)
        violation = db.end_violation(client_ref, ended_at or utc_now(), duration_seconds)
        if violation is None:
            raise HTTPException(status_code=404, detail="Violation not found")
        announce("violation_updated", violation)
        return {"id": violation["id"], "code": violation["code"]}

    @app.post("/internal/violations/{client_ref}/impact", dependencies=[Depends(require_worker)])
    def report_impact(
        client_ref: str,
        impact_score: float = Form(...),
        impact_level: str = Form(...),
        impact_parts: str = Form(""),
    ):
        check_ref(client_ref)
        impact = check_impact(impact_score, impact_level, impact_parts)
        violation = db.raise_impact(
            client_ref, impact["impact_score"], impact["impact_level"], impact["impact_parts"]
        )
        if violation is None:
            raise HTTPException(status_code=404, detail="Violation not found")
        announce("violation_updated", violation)
        return {"id": violation["id"], "code": violation["code"]}

    @app.post("/internal/violations/{client_ref}/clip", dependencies=[Depends(require_worker)])
    async def report_clip(client_ref: str, background: BackgroundTasks, clip: UploadFile = File(...)):
        check_ref(client_ref)
        violation = db.get_violation_by_ref(client_ref)
        if violation is None:
            raise HTTPException(status_code=404, detail="Violation not found")
        clip_file = await save_upload(clip, f"{violation['code']}.mp4", MAX_CLIP_BYTES)
        db.set_violation_files(violation["id"], clip_file=clip_file)
        background.add_task(make_browser_playable, settings.evidence_dir / clip_file)
        announce("violation_updated", violation)
        return {"id": violation["id"], "code": violation["code"]}

    # ------------------------------------------------------------------- login

    @app.post("/api/auth/login", dependencies=[Depends(require_json)])
    def login(body: LoginRequest, request: Request, response: Response):
        address = request.client.host if request.client else ""
        username = body.username.strip()

        locked = limiter.seconds_locked(username, address)
        if locked > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Too many wrong passwords. Try again in {int(locked // 60) + 1} minute(s).",
            )

        officer = db.get_officer_by_username(username)
        # Check a password even for an unknown username, so the reply takes
        # the same time either way and does not reveal which usernames exist.
        stored = officer["password_hash"] if officer else _DUMMY_HASH
        correct = auth.verify_password(body.password, stored)
        if not (officer and correct and officer["active"]):
            limiter.record_failure(username, address)
            raise HTTPException(status_code=401, detail="Wrong username or password")

        limiter.record_success(username, address)
        start_session(response, officer)
        return officer_view(officer)

    @app.post("/api/auth/logout")
    def logout(response: Response):
        response.delete_cookie(auth.COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/me")
    def me(officer: dict = Depends(current_officer)):
        return officer_view(officer)

    @app.post("/api/me/password", dependencies=[Depends(require_json)])
    def change_own_password(
        body: ChangePasswordRequest, response: Response, officer: dict = Depends(current_officer)
    ):
        if not auth.verify_password(body.current_password, officer["password_hash"]):
            raise HTTPException(status_code=400, detail="The current password is wrong")
        db.set_officer_password_by_id(officer["id"], auth.hash_password(body.new_password))
        db.log_officer_change(officer["id"], officer["id"], "changed own password")
        # Every other session of this login ends; this one continues.
        start_session(response, db.get_officer(officer["id"]))
        return {"ok": True}

    # ------------------------------------------------------- managing logins

    def officers_page() -> dict:
        return {"officers": db.list_officers(), "log": db.list_officer_log()}

    def target_officer(officer_id: int) -> dict:
        target = db.get_officer(officer_id)
        if target is None:
            raise HTTPException(status_code=404, detail="No such login")
        return target

    @app.get("/api/officers")
    def list_officers(_: dict = Depends(current_admin)):
        return officers_page()

    @app.post("/api/officers", status_code=201, dependencies=[Depends(require_json)])
    def add_officer(body: NewOfficerRequest, admin: dict = Depends(current_admin)):
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Give the full name")
        if db.get_officer_by_username(body.username) is not None:
            raise HTTPException(status_code=409, detail="That username is already taken")
        new_id = db.create_officer(name, body.username, auth.hash_password(body.password), body.role)
        db.log_officer_change(admin["id"], new_id, f"created as {body.role}")
        return officers_page()

    @app.post("/api/officers/{officer_id}/active", dependencies=[Depends(require_json)])
    def set_active(officer_id: int, body: ActiveRequest, admin: dict = Depends(current_admin)):
        target = target_officer(officer_id)
        if bool(target["active"]) != body.active:
            if not body.active:
                if target["id"] == admin["id"]:
                    raise HTTPException(status_code=400, detail="You cannot disable your own login")
                if target["role"] == "admin" and db.count_active_admins() <= 1:
                    raise HTTPException(status_code=400, detail="This is the last admin login")
            db.set_officer_active(officer_id, body.active)
            db.log_officer_change(admin["id"], officer_id, "enabled" if body.active else "disabled")
        return officers_page()

    @app.post("/api/officers/{officer_id}/password", dependencies=[Depends(require_json)])
    def reset_password(officer_id: int, body: ResetPasswordRequest, admin: dict = Depends(current_admin)):
        target = target_officer(officer_id)
        if target["id"] == admin["id"]:
            raise HTTPException(status_code=400, detail="Change your own password under Account")
        db.set_officer_password_by_id(officer_id, auth.hash_password(body.password))
        db.log_officer_change(admin["id"], officer_id, "password reset")
        return officers_page()

    # ------------------------------------------------------------- dashboard

    @app.get("/api/violations", dependencies=[Depends(current_officer)])
    def list_violations(
        status: str | None = None, limit: int = 50, offset: int = 0, sort: str = "newest"
    ):
        if sort not in ("newest", "impact"):
            raise HTTPException(status_code=400, detail="sort is 'newest' or 'impact'")
        if status is not None and status not in STATUSES:
            raise HTTPException(status_code=400, detail=f"Unknown status. Allowed: {', '.join(STATUSES)}")
        limit = max(1, min(limit, 200))
        rows = db.list_violations(
            status=status, limit=limit, offset=max(0, offset), by_impact=sort == "impact"
        )
        return {"items": [public(v) for v in rows], "counts": db.count_by_status()}

    @app.get("/api/violations/{violation_id}", dependencies=[Depends(current_officer)])
    def get_violation(violation_id: int):
        violation = db.get_violation(violation_id)
        if violation is None:
            raise HTTPException(status_code=404, detail="Violation not found")
        return detail(violation)

    @app.post("/api/violations/{violation_id}/review", dependencies=[Depends(require_json)])
    def review_violation(
        violation_id: int, body: ReviewRequest, officer: dict = Depends(current_officer)
    ):
        try:
            violation = db.record_review(
                violation_id, officer["id"], body.decision, body.reason, body.note
            )
        except ReviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        if violation is None:
            raise HTTPException(status_code=404, detail="Violation not found")
        announce("violation_updated", violation)
        return detail(violation)

    @app.post("/api/violations/{violation_id}/plate", dependencies=[Depends(require_json)])
    def correct_plate(
        violation_id: int, body: PlateRequest, officer: dict = Depends(current_officer)
    ):
        plate = re.sub(r"[^A-Z0-9]", "", body.plate_text.upper())
        # Something was typed but none of it is a letter or digit. Treating
        # that as "unreadable" would silently wipe the plate on a typing slip.
        typed_nonsense = bool(body.plate_text.strip()) and not plate
        if typed_nonsense or (plate and not _PLATE.match(plate)):
            raise HTTPException(
                status_code=400, detail="A plate is 2 to 10 letters and digits"
            )
        try:
            violation = db.correct_plate(violation_id, officer["id"], plate or None)
        except ReviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        if violation is None:
            raise HTTPException(status_code=404, detail="Violation not found")
        announce("violation_updated", violation)
        return detail(violation)

    @app.get("/api/analytics", dependencies=[Depends(current_officer)])
    def get_analytics(days: int = 30):
        days = max(1, min(days, 365))
        return analytics.build(
            db.all_violations(), db.reject_reason_counts(), settings.timezone, days
        )

    @app.get("/api/review-options", dependencies=[Depends(current_officer)])
    def review_options():
        return {"statuses": list(STATUSES), "reject_reasons": list(REJECT_REASONS)}

    @app.get("/api/evidence/{name}", dependencies=[Depends(current_officer)])
    def get_evidence(name: str):
        if not _EVIDENCE_NAME.match(name):
            raise HTTPException(status_code=404, detail="Not found")
        path = settings.evidence_dir / name
        if not path.exists():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(path, headers={"Cache-Control": "private, max-age=60"})

    @app.get("/api/events", dependencies=[Depends(current_officer)])
    async def stream_events(request: Request):
        async def stream():
            last = events.last_id
            yield "retry: 3000\n\n"
            idle = 0.0
            while not await request.is_disconnected():
                fresh = events.since(last)
                for event_id, kind, data in fresh:
                    last = event_id
                    yield f"id: {event_id}\nevent: {kind}\ndata: {json.dumps(data)}\n\n"
                if fresh:
                    idle = 0.0
                elif idle >= 15:
                    yield ": keep-alive\n\n"  # stops proxies closing a quiet connection
                    idle = 0.0
                await asyncio.sleep(0.5)
                idle += 0.5

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "telegram_configured": settings.telegram_configured}

    # --------------------------------------------------------- dashboard pages

    index = settings.dashboard_dir / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def dashboard(path: str):
        if path.startswith(("api/", "internal/")):
            raise HTTPException(status_code=404, detail="Not found")
        if not index.exists():
            raise HTTPException(
                status_code=404,
                detail="The dashboard has not been built. Run: npm --prefix dashboard run build",
            )
        # A real file (script, stylesheet, icon) is served as it is; any other
        # address is a page inside the dashboard, which starts from index.html.
        candidate = (settings.dashboard_dir / path).resolve()
        if path and candidate.is_file() and settings.dashboard_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


#: Checked when someone tries a username that does not exist.
_DUMMY_HASH = auth.hash_password(secrets.token_urlsafe(16))


def _default_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return create_app()


def __getattr__(name: str):
    # ``uvicorn api.main:app`` builds the app on demand, so importing this
    # module in tests does not create a database or read the real settings.
    if name == "app":
        return _default_app()
    raise AttributeError(name)

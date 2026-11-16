import sqlite3
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from api import auth
from api.main import create_app

PHOTO = b"\xff\xd8 fake jpeg \xff\xd9"
PASSWORD = "a-long-test-password"


@pytest.fixture
def app(settings):
    application = create_app(settings)
    db = application.state.db
    db.create_officer("Ali Khan", "ali", auth.hash_password(PASSWORD), "officer")
    db.create_officer("Sara Shah", "sara", auth.hash_password(PASSWORD), "officer")
    return application


@pytest.fixture
def anonymous(app):
    """A client that has not logged in. The camera worker is one of these."""
    return TestClient(app)


@pytest.fixture
def client(app):
    """A client logged in as officer Ali."""
    logged_in = TestClient(app)
    assert login(logged_in).status_code == 200
    return logged_in


def login(client, username="ali", password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def report(client, ref="ref-00000001", **overrides):
    data = {
        "client_ref": ref,
        "camera_name": "Hospital gate",
        "latitude": "34.0151",
        "longitude": "71.5249",
        "zone_id": "zone1",
        "zone_name": "North kerb",
        "vehicle_class": "car",
        "confidence": "0.81",
        "parked_seconds": "120",
        "started_at": "2026-11-13T17:24:29+00:00",
        **overrides,
    }
    data = {k: v for k, v in data.items() if v is not None}
    return client.post(
        "/internal/violations", data=data, files={"photo": ("v.jpg", PHOTO, "image/jpeg")}
    )


def review(client, violation_id, decision, reason=None, note=None):
    return client.post(
        f"/api/violations/{violation_id}/review",
        json={"decision": decision, "reason": reason, "note": note},
    )


# ------------------------------------------------------------ worker reports


def test_reporting_a_violation_stores_it_and_sends_the_alert(client, settings, telegram):
    response = report(client)
    assert response.status_code == 201
    assert response.json()["code"] == "PV-20261113-0001"
    assert (settings.evidence_dir / "PV-20261113-0001.jpg").read_bytes() == PHOTO
    assert telegram.methods() == ["sendPhoto", "sendLocation"]

    detail = client.get(f"/api/violations/{response.json()['id']}").json()
    assert detail["status"] == "Pending"
    assert detail["camera_name"] == "Hospital gate"
    assert detail["photo_url"] == "/api/evidence/PV-20261113-0001.jpg"
    assert detail["alerts"][0]["success"] == 1
    assert "client_ref" not in detail


def test_codes_count_up_within_a_day(client):
    assert report(client, ref="ref-00000001").json()["code"].endswith("-0001")
    assert report(client, ref="ref-00000002").json()["code"].endswith("-0002")


def test_resent_report_does_not_create_or_alert_twice(client, telegram):
    first = report(client).json()
    second = report(client)
    assert second.status_code == 201
    assert second.json()["id"] == first["id"]
    assert len(client.get("/api/violations").json()["items"]) == 1
    assert telegram.methods().count("sendPhoto") == 1


def test_ended_and_clip_update_the_violation(client):
    created = report(client).json()
    ended = client.post(
        "/internal/violations/ref-00000001/ended",
        data={"duration_seconds": "431.5", "ended_at": "2026-11-13T17:31:40+00:00"},
    )
    assert ended.status_code == 200
    clip = client.post(
        "/internal/violations/ref-00000001/clip",
        files={"clip": ("v.mp4", b"fake mp4 bytes", "video/mp4")},
    )
    assert clip.status_code == 200

    detail = client.get(f"/api/violations/{created['id']}").json()
    assert detail["duration_seconds"] == 431.5
    assert detail["clip_url"] == f"/api/evidence/{created['code']}.mp4"
    # Not a real video, so the converter leaves it untouched.
    assert client.get(detail["clip_url"]).content == b"fake mp4 bytes"


def test_updates_for_an_unknown_violation_are_404(client):
    assert client.post(
        "/internal/violations/ref-unknown01/ended", data={"duration_seconds": "5"}
    ).status_code == 404
    assert client.post(
        "/internal/violations/ref-unknown01/clip", files={"clip": ("v.mp4", b"x", "video/mp4")}
    ).status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"client_ref": "short"},
        {"client_ref": "../../etc/passwd"},
        {"camera_name": "   "},
        {"latitude": "123"},
        {"longitude": "-200"},
    ],
)
def test_bad_reports_are_rejected(client, telegram, overrides):
    ref = overrides.pop("client_ref", "ref-00000001")
    assert report(client, ref=ref, **overrides).status_code == 400
    assert telegram.calls == []


def test_empty_photo_is_rejected(client):
    response = client.post(
        "/internal/violations",
        data={"client_ref": "ref-00000001", "camera_name": "Gate"},
        files={"photo": ("v.jpg", b"", "image/jpeg")},
    )
    assert response.status_code == 400


def test_position_is_optional(client, telegram):
    created = report(client, latitude=None, longitude=None).json()
    assert client.get(f"/api/violations/{created['id']}").json()["latitude"] is None
    assert telegram.methods() == ["sendPhoto"]


def test_reports_from_another_machine_are_refused(app):
    outsider = TestClient(app, client=("203.0.113.9", 5000))
    assert report(outsider).status_code == 403
    assert outsider.get("/health").status_code == 200


def test_internal_key_is_required_when_configured(settings):
    keyed = create_app(replace(settings, internal_api_key="s3cret-key"))
    assert report(TestClient(keyed)).status_code == 401
    assert report(TestClient(keyed, headers={"x-internal-key": "wrong"})).status_code == 401
    remote = TestClient(keyed, client=("203.0.113.9", 5000), headers={"x-internal-key": "s3cret-key"})
    assert report(remote).status_code == 201


def test_alert_failure_does_not_fail_the_report(client, telegram, monkeypatch):
    import api.alerts

    monkeypatch.setattr(api.alerts, "RETRY_DELAYS", (0.0, 0.0))
    telegram.fail_next = 99
    response = report(client)
    assert response.status_code == 201
    detail = client.get(f"/api/violations/{response.json()['id']}").json()
    assert detail["alerts"][0]["success"] == 0


# --------------------------------------------------------------------- login


def test_login_sets_a_protected_cookie(anonymous):
    response = login(anonymous)
    assert response.status_code == 200
    assert response.json() == {"id": 1, "name": "Ali Khan", "username": "ali", "role": "officer"}
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert anonymous.get("/api/me").json()["username"] == "ali"


def test_username_is_not_case_sensitive(anonymous):
    assert login(anonymous, username="ALI").status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(anonymous):
    wrong = login(anonymous, password="not-the-password")
    unknown = login(anonymous, username="nobody")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert "set-cookie" not in wrong.headers


def test_login_locks_after_five_wrong_passwords(anonymous):
    for _ in range(5):
        assert login(anonymous, password="wrong-password").status_code == 401
    locked = login(anonymous)  # even the right password is refused now
    assert locked.status_code == 429
    assert "minute" in locked.json()["detail"]
    assert login(anonymous, username="sara").status_code == 200  # others unaffected


def test_logout_ends_the_session(client):
    assert client.get("/api/me").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/me").status_code == 401


def test_disabled_officer_is_shut_out_even_with_a_valid_session(client, settings):
    with sqlite3.connect(settings.database_path) as conn:
        conn.execute("UPDATE officers SET active = 0 WHERE username = 'ali'")
    assert client.get("/api/me").status_code == 401
    assert login(TestClient(client.app)).status_code == 401


def test_session_from_another_server_key_is_refused(app, settings):
    forged = auth.create_session_token(1, "some-other-secret-that-is-long-enough", hours=1)
    intruder = TestClient(app, cookies={auth.COOKIE_NAME: forged})
    assert intruder.get("/api/me").status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/me",
        "/api/violations",
        "/api/violations/1",
        "/api/evidence/PV-20261113-0001.jpg",
        "/api/review-options",
        "/api/events",
    ],
)
def test_dashboard_routes_need_a_login(client, anonymous, path):
    report(client)
    assert anonymous.get(path).status_code == 401


def test_login_must_be_json(anonymous):
    response = anonymous.post("/api/auth/login", data={"username": "ali", "password": PASSWORD})
    assert response.status_code == 415


# ------------------------------------------------------------------- reading


def test_list_newest_first_with_counts_and_filter(client):
    report(client, ref="ref-00000001")
    report(client, ref="ref-00000002")
    body = client.get("/api/violations").json()
    assert [v["code"] for v in body["items"]] == ["PV-20261113-0002", "PV-20261113-0001"]
    assert body["counts"] == {"Pending": 2, "Confirmed": 0, "Rejected": 0, "Action Taken": 0}
    assert len(client.get("/api/violations", params={"status": "Pending"}).json()["items"]) == 2
    assert client.get("/api/violations", params={"status": "Confirmed"}).json()["items"] == []
    assert client.get("/api/violations", params={"status": "Nonsense"}).status_code == 400


def test_paging(client):
    for i in range(3):
        report(client, ref=f"ref-0000000{i}")
    page = client.get("/api/violations", params={"limit": 2, "offset": 2}).json()["items"]
    assert [v["code"] for v in page] == ["PV-20261113-0001"]


def test_unknown_violation_is_404(client):
    assert client.get("/api/violations/999").status_code == 404


def test_evidence_route_only_serves_evidence_names(client):
    report(client)
    assert client.get("/api/evidence/PV-20261113-0001.jpg").content == PHOTO
    assert client.get("/api/evidence/PV-20261113-9999.jpg").status_code == 404
    assert client.get("/api/evidence/test.db").status_code == 404
    assert client.get("/api/evidence/..%2Ftest.db").status_code == 404
    assert client.get("/api/evidence/secret.key").status_code == 404


# ------------------------------------------------------------------- reviews


def test_confirm_then_action_taken_is_logged_with_the_officer(client):
    violation_id = report(client).json()["id"]
    assert client.get(f"/api/violations/{violation_id}").json()["allowed_decisions"] == [
        "Confirmed",
        "Rejected",
    ]

    confirmed = review(client, violation_id, "Confirmed", note="Blocking the ambulance bay")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "Confirmed"

    done = review(client, violation_id, "Action Taken", note="Challan issued")
    assert done.json()["status"] == "Action Taken"
    assert done.json()["allowed_decisions"] == []

    history = done.json()["reviews"]
    assert [r["decision"] for r in history] == ["Confirmed", "Action Taken"]
    assert history[0]["officer_name"] == "Ali Khan"
    assert history[0]["note"] == "Blocking the ambulance bay"
    assert history[0]["created_at"]


def test_each_review_records_who_made_it(app, client):
    violation_id = report(client).json()["id"]
    review(client, violation_id, "Confirmed")
    sara = TestClient(app)
    login(sara, username="sara")
    review(sara, violation_id, "Action Taken")
    names = [r["officer_name"] for r in client.get(f"/api/violations/{violation_id}").json()["reviews"]]
    assert names == ["Ali Khan", "Sara Shah"]


def test_rejection_needs_a_listed_reason(client):
    violation_id = report(client).json()["id"]
    assert review(client, violation_id, "Rejected").status_code == 400
    assert review(client, violation_id, "Rejected", reason="Because").status_code == 400
    assert review(client, violation_id, "Rejected", reason="Other").status_code == 400  # needs a note
    assert client.get(f"/api/violations/{violation_id}").json()["status"] == "Pending"

    ok = review(client, violation_id, "Rejected", reason="Not a vehicle")
    assert ok.status_code == 200
    assert ok.json()["status"] == "Rejected"
    assert ok.json()["reviews"][0]["reason"] == "Not a vehicle"
    assert review(client, violation_id, "Rejected", reason="Other", note="x").status_code == 400


def test_rejected_can_be_reopened(client):
    violation_id = report(client).json()["id"]
    review(client, violation_id, "Rejected", reason="Other", note="Looked like a cart")
    reopened = review(client, violation_id, "Reopened", note="Second look: it is a car")
    assert reopened.json()["status"] == "Pending"
    assert len(reopened.json()["reviews"]) == 2


@pytest.mark.parametrize("decision", ["Action Taken", "Reopened", "Deleted", ""])
def test_decisions_that_do_not_fit_the_status_are_refused(client, decision):
    violation_id = report(client).json()["id"]
    response = review(client, violation_id, decision)
    assert response.status_code == 400
    detail = client.get(f"/api/violations/{violation_id}").json()
    assert detail["status"] == "Pending" and detail["reviews"] == []


def test_action_taken_is_final(client):
    violation_id = report(client).json()["id"]
    review(client, violation_id, "Confirmed")
    review(client, violation_id, "Action Taken")
    for decision in ("Confirmed", "Rejected", "Reopened"):
        assert review(client, violation_id, decision, reason="Not a vehicle").status_code == 400


def test_review_needs_login_and_json(client, anonymous):
    violation_id = report(client).json()["id"]
    assert review(anonymous, violation_id, "Confirmed").status_code == 401
    form = client.post(f"/api/violations/{violation_id}/review", data={"decision": "Confirmed"})
    assert form.status_code == 415
    assert review(client, 999, "Confirmed").status_code == 404


def test_review_history_cannot_be_changed_or_deleted(client, settings):
    violation_id = report(client).json()["id"]
    review(client, violation_id, "Confirmed")
    conn = sqlite3.connect(settings.database_path)
    with pytest.raises(sqlite3.IntegrityError, match="add-only"):
        conn.execute("UPDATE reviews SET decision = 'Rejected'")
    with pytest.raises(sqlite3.IntegrityError, match="add-only"):
        conn.execute("DELETE FROM reviews")
    conn.close()
    assert len(client.get(f"/api/violations/{violation_id}").json()["reviews"]) == 1


def test_review_options(client):
    options = client.get("/api/review-options").json()
    assert options["statuses"] == ["Pending", "Confirmed", "Rejected", "Action Taken"]
    assert "Not a vehicle" in options["reject_reasons"]


# --------------------------------------------------------------- live events


def test_events_are_published_for_new_and_changed_violations(app, client):
    events = app.state.events
    violation_id = report(client).json()["id"]
    review(client, violation_id, "Confirmed")
    kinds = [(kind, data["status"]) for _, kind, data in events.since(0)]
    assert kinds == [("violation_created", "Pending"), ("violation_updated", "Confirmed")]
    assert events.since(events.last_id) == []


# ----------------------------------------------------------- dashboard pages


def test_dashboard_pages_fall_back_to_index(settings, tmp_path):
    site = tmp_path / "dist"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text("<html>dashboard</html>")
    (site / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "outside.txt").write_text("private")
    client = TestClient(create_app(replace(settings, dashboard_dir=site)))

    assert "dashboard" in client.get("/").text
    assert "dashboard" in client.get("/violations/3").text  # a page inside the dashboard
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert "private" not in client.get("/..%2Foutside.txt").text
    assert client.get("/api/nothing-here").status_code == 404


def test_missing_dashboard_build_explains_itself(anonymous):
    response = anonymous.get("/")
    assert response.status_code == 404
    assert "npm" in response.json()["detail"]


def test_health_reports_telegram_state(anonymous, settings):
    assert anonymous.get("/health").json() == {"status": "ok", "telegram_configured": True}
    blank = TestClient(create_app(replace(settings, telegram_chat_id="")))
    assert blank.get("/health").json()["telegram_configured"] is False


def test_relative_setting_paths_are_inside_the_project(monkeypatch, tmp_path):
    from api import config

    monkeypatch.chdir(tmp_path)  # start "the server" from some other folder
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.delenv("DASHBOARD_DIR", raising=False)
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "elsewhere"))
    loaded = config.load_settings()
    assert loaded.database_path == config.PROJECT_ROOT / "data/rahsaaf.db"
    assert loaded.dashboard_dir == config.PROJECT_ROOT / "dashboard/dist"
    assert loaded.evidence_dir == tmp_path / "elsewhere"  # absolute paths are kept


# -------------------------------------------------------------------- plates


def report_with_plate(client, text="LEA1234", confidence="0.93", ref="ref-00000001"):
    return client.post(
        "/internal/violations",
        data={
            "client_ref": ref,
            "camera_name": "Hospital gate",
            "plate_text": text,
            "plate_confidence": confidence,
            "started_at": "2026-11-13T17:24:29+00:00",
        },
        files={
            "photo": ("v.jpg", PHOTO, "image/jpeg"),
            "plate_photo": ("p.jpg", b"plate-crop-bytes", "image/jpeg"),
        },
    )


def test_plate_is_stored_shown_and_sent_in_the_alert(client, telegram):
    violation_id = report_with_plate(client).json()["id"]
    detail = client.get(f"/api/violations/{violation_id}").json()
    assert detail["plate_text"] == "LEA1234"
    assert detail["plate_confidence"] == 0.93
    assert detail["plate_source"] == "auto"
    assert detail["plate_url"] == "/api/evidence/PV-20261113-0001_plate.jpg"
    assert client.get(detail["plate_url"]).content == b"plate-crop-bytes"

    caption = telegram.calls[0]["body"]
    assert b"LEA1234" in caption
    assert b"read automatically, 93% sure" in caption


def test_plate_text_is_cleaned_and_checked(client):
    assert report_with_plate(client, text="lea-1234").status_code == 201
    assert client.get("/api/violations/1").json()["plate_text"] == "LEA1234"
    assert report_with_plate(client, text="X" * 15, ref="ref-00000002").status_code == 400
    assert report_with_plate(client, confidence="1.5", ref="ref-00000003").status_code == 400


def test_unread_plate_is_stored_as_none_but_keeps_its_picture(client, telegram):
    violation_id = report_with_plate(client, text="", confidence="").json()["id"]
    detail = client.get(f"/api/violations/{violation_id}").json()
    assert detail["plate_text"] is None
    assert detail["plate_source"] is None
    assert detail["plate_url"] is not None
    assert b"not readable, see photo" in telegram.calls[0]["body"]


def test_officer_can_correct_a_plate_and_it_is_logged(client):
    violation_id = report_with_plate(client, text="LEA1284").json()["id"]
    response = client.post(f"/api/violations/{violation_id}/plate", json={"plate_text": "lea 1234"})
    assert response.status_code == 200
    body = response.json()
    assert body["plate_text"] == "LEA1234"
    assert body["plate_source"] == "officer"
    assert body["plate_confidence"] is None
    assert body["status"] == "Pending"  # correcting a plate is not a decision

    entry = body["reviews"][-1]
    assert entry["decision"] == "Plate corrected"
    assert entry["note"] == "LEA1284 → LEA1234"
    assert entry["officer_name"] == "Ali Khan"


def test_officer_can_mark_a_plate_unreadable(client):
    violation_id = report_with_plate(client).json()["id"]
    body = client.post(f"/api/violations/{violation_id}/plate", json={"plate_text": ""}).json()
    assert body["plate_text"] is None
    assert body["reviews"][-1]["note"] == "LEA1234 → not readable"


def test_plate_correction_rules(client, anonymous):
    violation_id = report_with_plate(client).json()["id"]
    path = f"/api/violations/{violation_id}/plate"
    assert client.post(path, json={"plate_text": "LEA1234"}).status_code == 400  # no change
    assert client.post(path, json={"plate_text": "!"}).status_code == 400
    assert client.post(path, json={"plate_text": "ABCDEFGHIJKL"}).status_code == 400
    assert anonymous.post(path, json={"plate_text": "ABC123"}).status_code == 401
    assert client.post(path, data={"plate_text": "ABC123"}).status_code == 415
    assert client.post("/api/violations/999/plate", json={"plate_text": "ABC123"}).status_code == 404


def test_older_database_gains_the_plate_columns(tmp_path):
    import sqlite3

    from api.db import Database

    path = tmp_path / "old.db"
    Database(path)
    with sqlite3.connect(path) as conn:  # make it look like a pre-plate database
        for column in ("plate_confidence", "plate_file", "plate_source"):
            conn.execute(f"ALTER TABLE violations DROP COLUMN {column}")
    Database(path)
    with sqlite3.connect(path) as conn:
        names = {row[1] for row in conn.execute("PRAGMA table_info(violations)")}
    assert {"plate_confidence", "plate_file", "plate_source"} <= names


# ------------------------------------------------------- impact and analytics

IMPACT_PARTS = '{"flow_drop": 0.8, "queue": 0.6, "lane_blocked": 1.0, "queued_vehicles": 3, "baseline_ready": true}'


def report_full(client, ref, camera="Hospital gate", plate="", impact=None, level="", when="2026-11-13T17:24:29+00:00", lat="34.0151", lon="71.5249"):
    data = {
        "client_ref": ref,
        "camera_name": camera,
        "latitude": lat,
        "longitude": lon,
        "plate_text": plate,
        "started_at": when,
    }
    if impact is not None:
        data.update(impact_score=str(impact), impact_level=level, impact_parts=IMPACT_PARTS)
    response = client.post(
        "/internal/violations", data=data, files={"photo": ("v.jpg", PHOTO, "image/jpeg")}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def recent(hours_ago=0.0):
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def test_impact_is_stored_shown_and_put_in_the_alert(client, telegram):
    violation_id = report_full(client, "ref-00000001", impact=0.74, level="High")
    detail = client.get(f"/api/violations/{violation_id}").json()
    assert detail["impact"]["level"] == "High"
    assert detail["impact"]["score"] == 0.74
    assert detail["impact"]["queued_vehicles"] == 3
    assert "impact_parts" not in detail
    assert "Traffic impact:</b> 🔴 High".encode() in telegram.calls[0]["body"]


def test_violation_without_a_marked_lane_has_no_impact(client, telegram):
    violation_id = report_full(client, "ref-00000001")
    assert client.get(f"/api/violations/{violation_id}").json()["impact"] is None
    assert b"Traffic impact" not in telegram.calls[0]["body"]


def test_impact_only_ever_goes_up(client):
    violation_id = report_full(client, "ref-00000001", impact=0.2, level="Low")
    path = "/internal/violations/ref-00000001/impact"
    worse = {"impact_score": "0.65", "impact_level": "High", "impact_parts": IMPACT_PARTS}
    assert client.post(path, data=worse).status_code == 200
    assert client.get(f"/api/violations/{violation_id}").json()["impact"]["level"] == "High"
    # A later, calmer reading must not hide that it caused a jam.
    assert client.post(path, data={"impact_score": "0.1", "impact_level": "Low"}).status_code == 200
    assert client.get(f"/api/violations/{violation_id}").json()["impact"]["score"] == 0.65


@pytest.mark.parametrize(
    "data",
    [
        {"impact_score": "1.4", "impact_level": "High"},
        {"impact_score": "0.5", "impact_level": "Huge"},
        {"impact_score": "0.5", "impact_level": "High", "impact_parts": "not json"},
        {"impact_score": "0.5", "impact_level": "High", "impact_parts": "[1, 2]"},
    ],
)
def test_bad_impact_reports_are_rejected(client, data):
    report_full(client, "ref-00000001")
    assert client.post("/internal/violations/ref-00000001/impact", data=data).status_code == 400


def test_impact_update_for_unknown_violation_is_404(client):
    response = client.post(
        "/internal/violations/ref-unknown01/impact",
        data={"impact_score": "0.5", "impact_level": "Medium"},
    )
    assert response.status_code == 404


def test_queue_can_be_sorted_by_impact(client):
    report_full(client, "ref-00000001", impact=0.2, level="Low")
    report_full(client, "ref-00000002")  # no lane marked: unmeasured
    report_full(client, "ref-00000003", impact=0.9, level="High")
    report_full(client, "ref-00000004", impact=0.5, level="Medium")
    by_impact = client.get("/api/violations", params={"sort": "impact"}).json()["items"]
    assert [v["id"] for v in by_impact] == [3, 4, 1, 2]
    newest = client.get("/api/violations").json()["items"]
    assert [v["id"] for v in newest] == [4, 3, 2, 1]
    assert client.get("/api/violations", params={"sort": "random"}).status_code == 400


def test_detail_flags_a_plate_seen_before(client):
    first = report_full(client, "ref-00000001", plate="LEA1234")
    second = report_full(client, "ref-00000002", plate="LEA1234", camera="Saddar Road")
    other = report_full(client, "ref-00000003", plate="ABC123")
    assert client.get(f"/api/violations/{second}").json()["other_violations_for_plate"] == 1
    assert client.get(f"/api/violations/{other}").json()["other_violations_for_plate"] == 0
    # A rejected alert was not a violation, so it does not count against the plate.
    review(client, first, "Rejected", reason="Not a vehicle")
    assert client.get(f"/api/violations/{second}").json()["other_violations_for_plate"] == 0


def test_analytics_counts_hotspots_offenders_and_rejections(client):
    a = report_full(client, "ref-00000001", camera="Hospital gate", plate="LEA1234", impact=0.8, level="High", when=recent(1))
    report_full(client, "ref-00000002", camera="Hospital gate", plate="LEA1234", when=recent(2))
    report_full(client, "ref-00000003", camera="Hospital gate", plate="ABC123", when=recent(3))
    b = report_full(client, "ref-00000004", camera="Saddar Road", lat="34.0", lon="71.55", when=recent(4))
    old = report_full(client, "ref-00000005", camera="Saddar Road", when=recent(24 * 60))
    review(client, a, "Confirmed")
    review(client, b, "Rejected", reason="Not a vehicle")

    data = client.get("/api/analytics", params={"days": 30}).json()
    summary = data["summary"]
    assert summary["violations"] == 3  # the rejected one and the 60-day-old one are out
    assert summary["confirmed"] == 1 and summary["rejected"] == 1 and summary["pending"] == 2
    assert summary["rejected_share"] == 0.5  # 1 rejected of 2 judged
    assert summary["high_impact"] == 1
    assert summary["plates_read_share"] == 1.0

    spots = {s["camera_name"]: s for s in data["hotspots"]}
    assert data["hotspots"][0]["camera_name"] == "Hospital gate"  # most violations first
    assert spots["Hospital gate"]["violations"] == 3
    assert spots["Hospital gate"]["high_impact"] == 1
    assert spots["Hospital gate"]["latitude"] == 34.0151
    assert spots["Saddar Road"]["violations"] == 0 and spots["Saddar Road"]["rejected"] == 1
    assert spots["Saddar Road"]["busiest_hour"] is None

    assert [(o["plate_text"], o["violations"]) for o in data["repeat_offenders"]] == [("LEA1234", 2)]
    assert data["repeat_offenders"][0]["officer_checked"] is False
    assert data["reject_reasons"] == [{"reason": "Not a vehicle", "count": 1}]
    assert sum(data["by_hour"]) == 3 and len(data["by_hour"]) == 24
    assert len(data["by_day"]) == 14 and sum(d["count"] for d in data["by_day"]) == 3

    everything = client.get("/api/analytics", params={"days": 365}).json()
    assert everything["summary"]["violations"] == 4
    assert old


def test_analytics_on_an_empty_system(client):
    data = client.get("/api/analytics").json()
    assert data["summary"]["violations"] == 0
    assert data["summary"]["rejected_share"] is None  # "no data", not "0% wrong"
    assert data["summary"]["plates_read_share"] is None
    assert data["hotspots"] == [] and data["repeat_offenders"] == []


def test_reopened_rejection_no_longer_counts_as_a_rejection(client):
    violation_id = report_full(client, "ref-00000001", when=recent(1))
    review(client, violation_id, "Rejected", reason="Not a vehicle")
    review(client, violation_id, "Reopened")
    data = client.get("/api/analytics").json()
    assert data["reject_reasons"] == []
    assert data["summary"]["rejected"] == 0 and data["summary"]["violations"] == 1


def test_analytics_needs_a_login(anonymous):
    assert anonymous.get("/api/analytics").status_code == 401


# ------------------------------------------------------------ managing logins

NEW_PASSWORD = "another-long-password"


@pytest.fixture
def admin(app):
    app.state.db.create_officer("Head Office", "boss", auth.hash_password(PASSWORD), "admin")
    logged_in = TestClient(app)
    assert login(logged_in, "boss").status_code == 200
    return logged_in


def officer_id(app, username):
    return app.state.db.get_officer_by_username(username)["id"]


def test_ordinary_officer_cannot_manage_logins(client, app):
    assert client.get("/api/officers").status_code == 403
    new = {"name": "X Y", "username": "xyz", "password": NEW_PASSWORD}
    assert client.post("/api/officers", json=new).status_code == 403
    sara = officer_id(app, "sara")
    assert client.post(f"/api/officers/{sara}/active", json={"active": False}).status_code == 403
    assert client.post(f"/api/officers/{sara}/password", json={"password": NEW_PASSWORD}).status_code == 403


def test_login_management_needs_a_login(anonymous):
    assert anonymous.get("/api/officers").status_code == 401


def test_admin_adds_a_login_that_can_then_log_in(admin, app):
    reply = admin.post(
        "/api/officers", json={"name": "Bilal Ahmad", "username": "bilal", "password": NEW_PASSWORD}
    )
    assert reply.status_code == 201
    listed = {o["username"]: o for o in reply.json()["officers"]}
    assert listed["bilal"]["role"] == "officer"
    assert "password_hash" not in listed["bilal"]
    assert login(TestClient(app), "bilal", NEW_PASSWORD).status_code == 200
    assert reply.json()["log"][0]["action"] == "created as officer"


@pytest.mark.parametrize(
    "change",
    [{"username": "ali"}, {"username": "ALI"}, {"username": "a b"}, {"password": "short"}, {"role": "root"}, {"name": ""}],
)
def test_bad_new_logins_are_refused(admin, change):
    body = {"name": "New Person", "username": "newone", "password": NEW_PASSWORD, "role": "officer", **change}
    assert admin.post("/api/officers", json=body).status_code in (409, 422)


def test_disabling_a_login_ends_its_session_at_once(admin, client, app):
    ali = officer_id(app, "ali")
    assert client.get("/api/me").status_code == 200
    assert admin.post(f"/api/officers/{ali}/active", json={"active": False}).status_code == 200
    assert client.get("/api/me").status_code == 401
    assert login(TestClient(app), "ali").status_code == 401
    assert admin.post(f"/api/officers/{ali}/active", json={"active": True}).status_code == 200
    assert login(TestClient(app), "ali").status_code == 200


def test_admin_cannot_disable_self_or_the_last_admin(admin, app):
    boss = officer_id(app, "boss")
    assert admin.post(f"/api/officers/{boss}/active", json={"active": False}).status_code == 400
    assert app.state.db.get_officer(boss)["active"] == 1


def test_password_reset_ends_old_sessions(admin, client, app):
    ali = officer_id(app, "ali")
    assert admin.post(f"/api/officers/{ali}/password", json={"password": NEW_PASSWORD}).status_code == 200
    assert client.get("/api/me").status_code == 401
    assert login(TestClient(app), "ali").status_code == 401
    assert login(TestClient(app), "ali", NEW_PASSWORD).status_code == 200


def test_unknown_login_is_404(admin):
    assert admin.post("/api/officers/9999/active", json={"active": False}).status_code == 404


def test_officer_changes_own_password(client, app):
    other_device = TestClient(app)
    assert login(other_device).status_code == 200

    wrong = {"current_password": "not-the-password", "new_password": NEW_PASSWORD}
    assert client.post("/api/me/password", json=wrong).status_code == 400
    short = {"current_password": PASSWORD, "new_password": "short"}
    assert client.post("/api/me/password", json=short).status_code == 422

    good = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert client.post("/api/me/password", json=good).status_code == 200
    assert client.get("/api/me").status_code == 200  # this device stays logged in
    assert other_device.get("/api/me").status_code == 401  # the other does not
    assert login(TestClient(app), "ali").status_code == 401
    assert login(TestClient(app), "ali", NEW_PASSWORD).status_code == 200


def test_login_changes_log_is_add_only(admin, app):
    ali = officer_id(app, "ali")
    admin.post(f"/api/officers/{ali}/active", json={"active": False})
    with sqlite3.connect(app.state.settings.database_path) as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM officer_log")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE officer_log SET action = 'x'")


def test_security_headers(anonymous, settings):
    reply = anonymous.get("/health")
    assert reply.headers["x-content-type-options"] == "nosniff"
    assert reply.headers["x-frame-options"] == "DENY"
    assert "strict-transport-security" not in reply.headers

    secure = TestClient(create_app(replace(settings, cookie_secure=True)), base_url="https://testserver")
    assert "strict-transport-security" in secure.get("/health").headers
    secure.app.state.db.create_officer("Ali Khan", "ali2", auth.hash_password(PASSWORD), "officer")
    cookie = login(secure, "ali2").headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie


# --- the box of each alert, and learning from "Not a vehicle" rejections ---


def test_box_is_stored_with_the_alert(client, anonymous):
    created = report(anonymous, box="0.68,0.46,0.80,0.65").json()
    assert client.get(f"/api/violations/{created['id']}").json()["box"] == "0.6800,0.4600,0.8000,0.6500"


def test_alert_without_a_box_is_still_accepted(client, anonymous):
    created = report(anonymous).json()
    assert client.get(f"/api/violations/{created['id']}").json()["box"] is None


@pytest.mark.parametrize("box", ["1,2,3", "a,b,c,d", "0.5,0.5,0.4,0.9", "0.1,0.1,1.2,0.9", "-0.1,0,1,1"])
def test_bad_box_is_refused(anonymous, box):
    assert report(anonymous, box=box).status_code == 400


def test_only_standing_not_a_vehicle_rejections_are_listed(app, client, anonymous):
    db = app.state.db
    booth = report(anonymous, ref="ref-0000000a", box="0.68,0.46,0.80,0.65").json()["id"]
    traffic = report(anonymous, ref="ref-0000000b", box="0.10,0.10,0.20,0.20").json()["id"]
    reopened = report(anonymous, ref="ref-0000000c", box="0.30,0.30,0.40,0.40").json()["id"]
    no_box = report(anonymous, ref="ref-0000000d").json()["id"]
    report(anonymous, ref="ref-0000000e", box="0.50,0.50,0.60,0.60")  # never reviewed

    assert review(client, booth, "Rejected", "Not a vehicle").status_code == 200
    assert review(client, traffic, "Rejected", "Vehicle was not parked (traffic or signal)").status_code == 200
    assert review(client, reopened, "Rejected", "Not a vehicle").status_code == 200
    assert review(client, reopened, "Reopened").status_code == 200
    assert review(client, no_box, "Rejected", "Not a vehicle").status_code == 200

    rows = db.not_a_vehicle_boxes("Hospital gate")
    assert [row["box"] for row in rows] == ["0.6800,0.4600,0.8000,0.6500"]
    assert db.not_a_vehicle_boxes("Another camera") == []

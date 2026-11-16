from dataclasses import replace

from api import alerts
from api.alerts import build_caption, format_duration, map_link, send_violation_alert
from api.db import Database
from tests.conftest import TOKEN

VIOLATION = {
    "code": "PV-20261113-0001",
    "camera_name": "Hospital gate",
    "zone_name": "North kerb",
    "vehicle_class": "car",
    "plate_text": None,
    "parked_seconds": 125,
    "started_at": "2026-11-13T17:24:29+00:00",
    "latitude": 34.0151,
    "longitude": 71.5249,
}


def make_violation(settings, with_photo=True, position=True):
    db = Database(settings.database_path)
    camera = db.upsert_camera(
        "Hospital gate", 34.0151 if position else None, 71.5249 if position else None
    )
    violation, _ = db.create_violation(
        {
            "client_ref": "ref-00000001",
            "camera_id": camera,
            "zone_name": "North kerb",
            "vehicle_class": "car",
            "parked_seconds": 125,
            "started_at": "2026-11-13T17:24:29+00:00",
        }
    )
    if with_photo:
        settings.evidence_dir.mkdir(parents=True, exist_ok=True)
        (settings.evidence_dir / "p.jpg").write_bytes(b"\xff\xd8 fake jpeg \xff\xd9")
        db.set_violation_files(violation["id"], photo_file="p.jpg")
    return db, violation["id"]


def no_sleep(_seconds):
    pass


def test_format_duration():
    assert format_duration(45) == "45 s"
    assert format_duration(125) == "2 min 5 s"
    assert format_duration(None) == "unknown"


def test_map_link():
    assert map_link(34.0151, 71.5249) == "https://www.google.com/maps?q=34.015100,71.524900"


def test_caption_has_everything_an_officer_needs(settings):
    caption = build_caption(VIOLATION, settings)
    assert "PV-20261113-0001" in caption
    assert "car" in caption
    assert "Hospital gate (North kerb)" in caption
    assert "2 min 5 s" in caption
    assert "not read" in caption  # no plate yet
    assert "10:24:29 PM" in caption  # 17:24 UTC shown in Pakistan time
    assert "maps?q=34.015100,71.524900" in caption


def test_caption_escapes_names(settings):
    caption = build_caption({**VIOLATION, "camera_name": "<b>Gate</b> & Co"}, settings)
    assert "&lt;b&gt;Gate&lt;/b&gt; &amp; Co" in caption


def test_caption_without_position_has_no_map_link(settings):
    caption = build_caption({**VIOLATION, "latitude": None, "longitude": None}, settings)
    assert "maps" not in caption


def test_alert_sends_photo_then_map_pin(settings, telegram):
    db, violation_id = make_violation(settings)
    assert send_violation_alert(db, settings, violation_id, sleep=no_sleep)

    assert telegram.methods() == ["sendPhoto", "sendLocation"]
    photo_call = telegram.calls[0]
    assert b"fake jpeg" in photo_call["body"]
    assert b"PV-" in photo_call["body"]
    assert b'name="chat_id"\r\n\r\n42' in photo_call["body"]

    log = db.list_alerts(violation_id)
    assert len(log) == 1
    assert log[0]["success"] == 1 and log[0]["attempts"] == 1 and log[0]["error"] is None


def test_alert_without_photo_falls_back_to_text(settings, telegram):
    db, violation_id = make_violation(settings, with_photo=False)
    assert send_violation_alert(db, settings, violation_id, sleep=no_sleep)
    assert telegram.methods() == ["sendMessage", "sendLocation"]


def test_no_map_pin_without_position(settings, telegram):
    db, violation_id = make_violation(settings, position=False)
    assert send_violation_alert(db, settings, violation_id, sleep=no_sleep)
    assert telegram.methods() == ["sendPhoto"]


def test_map_pin_can_be_switched_off(settings, telegram):
    db, violation_id = make_violation(settings)
    quiet = replace(settings, telegram_send_location=False)
    assert send_violation_alert(db, quiet, violation_id, sleep=no_sleep)
    assert telegram.methods() == ["sendPhoto"]


def test_alert_is_retried_after_a_failure(settings, telegram):
    db, violation_id = make_violation(settings)
    telegram.fail_next = 1
    waits = []
    assert send_violation_alert(db, settings, violation_id, sleep=waits.append)

    assert telegram.methods() == ["sendPhoto", "sendPhoto", "sendLocation"]
    assert waits == [alerts.RETRY_DELAYS[0]]
    assert db.list_alerts(violation_id)[0]["attempts"] == 2


def test_alert_that_keeps_failing_is_logged_as_failed(settings, telegram):
    db, violation_id = make_violation(settings)
    telegram.fail_next = 99
    assert not send_violation_alert(db, settings, violation_id, sleep=no_sleep)

    log = db.list_alerts(violation_id)[0]
    assert log["success"] == 0
    assert log["attempts"] == 3
    assert "HTTP 500" in log["error"]
    assert "sendLocation" not in telegram.methods()


def test_unconfigured_telegram_is_logged_not_sent(settings, telegram):
    db, violation_id = make_violation(settings)
    blank = replace(settings, telegram_bot_token="")
    assert not send_violation_alert(db, blank, violation_id, sleep=no_sleep)
    assert telegram.calls == []
    assert "not configured" in db.list_alerts(violation_id)[0]["error"]


def test_token_never_appears_in_the_error_log(settings):
    db, violation_id = make_violation(settings)
    dead = replace(settings, telegram_api_base="http://127.0.0.1:9")  # nothing listens here
    assert not send_violation_alert(db, dead, violation_id, sleep=no_sleep)
    error = db.list_alerts(violation_id)[0]["error"]
    assert "network error" in error
    assert TOKEN not in error


def test_wrong_token_is_reported(settings, telegram):
    db, violation_id = make_violation(settings)
    wrong = replace(settings, telegram_bot_token="999:WRONG")
    assert not send_violation_alert(db, wrong, violation_id, sleep=no_sleep)
    assert "401" in db.list_alerts(violation_id)[0]["error"]

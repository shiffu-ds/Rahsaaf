import time

import httpx

from worker.reporter import ViolationReporter


class Server:
    """Stands in for the API: records requests and can fail the first few."""

    def __init__(self, failures=0, status_when_failing=503, reject=False):
        self.requests = []
        self.failures = failures
        self.status_when_failing = status_when_failing
        self.reject = reject

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.url.path, request.read(), dict(request.headers)))
        if self.reject:
            return httpx.Response(400, json={"detail": "bad"})
        if self.failures > 0:
            self.failures -= 1
            if self.status_when_failing is None:
                raise httpx.ConnectError("refused")
            return httpx.Response(self.status_when_failing)
        return httpx.Response(201, json={})


def make(server, **kwargs):
    return ViolationReporter(
        "http://api",
        camera_name="Hospital gate",
        latitude=34.0151,
        longitude=71.5249,
        retry_delays=(0.01, 0.01, 0.01),
        transport=httpx.MockTransport(server),
        **kwargs,
    )


def start(reporter, photo, ref="ref-00000001"):
    reporter.violation_started(
        ref,
        photo=photo,
        zone_id="zone1",
        zone_name="North kerb",
        vehicle_class="car",
        confidence=0.8,
        parked_seconds=120.0,
        started_at="2026-11-13T17:24:29+00:00",
    )


def photo_file(tmp_path):
    path = tmp_path / "violation_1.jpg"
    path.write_bytes(b"jpeg-bytes")
    return path


def test_started_report_carries_details_photo_and_position(tmp_path):
    server = Server()
    reporter = make(server)
    start(reporter, photo_file(tmp_path))
    reporter.close()

    path, body, _ = server.requests[0]
    assert path == "/internal/violations"
    for expected in (b"ref-00000001", b"Hospital gate", b"34.0151", b"71.5249", b"North kerb", b"jpeg-bytes"):
        assert expected in body
    assert reporter.sent == 1 and reporter.failed == 0


def test_reports_are_delivered_in_order(tmp_path):
    server = Server()
    reporter = make(server)
    clip = tmp_path / "violation_1.mp4"
    clip.write_bytes(b"mp4-bytes")
    start(reporter, photo_file(tmp_path))
    reporter.clip_ready("ref-00000001", clip)
    reporter.violation_ended("ref-00000001", 300.0, "2026-11-13T17:29:29+00:00")
    reporter.close()

    assert [r[0] for r in server.requests] == [
        "/internal/violations",
        "/internal/violations/ref-00000001/clip",
        "/internal/violations/ref-00000001/ended",
    ]
    assert b"mp4-bytes" in server.requests[1][1]


def test_report_is_retried_when_the_server_is_down(tmp_path):
    server = Server(failures=2, status_when_failing=None)  # connection refused twice
    reporter = make(server)
    start(reporter, photo_file(tmp_path))
    reporter.close()
    assert len(server.requests) == 3
    assert reporter.sent == 1


def test_report_is_retried_on_a_server_error(tmp_path):
    server = Server(failures=1, status_when_failing=503)
    reporter = make(server)
    start(reporter, photo_file(tmp_path))
    reporter.close()
    assert len(server.requests) == 2
    assert reporter.sent == 1


def test_rejected_report_is_not_retried(tmp_path):
    server = Server(reject=True)
    reporter = make(server)
    start(reporter, photo_file(tmp_path))
    reporter.close()
    assert len(server.requests) == 1
    assert reporter.failed == 1


def test_report_is_given_up_after_all_retries(tmp_path):
    server = Server(failures=99)
    reporter = make(server)
    start(reporter, photo_file(tmp_path))
    reporter.close()
    assert len(server.requests) == 4  # first try + 3 retries
    assert reporter.failed == 1


def test_internal_key_is_sent_when_set(tmp_path):
    server = Server()
    reporter = make(server, internal_key="s3cret-key")
    start(reporter, photo_file(tmp_path))
    reporter.close()
    assert server.requests[0][2]["x-internal-key"] == "s3cret-key"


def test_reporting_does_not_block_the_caller(tmp_path):
    def slow(request):
        time.sleep(0.3)
        return httpx.Response(201, json={})

    reporter = ViolationReporter("http://api", "Gate", transport=httpx.MockTransport(slow))
    began = time.monotonic()
    start(reporter, photo_file(tmp_path))
    assert time.monotonic() - began < 0.1
    reporter.close()
    assert reporter.sent == 1


def test_plate_and_its_picture_travel_with_the_report(tmp_path):
    server = Server()
    reporter = make(server)
    plate = tmp_path / "violation_1_plate.jpg"
    plate.write_bytes(b"plate-bytes")
    reporter.violation_started(
        "ref-00000001",
        photo=photo_file(tmp_path),
        zone_id="zone1",
        zone_name="North kerb",
        vehicle_class="car",
        confidence=0.8,
        parked_seconds=120.0,
        started_at="2026-11-13T17:24:29+00:00",
        plate_text="LEA1234",
        plate_confidence=0.93,
        plate_photo=plate,
    )
    reporter.close()
    body = server.requests[0][1]
    for expected in (b"LEA1234", b"0.93", b"plate-bytes", b"jpeg-bytes"):
        assert expected in body


def test_unread_plate_sends_no_plate_text(tmp_path):
    server = Server()
    reporter = make(server)
    start(reporter, photo_file(tmp_path))
    reporter.close()
    assert b"plate_text" not in server.requests[0][1]


def test_impact_travels_with_the_report_and_as_an_update(tmp_path):
    from worker.congestion import Impact

    impact = Impact(0.74, "High", 0.8, 0.6, 1.0, 3, True)
    server = Server()
    reporter = make(server)
    reporter.violation_started(
        "ref-00000001",
        photo=photo_file(tmp_path),
        zone_id="zone1",
        zone_name="North kerb",
        vehicle_class="car",
        confidence=0.8,
        parked_seconds=120.0,
        started_at="2026-11-13T17:24:29+00:00",
        impact=impact,
    )
    reporter.impact_changed("ref-00000001", impact)
    reporter.close()
    assert b"0.74" in server.requests[0][1] and b"High" in server.requests[0][1]
    assert server.requests[1][0] == "/internal/violations/ref-00000001/impact"
    assert b"queued_vehicles" in server.requests[1][1]

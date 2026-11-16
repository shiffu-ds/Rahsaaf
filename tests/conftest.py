"""Shared test helpers: a stand-in Telegram server and an API test client."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from api.config import Settings

TOKEN = "123456:TEST-TOKEN"


class FakeTelegram:
    """Answers like the Telegram Bot API and remembers what it was sent."""

    def __init__(self):
        self.calls: list[dict] = []
        self.fail_next = 0  # answer this many requests with an error first
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.calls.append(
                    {"path": self.path, "body": body, "type": self.headers.get("Content-Type", "")}
                )
                if outer.fail_next > 0:
                    outer.fail_next -= 1
                    status, payload = 500, {"ok": False, "description": "Internal Server Error"}
                elif not self.path.startswith(f"/bot{TOKEN}/"):
                    status, payload = 401, {"ok": False, "description": "Unauthorized"}
                else:
                    status, payload = 200, {"ok": True, "result": {}}
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def methods(self) -> list[str]:
        return [call["path"].rsplit("/", 1)[-1] for call in self.calls]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def telegram():
    fake = FakeTelegram()
    yield fake
    fake.close()


@pytest.fixture
def settings(tmp_path, telegram):
    return Settings(
        database_path=tmp_path / "test.db",
        evidence_dir=tmp_path / "evidence",
        dashboard_dir=tmp_path / "dashboard-not-built",
        telegram_bot_token=TOKEN,
        telegram_chat_id="42",
        telegram_api_base=telegram.url,
    )

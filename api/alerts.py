"""Sends violation alerts to Telegram.

An alert is a photo with a caption (vehicle, place, time, map link), optionally
followed by a map pin. Sending is retried a few times, and every outcome is
written to the alert log so a failed alert is never silently lost.
"""
from __future__ import annotations

import html
import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from api.config import Settings
from api.db import Database

logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO level, and a Telegram URL contains the
# bot token. Keep it out of the logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

CHANNEL = "telegram"
RETRY_DELAYS = (1.0, 3.0)  # waits between attempts; three attempts in total


def map_link(latitude: float, longitude: float) -> str:
    return f"https://www.google.com/maps?q={latitude:.6f},{longitude:.6f}"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes} min {secs} s" if minutes else f"{secs} s"


def format_time(iso_time: str, timezone_name: str) -> str:
    local = datetime.fromisoformat(iso_time).astimezone(ZoneInfo(timezone_name))
    return local.strftime("%d %b %Y, %I:%M:%S %p")


def plate_line(violation: dict) -> str:
    """The plate as shown in an alert, saying how far it can be trusted."""
    plate = violation.get("plate_text")
    if not plate:
        return "not readable, see photo"
    plate = html.escape(plate)
    if violation.get("plate_source") == "officer":
        return f"{plate} (entered by an officer)"
    confidence = violation.get("plate_confidence")
    # Never show 100%: no automatic read is certain.
    sure = f", {min(99, round(confidence * 100))}% sure" if confidence is not None else ""
    return f"{plate} (read automatically{sure}; check against the photo)"


def build_caption(violation: dict, settings: Settings) -> str:
    """Alert text, in Telegram's HTML format."""
    esc = html.escape
    place = esc(violation["camera_name"])
    if violation.get("zone_name"):
        place += f" ({esc(violation['zone_name'])})"

    lines = [
        f"🚨 <b>Illegal parking</b> · {esc(violation['code'])}",
        f"<b>Vehicle:</b> {esc(violation.get('vehicle_class') or 'vehicle')}",
        f"<b>Plate:</b> {plate_line(violation)}",
        f"<b>Place:</b> {place}",
        f"<b>Parked for:</b> {format_duration(violation.get('parked_seconds'))}",
        f"<b>Time:</b> {format_time(violation['started_at'], settings.timezone)}",
    ]
    if violation.get("impact_level"):
        marks = {"High": "🔴", "Medium": "🟠", "Low": "🟢"}
        level = violation["impact_level"]
        lines.insert(1, f"<b>Traffic impact:</b> {marks.get(level, '')} {esc(level)}")
    if violation.get("latitude") is not None and violation.get("longitude") is not None:
        link = map_link(violation["latitude"], violation["longitude"])
        lines.append(f'<a href="{link}">Open location in Google Maps</a>')
    return "\n".join(lines)


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, settings: Settings, timeout: float = 15.0):
        self._base = f"{settings.telegram_api_base}/bot{settings.telegram_bot_token}"
        self._chat_id = settings.telegram_chat_id
        self._timeout = timeout

    def send_photo(self, photo: Path, caption: str) -> None:
        with photo.open("rb") as handle:
            self._call(
                "sendPhoto",
                data={"chat_id": self._chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": (photo.name, handle, "image/jpeg")},
            )

    def send_message(self, text: str) -> None:
        self._call(
            "sendMessage",
            data={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
        )

    def send_location(self, latitude: float, longitude: float) -> None:
        self._call(
            "sendLocation",
            data={"chat_id": self._chat_id, "latitude": latitude, "longitude": longitude},
        )

    def _call(self, method: str, data: dict, files: dict | None = None) -> None:
        try:
            response = httpx.post(
                f"{self._base}/{method}", data=data, files=files, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            # Never include the URL in the message: it contains the bot token.
            raise TelegramError(f"{method}: network error ({type(exc).__name__})") from None
        if response.status_code != 200:
            try:
                detail = response.json().get("description", "")
            except ValueError:
                detail = ""
            raise TelegramError(f"{method}: HTTP {response.status_code} {detail}".strip())


def send_violation_alert(
    db: Database,
    settings: Settings,
    violation_id: int,
    sleep=time.sleep,
) -> bool:
    """Send the alert for one violation and log the outcome. True on success."""
    violation = db.get_violation(violation_id)
    if violation is None:
        return False

    if not settings.telegram_configured:
        db.log_alert(violation_id, CHANNEL, False, 0, "Telegram is not configured")
        logger.warning("Alert for %s not sent: Telegram is not configured", violation["code"])
        return False

    client = TelegramClient(settings)
    caption = build_caption(violation, settings)
    photo = (
        settings.evidence_dir / violation["photo_file"] if violation.get("photo_file") else None
    )

    error = None
    attempts = 0
    for delay in (0.0, *RETRY_DELAYS):
        if delay:
            sleep(delay)
        attempts += 1
        try:
            if photo is not None and photo.exists():
                client.send_photo(photo, caption)
            else:
                client.send_message(caption)
            error = None
            break
        except TelegramError as exc:
            error = str(exc)
            logger.warning("Alert attempt %d for %s failed: %s", attempts, violation["code"], error)

    db.log_alert(violation_id, CHANNEL, error is None, attempts, error)
    if error is not None:
        return False

    # The map pin is a convenience. If it fails the alert has still arrived,
    # with a map link in its caption, so this is not retried.
    has_position = violation.get("latitude") is not None and violation.get("longitude") is not None
    if settings.telegram_send_location and has_position:
        try:
            client.send_location(violation["latitude"], violation["longitude"])
        except TelegramError as exc:
            logger.warning("Map pin for %s failed: %s", violation["code"], exc)
    return True

"""Settings, read from the environment (and a .env file if one exists)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


#: The project folder (the one holding api/, worker/ and dashboard/).
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _project_path(value: str) -> Path:
    """A path from the settings; a relative one is inside the project folder.

    Without this, relative paths would depend on which folder the server was
    started from, and starting it from anywhere else would silently create a
    second, empty database and fail to find the dashboard.
    """
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path("data/rahsaaf.db")
    evidence_dir: Path = Path("data/evidence")
    timezone: str = "Asia/Karachi"
    public_base_url: str = "http://127.0.0.1:8000"
    internal_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_send_location: bool = True
    #: Signs login sessions. Empty means: generate one and keep it in a file.
    secret_key: str = ""
    session_hours: float = 12.0
    #: Send the login cookie only over HTTPS. Turn on when served over HTTPS.
    cookie_secure: bool = False
    dashboard_dir: Path = Path("dashboard/dist")
    #: Only changed in tests, to point at a stand-in server.
    telegram_api_base: str = "https://api.telegram.org"

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    env = os.environ.get
    return Settings(
        database_path=_project_path(env("DATABASE_PATH", "data/rahsaaf.db")),
        evidence_dir=_project_path(env("EVIDENCE_DIR", "data/evidence")),
        timezone=env("TIMEZONE", "Asia/Karachi"),
        public_base_url=env("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        internal_api_key=env("INTERNAL_API_KEY", ""),
        telegram_bot_token=env("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=env("TELEGRAM_CHAT_ID", ""),
        telegram_send_location=env("TELEGRAM_SEND_LOCATION", "true").lower() != "false",
        secret_key=env("SECRET_KEY", ""),
        session_hours=float(env("SESSION_HOURS", "12")),
        cookie_secure=env("COOKIE_SECURE", "false").lower() == "true",
        dashboard_dir=_project_path(env("DASHBOARD_DIR", "dashboard/dist")),
        telegram_api_base=env("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
    )

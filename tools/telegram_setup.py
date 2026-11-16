"""Find your Telegram chat ID and send a test alert.

    uv run python tools/telegram_setup.py          # list chats that messaged the bot
    uv run python tools/telegram_setup.py --test   # send a test message

Before running: put TELEGRAM_BOT_TOKEN in .env, then open your bot in Telegram
and press Start (or add it to a group and send any message there).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.alerts import TelegramClient, TelegramError  # noqa: E402
from api.config import load_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--test", action="store_true", help="send a test message")
    args = parser.parse_args()

    settings = load_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is empty. Copy .env.example to .env and fill it in.")

    if args.test:
        if not settings.telegram_chat_id:
            raise SystemExit("TELEGRAM_CHAT_ID is empty. Run without --test to find it.")
        try:
            TelegramClient(settings).send_message("✅ RahSaaf test message. Alerts will arrive here.")
        except TelegramError as exc:
            raise SystemExit(f"Could not send: {exc}")
        print("Test message sent. Check Telegram.")
        return

    url = f"{settings.telegram_api_base}/bot{settings.telegram_bot_token}/getUpdates"
    try:
        response = httpx.get(url, timeout=15)
    except httpx.HTTPError as exc:
        raise SystemExit(f"Could not reach Telegram ({type(exc).__name__}).")
    if response.status_code == 401:
        raise SystemExit("Telegram rejected the token. Check TELEGRAM_BOT_TOKEN.")
    if response.status_code != 200:
        raise SystemExit(f"Telegram answered HTTP {response.status_code}.")

    chats = {}
    for update in response.json().get("result", []):
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("first_name") or chat.get("username") or ""

    if not chats:
        print("No chats found. Open your bot in Telegram, press Start, send a message, and run this again.")
        return
    print("Chats that have messaged the bot:\n")
    for chat_id, name in chats.items():
        print(f"  TELEGRAM_CHAT_ID={chat_id}    ({name})")
    print("\nPut the right line in .env, then run with --test.")


if __name__ == "__main__":
    main()

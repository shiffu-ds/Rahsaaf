"""Create a dashboard login, or reset its password.

    uv run python tools/create_officer.py --name "Ali Khan" --username ali
    uv run python tools/create_officer.py --username ali --reset-password
    uv run python tools/create_officer.py --list

You are asked to type the password; it is not shown and not stored anywhere
except as a one-way hash in the database.
"""
from __future__ import annotations

import argparse
import getpass
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import auth  # noqa: E402
from api.config import load_settings  # noqa: E402
from api.db import Database  # noqa: E402


def ask_password() -> str:
    while True:
        first = getpass.getpass(f"Password (at least {auth.MIN_PASSWORD_LENGTH} characters): ")
        if len(first) < auth.MIN_PASSWORD_LENGTH:
            print("Too short.")
            continue
        if first != getpass.getpass("Type it again: "):
            print("The two did not match.")
            continue
        return first


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--name", help="full name, shown in the audit log")
    parser.add_argument("--username")
    parser.add_argument("--role", choices=["officer", "admin"], default="officer")
    parser.add_argument("--reset-password", action="store_true")
    parser.add_argument("--list", action="store_true", help="list existing logins")
    args = parser.parse_args()

    db = Database(load_settings().database_path)

    if args.list:
        for officer in db.list_officers():
            state = "" if officer["active"] else "  (disabled)"
            print(f"{officer['username']:<20} {officer['role']:<8} {officer['name']}{state}")
        return

    if not args.username or not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", args.username):
        raise SystemExit("--username is required: 3-32 letters, digits, dot, dash or underscore.")

    if args.reset_password:
        if db.get_officer_by_username(args.username) is None:
            raise SystemExit(f"No login named {args.username!r}.")
        db.set_officer_password(args.username, auth.hash_password(ask_password()))
        print(f"Password changed for {args.username}.")
        return

    if not args.name:
        raise SystemExit("--name is required when creating a login.")
    if db.get_officer_by_username(args.username) is not None:
        raise SystemExit(f"{args.username!r} already exists. Use --reset-password to change its password.")
    try:
        db.create_officer(args.name.strip(), args.username, auth.hash_password(ask_password()), args.role)
    except sqlite3.IntegrityError:
        raise SystemExit(f"{args.username!r} already exists.")
    print(f"Created {args.role} login {args.username!r}.")


if __name__ == "__main__":
    main()

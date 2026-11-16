"""Start the RahSaaf server.

    uv run python tools/serve.py          this computer only, plain HTTP
    uv run python tools/serve.py --lan    other devices on the same network, HTTPS

With --lan the dashboard is reachable from phones and computers on the same
Wi-Fi or office network, so everything is encrypted:

* a certificate is made once and kept in data/tls/ (the key never leaves this
  computer),
* the login cookie is only ever sent over HTTPS,
* camera workers on other computers are still refused unless INTERNAL_API_KEY
  is set in .env.

The certificate is self-signed: no outside authority vouches for it, so each
browser shows a warning the first time. Compare the fingerprint the browser
shows with the one printed here before accepting it. For use over the
internet, put a real certificate in front instead (for example Caddy).
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.config import PROJECT_ROOT  # noqa: E402


def lan_address() -> str:
    """This computer's address on the local network (no data is sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def ensure_certificate(folder: Path, address: str) -> tuple[Path, Path]:
    """A certificate valid for this computer's addresses; made if missing."""
    cert, key, made_for = folder / "cert.pem", folder / "key.pem", folder / "address.txt"
    if cert.exists() and key.exists() and made_for.exists() and made_for.read_text().strip() == address:
        return cert, key
    if shutil.which("openssl") is None:
        raise SystemExit("openssl is needed to make the certificate. Install it and try again.")
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    for old in (cert, key):
        old.unlink(missing_ok=True)
    previous = os.umask(0o077)  # the key is readable by this user only
    try:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key), "-out", str(cert), "-days", "365",
                "-subj", "/CN=RahSaaf",
                "-addext", f"subjectAltName=DNS:localhost,IP:127.0.0.1,IP:{address}",
            ],
            check=True,
            capture_output=True,
        )
    finally:
        os.umask(previous)
    made_for.write_text(address + "\n")
    print(f"Made a new certificate for {address} in {folder}/ (valid for one year).")
    return cert, key


def fingerprint(cert: Path) -> str:
    result = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip().split("=", 1)[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--lan", action="store_true", help="serve the local network, over HTTPS")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)  # show the address even when output is redirected
    load_dotenv(PROJECT_ROOT / ".env")
    port = args.port or int(os.environ.get("API_PORT", "8000"))

    if not args.lan:
        print(f"Dashboard: http://127.0.0.1:{port}   (this computer only)")
        uvicorn.run("api.main:app", host="127.0.0.1", port=port, log_level="warning")
        return

    address = lan_address()
    cert, key = ensure_certificate(PROJECT_ROOT / "data" / "tls", address)
    os.environ["COOKIE_SECURE"] = "true"
    if "127.0.0.1" in os.environ.get("PUBLIC_BASE_URL", "127.0.0.1"):
        # Links in alerts must work on the officer's phone, not just here.
        os.environ["PUBLIC_BASE_URL"] = f"https://{address}:{port}"

    print(f"Dashboard:   https://{address}:{port}   (devices on this network)")
    print(f"             https://127.0.0.1:{port}   (this computer)")
    print(f"Certificate fingerprint (SHA-256), to compare with the browser's warning:\n  {fingerprint(cert)}")
    print("Camera worker on this computer:")
    print(f"  uv run python -m worker.run_live SOURCE --zones ZONES --api https://127.0.0.1:{port} --ca data/tls/cert.pem")
    if not os.environ.get("INTERNAL_API_KEY"):
        print("Camera workers on other computers are refused (INTERNAL_API_KEY is not set).")
    uvicorn.run(
        "api.main:app", host="0.0.0.0", port=port, log_level="warning",
        ssl_certfile=str(cert), ssl_keyfile=str(key),
    )


if __name__ == "__main__":
    main()

"""Makes evidence clips playable in a web browser.

The camera worker writes clips with OpenCV's built-in MPEG-4 encoder, which
browsers refuse to play. FFmpeg re-encodes them as H.264. If FFmpeg is not
installed the clip is left as it is: it still downloads and plays in a media
player, it just will not play inside the dashboard.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def make_browser_playable(path: Path) -> bool:
    """Re-encode ``path`` in place as H.264. True if it was converted."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None or not path.exists():
        return False
    temp = path.with_name(f"{path.stem}.h264.tmp.mp4")
    command = [
        ffmpeg, "-y", "-v", "error",
        "-i", str(path),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "26",
        "-movflags", "+faststart",  # lets playback start before the file has fully loaded
        "-an",
        str(temp),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=120)
        if result.returncode == 0 and temp.exists() and temp.stat().st_size > 0:
            temp.replace(path)
            return True
        logger.warning("Could not convert %s: %s", path.name, result.stderr.decode()[-200:])
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Could not convert %s: %s", path.name, type(exc).__name__)
    temp.unlink(missing_ok=True)
    return False

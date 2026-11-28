"""Bounded opt-in secondary extractor for one playback metadata lookup."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from pathlib import Path

from mariana.models import MediaSource, canonical_uri


def retryable(error: BaseException) -> bool:
    if isinstance(error, ModuleNotFoundError):
        return error.name == "yt_dlp" or (error.name or "").startswith("yt_dlp.")
    text = str(error).casefold()
    denied = ("429", "403", "401", "quota", "too many requests", "rate limit", "sign in",
              "log in", "login", "cookie", "private", "geo", "country", "region", "age-restrict",
              "age restrict", "age limit", "age verification", "confirm your age", "not a bot", "drm",
              "certificate", "ssl", "forbidden", "authoriz", "members-only", "members only", "restricted",
              "copyright", "not available in", "unavailable in", "rights", "subscriber", "premium",
              "payment", "paywall", "licens", "451", "407")
    if any(token in text for token in denied):
        return False
    return isinstance(error, (TimeoutError, ConnectionError)) or any(token in text for token in (
        "timed out", "timeout", "connection reset", "connection refused", "remote end closed",
        "temporarily unavailable", "temporary failure", "unable to extract", "format is not available",
        "502", "503", "504"))


def external_info(url: str, selector: str, profile: str | None) -> dict | None:
    name = "yt-dlp"
    variable = "MARIANA_YTDLP_BINARY"
    if not os.environ.get(variable):
        name = "youtube-dl"
        variable = "MARIANA_YOUTUBE_DL_BINARY"
    value = os.environ.get(variable)
    if not value:
        return None
    if name == "youtube-dl":
        # youtube-dl has no browser-profile option. Preserve the selected
        # account on the in-process retry rather than switching to anonymous.
        if profile:
            return None
        url = canonical_uri(MediaSource.YOUTUBE, url)
        if not re.fullmatch(r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}", url):
            return None
        if selector.startswith('bestvideo[protocol=https][vcodec~='):
            selector = "/".join(f"bestvideo[protocol=https][vcodec^={codec}]" for codec in ("avc1", "av01", "vp9", "vp09"))
        else:
            selector = selector.replace("bestvideo*", "bestvideo")
    binary = Path(value).expanduser()
    if not binary.is_absolute() or not binary.is_file() or (os.name == "nt" and binary.suffix.lower() != ".exe"):
        raise ValueError(f"{variable} must point to an installed {name} executable.")
    args = [str(binary), "--ignore-config", "--no-playlist", "--skip-download", "--dump-single-json",
            "--no-geo-bypass", "--socket-timeout", "7", "--retries", "0", "--format", selector]
    if name == "yt-dlp":
        args += ["--extractor-retries", "0"]
    if profile:
        args += ["--cookies-from-browser", profile]
    args += ["--", url]
    try:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        raise ValueError(f"The configured fallback {name} executable could not start.") from None
    # Extractor JSON contains transient transport credentials. Keep it only in
    # memory and stop an oversized result before communicating it to callers.
    limit = 8 * 1024 * 1024
    data = bytearray()
    def read() -> None:
        with process.stdout as stream:
            while chunk := stream.read(65536):
                data.extend(chunk)
                if len(data) > limit:
                    process.kill()
                    break
    reader = threading.Thread(target=read, name="mariana-extractor-output", daemon=True)
    reader.start()
    try:
        process.wait(timeout=18)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise TimeoutError(f"Fallback {name} timed out.") from None
    finally:
        reader.join(timeout=2)
    if reader.is_alive() or process.returncode or len(data) > limit:
        raise ValueError(f"Fallback {name} could not resolve this recording.")
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        result = None
    if not isinstance(result, dict) or result.get("_type", "video") != "video":
        raise ValueError(f"Fallback {name} returned an unsupported recording.")
    if name == "youtube-dl":
        age = result.get("age_limit")
        if (result.get("availability") not in (None, "public") or result.get("is_private")
                or result.get("has_drm") or result.get("is_live") or result.get("live_status") == "is_live"
                or (age is not None and (type(age) not in (int, float) or age >= 18))
                or result.get("id") != url.rsplit("=", 1)[1]):
            raise ValueError("The legacy extractor did not return a matching unrestricted recording.")
    return result

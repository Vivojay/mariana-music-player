"""Console pixel previews: artwork/thumbnail rendering without a desktop host.

Local-first, bounded, read-only. Supports ASCII (always), Kitty graphics,
iTerm2 inline images, and Sixel (foot/wezterm/mlterm/contour and friends)
when the terminal advertises them, plus saving a frame to disk for any
other terminal.
"""

from __future__ import annotations

import base64
import io
import os
import subprocess

ASCII_SHADES = " .:-=+*#%@"

_SIXEL_TERMS = ("foot", "wezterm", "mlterm", "contour", "multiplexer")


def terminal_graphics() -> str:
    override = (os.environ.get("MARIANA_SIXEL") or "").casefold()
    term = (os.environ.get("TERM") or "").casefold()
    program = (os.environ.get("TERM_PROGRAM") or "").casefold()
    if "kitty" in term or "kitty" in program:
        return "kitty"
    if program.startswith("iterm") or os.environ.get("ITERM_SESSION_ID"):
        return "iterm"
    if override == "1":
        return "sixel"
    if override == "0" or os.environ.get("WT_SESSION"):
        return "none"
    if any(marker in term or marker in program for marker in _SIXEL_TERMS):
        return "sixel"
    if "xterm" in term or "tmux" in term:
        return "none"
    return "none"


def pil_to_ascii(image, *, width: int = 64) -> str:
    gray = image.convert("L")
    aspect = gray.height / max(1, gray.width)
    height = max(4, min(40, round(width * aspect * 0.55)))
    small = gray.resize((max(16, min(120, width)), height))
    pixels = list(small.tobytes())
    lines: list[str] = []
    for row in range(small.height):
        line = "".join(
            ASCII_SHADES[min(len(ASCII_SHADES) - 1, pixels[row * small.width + col] * len(ASCII_SHADES) // 256)]
            for col in range(small.width)
        )
        lines.append(line)
    border = "+" + "-" * len(lines[0]) + "+"
    return "\n".join([border, *[f"|{line}|" for line in lines], border])


def image_bytes_to_ascii(data: bytes, *, width: int = 64) -> str:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return pil_to_ascii(image, width=width)


def kitty_chunk(data: bytes) -> str:
    payload = base64.b85encode(data).decode("ascii") if False else base64.b64encode(data).decode("ascii")
    # Kitty graphics protocol: ESC _ G f=100,a=T; <payload> ESC \
    return f"\x1b_Gf=100,a=T;{payload}\x1b\\"


def iterm_chunk(data: bytes, *, width: int = 64) -> str:
    payload = base64.b64encode(data).decode("ascii")
    return f"\x1b]1337;File=inline=1;width={width};preserveAspectRatio=1:{payload}\x07"


def sixel_chunk(data: bytes, *, max_width: int = 800, colors: int = 16) -> str:
    """Encode PNG bytes as Sixel (pure Python + PIL, no native dependency).

    Bounded: downscales to max_width, quantizes to `colors` (4-256), emits
    6-row sixel bands. Output starts with DCS-q and ends with ST.
    """
    from PIL import Image

    width = max(16, min(1600, int(max_width)))
    count = max(4, min(256, int(colors)))
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        rgb = image.convert("RGB")
        if rgb.width > width:
            rgb = rgb.resize((width, round(rgb.height * width / rgb.width)))
        quantized = rgb.quantize(colors=count, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG)
        palette = quantized.getpalette() or []
        pixels = quantized.load()
        w, h = quantized.size
        parts = ["\x1bPq", f'"1;1;{w};{h}']
        used: set[int] = set()
        for y in range(0, h, 6):
            for x in range(w):
                try:
                    used.add(int(pixels[x, min(y, h - 1)]))
                except (TypeError, ValueError, IndexError):
                    continue
        for index in sorted(used):
            base = index * 3
            try:
                red, green, blue = palette[base], palette[base + 1], palette[base + 2]
            except (IndexError, TypeError):
                red = green = blue = 0
            parts.append(f"#{index};2;{round(red * 100 / 255)};{round(green * 100 / 255)};{round(blue * 100 / 255)}")
        for top in range(0, h, 6):
            for index in sorted(used):
                parts.append(f"#{index}")
                run_char: str | None = None
                run_len = 0

                def flush() -> None:
                    nonlocal run_char, run_len
                    if run_char is not None:
                        parts.append(f"!{run_len}{run_char}" if run_len > 3 else run_char * run_len)
                        run_char, run_len = None, 0

                for x in range(w):
                    bits = 0
                    for bit in range(6):
                        y = top + bit
                        if y >= h:
                            continue
                        try:
                            if int(pixels[x, y]) == index:
                                bits |= 1 << bit
                        except (TypeError, ValueError, IndexError):
                            continue
                    char = chr(63 + bits)
                    if char == run_char:
                        run_len += 1
                    else:
                        flush()
                        run_char, run_len = char, 1
                flush()
            parts.append("-")
        parts.append("\x1b\\")
        return "".join(parts)


def extract_frame_png(
    *, source: str, at_seconds: float = 0.0, ffmpeg_bin: str | None = None, timeout: float = 15
) -> bytes:
    """Extract one PNG frame via ffmpeg (bounded, no playback)."""
    binary = ffmpeg_bin or "ffmpeg"
    command = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-ss",
        f"{max(0.0, float(at_seconds)):.3f}",
        "-i",
        source,
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "pipe:1",
    ]
    try:
        process = subprocess.run(command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"Frame extraction failed: {error}") from error
    if process.returncode != 0 or not process.stdout:
        detail = (process.stderr or b"").decode("utf-8", errors="replace").strip()[:200]
        raise RuntimeError(f"Frame extraction failed{(': ' + detail) if detail else ''}")
    if len(process.stdout) > 8 * 1024 * 1024:
        raise RuntimeError("Extracted frame is too large for console preview")
    return process.stdout

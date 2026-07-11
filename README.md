# Mariana Music Player v0.6.2

Mariana is a command-line music player for 64-bit Windows. It supports local audio, VLC-backed streams and radio,
YouTube search/playback/downloads, podcasts, and Shazam-powered song recognition and lyrics.

## Supported environment

- Windows 10 or Windows 11, 64-bit
- CPython 3.12.x, 64-bit
- [VLC media player 3.x](https://www.videolan.org/vlc/), 64-bit
- [FFmpeg and FFprobe](https://ffmpeg.org/download.html) available on `PATH`
- [Deno](https://deno.com/) or [Node.js 22+](https://nodejs.org/) available on `PATH` for reliable YouTube extraction

Python and VLC must use the same architecture. FFmpeg is needed for media conversion, metadata extraction, downloads,
and sampling online audio for recognition; local-only playback can still start without it.

## Installation

Clone the repository and enter it:

```powershell
git clone https://github.com/Vivojay/mariana-music-player.git
Set-Location mariana-music-player
```

Create and activate a Python 3.12 virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the fully pinned runtime:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

Run Mariana:

```powershell
python main.py
```

The first run asks for local music folders and optionally offers the Mariana sample collection. The sample download can
be declined without limiting normal operation.

## Development checks

Install the locked development environment:

```powershell
python -m pip install -r requirements-dev.txt
python -m compileall -q .
python -m ruff check --select E9,F63,F7,F82 .
python -m pytest -q
python -m pip_audit -r requirements.txt
```

`requirements.in` contains direct runtime dependencies. Regenerate the lock after an intentional dependency update:

```powershell
python -m piptools compile --output-file requirements.txt requirements.in
python -m piptools compile --output-file requirements-dev.txt requirements-dev.in
```

## Compatibility notes

- Existing Mariana command syntax is preserved; see [help.md](help.md).
- Reddit live sessions/RPAN no longer exists. Its former command aliases remain recognized and display a retirement
  message instead of failing.
- YouTube operations use yt-dlp and may occasionally require a yt-dlp update when YouTube changes its delivery system.
- Online failures should not prevent local playback from starting.

## Troubleshooting

- **VLC not found:** install 64-bit VLC in its standard directory or set `vlc path` in `settings/settings.yml`.
- **FFmpeg/FFprobe warning:** add the directory containing `ffmpeg.exe` and `ffprobe.exe` to the system `PATH`, then open
  a new terminal.
- **JavaScript runtime warning:** install Deno or Node.js 22+ and add it to `PATH`; yt-dlp uses it for YouTube's current
  JavaScript challenges.
- **No audio device:** confirm Windows can see an output device before starting Mariana.
- **Dependency mismatch:** recreate `.venv` and install from `requirements.txt`; do not mix the old 2022 dependency set
  with the modern lock.

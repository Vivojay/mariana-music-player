# Building and running Mariana releases

## Local browser release

`Mariana-Web.pyz` contains the portable web player, scripts, artwork and practice audio. From any working directory, run the following on Windows with Python 3.9 or newer. Use `python3` on Linux or macOS. The player opens in the default browser.

```powershell
python 'D:\C DOWNLOADS\Mariana-Web.pyz' --view flow
```

The Windows ZIP includes `Open-Mariana.cmd`, `WindowsWeb.cs`, the same portable release, and its license. Extract the whole ZIP to a writable folder and double-click `Open-Mariana.cmd`. On a Windows installation with the .NET Framework compiler and compression libraries, first launch builds `Mariana-Web.exe` there. Subsequent launches can use that executable by itself. If compilation is unavailable the launcher tries Python on PATH. After replacing the kit contents, use `Open-Mariana.cmd --build` to regenerate the executable. Windows compiler support is exercised by the Windows preview workflow.

```powershell
$dir = 'D:\C DOWNLOADS\Mariana-Web'
Expand-Archive -LiteralPath 'D:\C DOWNLOADS\Mariana-Web-Windows.zip' -DestinationPath $dir -Force
& "$dir\Open-Mariana.cmd" --build
if ($LASTEXITCODE -eq 0) { & "$dir\Mariana-Web.exe" --view flow }
```

The Python zipapp, Windows launcher and PyInstaller browser executable use the same default origin, `http://127.0.0.1:8767/`. Keep the same host, port and browser profile to retain local storage across launches. Choose `--view console`, `--view flow` or `--view voice`, add `--no-open` to suppress opening a tab, or use `--port 8768` to pick another port. A new port creates a separate browser origin. Close the server with Ctrl+C. Local files, the built-in tone bank, effects and the practice duet can run without a network connection. Streams, external catalogs and provider account services need connectivity and any required provider credentials.

The self-contained web artifacts serve static browser features. The native account and room bridge requires the Python dev server, native dependencies and an eligible local origin. To use it, run the following in a checkout.

```powershell
.\.venv\Scripts\python.exe tools/build_web_player.py --serve --view flow --open
```

## Build, verify and host

The build command regenerates the self-contained archive, the Windows kit and a ZIP whose root contains `index.html`. Generated files and checksums appear in `build/portable`. Copy the static ZIP contents to an HTTPS host. The service worker and several browser capture APIs need HTTPS or a loopback origin.

```sh
python tools/package_web_release.py
python tools/check_web_release.py build/portable/Mariana-Web.pyz
```

To freeze one browser executable for the machine performing the build, use the project's Python 3.12 environment with `requirements-dev.txt` installed.

```sh
python tools/build_web_player.py
python -m PyInstaller --onefile --clean --noconfirm --name Mariana-Web --distpath build/native --add-data "build/web-player:web-player" packaging/web/portable_web.py
```

Verify it with `python tools/check_web_release.py build/native/Mariana-Web` (use `Mariana-Web.exe` on Windows). This starts the executable from another directory and checks Flow's launch URL, manifest and script MIME types, health, cache revalidation, and local bridge availability. To build the native playback CLI and TUI on the same host, run `python -m PyInstaller --clean --noconfirm --distpath build/native mariana-cli.spec`. Running `python tools/archive_native_preview.py` then validates both entry points and packages them together; `mariana-cli tui` opens the TUI. Platform-specific FFmpeg, FFprobe and audio output must be available to the full native player.

## Docker

Build the web image at the repository root. Its final stage runs an unprivileged nginx server on port 8080.

```sh
docker build -t mariana-web .
docker run --rm --read-only --tmpfs /tmp --cap-drop=ALL -p 127.0.0.1:8767:8080 mariana-web
```

Open `http://127.0.0.1:8767/?view=flow` and request `/healthz` to check readiness. Public deployments require an HTTPS endpoint. OAuth providers also require a registered redirect URI matching the chosen origin. Set the public Spotify or Snapchat client ID at build time using `--build-arg MARIANA_SPOTIFY_WEB_CLIENT_ID=...` or `--build-arg MARIANA_SNAPCHAT_WEB_CLIENT_ID=...`. Values shipped to the browser are public. A configured conference host can be selected with `--build-arg MARIANA_JITSI_ORIGIN=https://your-meeting-host`.

To run the Python CLI or TUI in a container, use the CLI image. It includes FFmpeg, FFprobe, Chromaprint and PortAudio, with state owned by a non-root user in `/data`. Mount a music folder at `/music` and add that container path to your library. Keep the named volume across image updates.

```sh
docker build -f Dockerfile.cli -t mariana-cli .
docker run --rm -it -v mariana-data:/data mariana-cli tui
```

On a Linux host with ALSA, audio output or live mic input also needs access to the host's audio device and its group. Add `--device /dev/snd --group-add "$(stat -c %g /dev/snd/controlC0)"` before the image name, adjusting the device name to match the host. Docker Desktop on Windows and macOS does not expose the host soundcard through that Linux device path. Use the native player for hardware audio on those platforms. Browser sound comes from the user's browser, regardless of where the web container runs.

## Electron Lite

A separate preview build packages the browser workspace with Electron and leaves the Python backend and native integrations in the full desktop distribution. Run `npm ci --ignore-scripts` and `npm run pack:lite`, or use the **Mariana portable and native previews** workflow. Application staging was verified. The distributables still need installation and playback testing on their targets. See [Studio follow-up](STUDIO_NEXT.md#build-the-electron-lite-variant).

## Distribution status

| Deliverable | How to produce it | Verification and availability |
| --- | --- | --- |
| Portable web player, Flow and Windows build kit | `tools/package_web_release.py` | ZIP/PYZ generation and loopback HTTP checks were exercised on Linux. The native Windows C# compile and run step is included in the preview workflow. |
| GNU/Linux x86-64 browser player | Freeze `packaging/web/portable_web.py` with its generated assets | A real executable served the packaged player to QtWebEngine Chromium 83. The Flow command tests loaded a wavetable, selected choir FX, listed the current profile and decoded the 28.8-second stereo Twinkle arrangement. The active media element advanced during playback. Physical speaker output was unavailable in the test. The local preview was built with glibc 2.41. Older distributions should use the Python archive or rebuild natively. |
| Native Linux local-studio CLI/TUI preview | `Mariana-Studio-linux-x86_64-preview.tar.gz` (separate download). Extract the entire archive and run `./mariana-cli --tui` from its program directory. | The frozen binary started outside the repository with genuine PortAudio and ALSA, played Twinkle to the ALSA null output, and opened its real TUI. Tested on Debian 13.7 x86-64 with glibc 2.41. Install FFmpeg and FFprobe on PATH. Physical sound and compatibility with other distributions are unverified. |
| Full native CLI/TUI and host-native web binary | **Mariana portable and native previews** workflow | Manual jobs for Windows x64, Linux x64 and the macOS runner's architecture. Each uploads its archives and SHA-256 without publishing. Native CLI runtime acceptance and cross-OS testing are pending for this update. |
| Electron desktop installers | Existing **Signed desktop release** workflow | Existing Windows NSIS, macOS DMG/ZIP for Intel and Apple silicon, Linux x64 AppImage. The release owner supplies a production version and tag, configured signing/notarization, managed-tool artifacts and the workflow's publication confirmation. This feature patch does not create a public release. |
| Android, Wear OS, iOS/iPadOS, watchOS | Existing **Mariana web and mobile preview builds** workflow | Android/Wear debug APKs and unsigned bundles, Apple simulator archives. Device testing and signed App Store / TestFlight / Play deliverables remain open. |
| Web and CLI containers | `Dockerfile` and `Dockerfile.cli` | Build-and-run checks are included in the preview workflow. A Docker daemon was unavailable on the development host. |

Sources and existing target instructions are in [the mobile guide](WEB_MOBILE_WATCH.md), [the studio guide](STUDIO_SURFACES.md), [the signed release workflow](../.github/workflows/release.yml) and [the portable workflow](../.github/workflows/portable-previews.yml).

The native Linux local-studio preview includes its matching source, build information and third-party notices. The preview uses some dependency versions outside the project lock. The tested package covers offline playback and studio commands. yt-dlp/yt-dlp-ejs, credential keyring, third-party plug-in hosting, cloud or speech services, and release signing are outside its verified distribution. A separately installed extractor, fpcalc, rsgain or Node runtime is a host dependency when its feature is used. Consult the archive's own readme for exact build scope.

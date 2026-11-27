# Mariana studio follow-up

For the latest paired Flow controls, restored Electron Home and terminal-style Console, see [native command coverage](CLI_FLOW_COVERAGE.md).

## Windows development and the Linux preview

Apply this source update on top of the Studio Workbench in the existing Windows checkout. The earlier Linux x86-64 preview archive is a standalone Linux build of the earlier workbench. It belongs outside the Windows checkout. On Linux, extract the entire archive and launch `./mariana-cli --tui` from the extracted program directory. Apply this follow-up to a source checkout to use its new commands.

## Browser library and native commands

Open FLOW and select **Library** on the workspace rail. **Import files** picks one or more recordings. **Import folder** uses the browser's folder picker where supported. Search by name, filter Audio or Video, then choose **Play** or **Queue**. Imports stay in the active browser profile. Play queue removal keeps the imported file. Removing the library entry keeps a copy available to an existing queue entry until that queue entry is removed. When database storage is unavailable, new imports are usable until the tab closes.

| Browser command | Where it runs |
| --- | --- |
| `library list` or `library search harbor` | Standalone browser, including Console and FLOW |
| `library play 1` or `library queue 1` | Standalone browser's stable local library numbering |
| `web session flow` or `web session console` | On the native Mariana command prompt. It opens a private, loopback-only invitation for the requested browser view. |
| `native` | Standalone browser shortcut to paste a native pairing invitation |
| `similar 1 --mode audio` | Native CLI, TUI, desktop terminal, or a paired browser command |

The paired workspace can search titles and indexed tags from the same numbered library as the CLI. Leave **Show my library and collections in this tab** unchecked when you only want the command console. Native commands run in the same native process. Use `web session flow --trust --share-output` for session approval with browser output, or approve once using **as** at the first review. Use `web help` at the paired terminal for browser-side actions. The browser library buttons use those same approvals. The standalone website has its own transport and account support. Native devices, data, shell integrations and Python models require native pairing or a native app. Libraries do not synchronize across browser origins and native listener profiles.

Workspace rail destinations are **Library**, **Discover**, **Studio**, **Rooms**, and **Settings**. Playback controls remain visible across FLOW destinations. **Commands** or **Ctrl+K** opens the command entry. The **Studio** destination contains DJ, sound design, karaoke, microphone tools and Strudel. The **Discover** destination holds podcast, audiobook and culture catalogs.

## Feature and acceptance status

| Area | Ships in this update | Verification still needed |
| --- | --- | --- |
| Similar media | Local fingerprints and file signatures, tag ranking, bounded acoustic analysis with reasons and profile-local storage. The Flow and Console follow-up adds browsing and playback of matches in paired Flow. [Similarity commands](MEDIA_SIMILARITY.md) | Similarity quality across a diverse labeled catalog, melody and visual models. |
| Audio effects and VST/AU | Built-in live rack adds bitcrush. An explicit install command verifies a vendor ZIP and keeps it in the active profile. Optional Pedalboard renders files through loaded VST3 or macOS AU components. [Effects, package and host setup](SOUND_DESIGN.md) | Vendor binary acceptance, live inserts and VST2. |
| ReplayGain, karaoke and stems | Same-name rsgain results handled independently while retaining album gain. Duet timing, singer selection, stem alignment, decode, mix and playback gates exercised. [Audio acceptance](AUDIO_ACCEPTANCE.md) | True rsgain on the user's machine, Demucs inference on real tracks, hosted separation and listening tests. |
| Speech and lyric drafts | Native whisper.cpp and optional Deepgram Nova-3 produce timestamped JSON or VTT. The hosted option supports language and anonymous speaker annotations. FLOW imports drafts and seeks by timestamp. [Speech](LIVE_SPEECH.md) · [Karaoke evidence](KARAOKE.md) | Actual model inference and service credentials. Automatic separation of simultaneous sung voices and performance-grade lyric alignment require independent evaluation. |
| Pictures | Native and browser video default for supported local files; browser picture controls and real-time effects, optional local YOLO11/12 ONNX boxes in the standalone window. [Video setup and filter modes](VIDEO_PLAYBACK.md) | OS and codec matrix testing, physical picture/audio synchronization, calibrated accessibility trials and real YOLO checkpoints. |
| DJ | Browser deck workstation with synchronized scales, decoded waveform scopes, overview seeks, mixer meters, library loading, hot cues, loops and master recording. [Browser DJ](PORTABLE_DJ.md) | Four decks, automatic beatgrid sync, advanced controllers and other Mixxx functions. Native `dj mixxx` opens an installed Mixxx. |
| Strudel | Project commands and expanded offline preview in FLOW and Console. Optional build of the pinned upstream browser engine, isolated in an iframe; explicit online editor also available. [Strudel surfaces](STRUDEL_SURFACES.md) | Upstream engine bundle, actual sample banks and mobile browser runtime acceptance. |
| Packaging | Standalone portable web build plus a lightweight Electron wrapper that carries browser assets without the frozen native backend. | Installer build and launch on each target, signed releases and physical-device tests. |

## Build the Electron Lite variant

The source recipe produces a separate desktop shell for the portable workspace. It uses the system browser for private native pairing invitations. For the CLI-backed integrated Electron terminal, continue to build the full desktop app. The Lite shell's application payload excludes Python, native audio models, vendor plugins and node-pty. An Electron distribution still includes Chromium, Node and Electron platform libraries.

From the repository root, with Node and Python available:

```powershell
npm ci --ignore-scripts
npm run pack:lite
```

Resulting output goes to `build/electron-lite-release`. Use `node tools/package_electron_lite.mjs --stage-only` to check exactly what the recipe stages and its raw app payload size without fetching the Electron runtime. The preview workflow has separate jobs for Windows, macOS and Linux. It does not publish installers or modify the full Electron release workflow. [Electron scheme API](https://www.electronjs.org/docs/latest/api/protocol)

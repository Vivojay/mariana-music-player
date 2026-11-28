# Strudel on Mariana

| Surface | Available in this patch | Acceptance still needed |
| --- | --- | --- |
| Local website, PWA Console and Flow | Profile-scoped named projects with revisions, autosaved draft, UTF-8 exchange, offline WAV previews and queue. The optional locked Strudel engine adds live coding and full WAV rendering. The online editor is also available on explicit request. | Bundle build and real advanced output with upstream npm dependencies installed |
| Android and iOS phone shells | Named projects, bundled editor, import, copy, offline preview and queue. Share WAV uses Mariana’s existing native file handoff. The installed mobile shells use the offline renderer. | Installed-device audio, picker, background behavior and OS share targets |
| PowerShell, Bash, native CLI and TUI | Named revisioned projects and UTF-8 exchange. `strudel render NAME new.wav` uses the same oscillator implementation as the phone and web, with Node.js 20+ on PATH. | Native Windows and macOS playback |
| Electron | Toolbar and terminal entry points open the project editor. A separate sandboxed window loads the pinned Strudel REPL and Web Audio packages. Save a project before rendering its revision into native playback. A dedicated in-memory session has its own permissions and storage. | Electron development and packaged listening tests with npm dependencies installed |
| Wear OS and watchOS | No dedicated Strudel editor or render command. | On-watch composition, Strudel rendering and device tests |

## Try the local website

From the repository directory run `python tools/build_web_player.py --serve --port 8767 --view flow --open`. Open **Strudel patterns** and choose **Render preview**, **Add to queue**, or **Download WAV**. Console and Flow use the same projects and draft for the current listener profile. A pattern edit clears its old preview.

| Command | Result |
| --- | --- |
| `strudel` | Open and focus the source editor. |
| `strudel new "Late Night"` | Create and open a named project from the starter. |
| `strudel list`, `strudel show "Late Night"`, `strudel save "Late Night"` | List projects, open a revision for editing, or save the open draft as the next revision. Save detects a newer revision from another tab. |
| `strudel import`, `strudel export` | Choose a UTF-8 file to put into the draft, or download the active source. |
| `strudel delete "Late Night" --yes` | Delete the selected saved project and keep its source in the editor if open. |
| `strudel render`, `strudel play`, `strudel queue` | Use the built-in offline oscillator preview, then download, play, or queue its WAV. |
| `strudel live`, `strudel stop` | Open the locally installed Strudel editor or stop and close it. Press Play inside the editor to start the audio. |
| `strudel render full`, `strudel play full`, `strudel queue full` | Use the locally installed upstream Strudel engine to produce a bounded stereo WAV. |
| `strudel live online` | Open the upstream editor in a frame with the current source in its URL fragment. This gives the upstream page access to the draft. Use source you intend to load at strudel.cc. |

Build the optional full browser engine from the pinned Electron dependency lock. Run these from the repository directory. The portable packager picks up the same compiled assets on the next build.

```powershell
npm ci --ignore-scripts
node tools/bundle_strudel_web.mjs
python tools/build_web_player.py --serve --view flow --open
```

Try `note("<c4 eb4 g4>*2").s("sawtooth").lpf(800).room(.4)` in **Live editor**. The local frame has a separate opaque origin. It receives only the requested draft and preview length. The live editor and renderer evaluate Strudel source as code within that frame, so run source you trust. Stock online sample maps require access to their allowed upstream origins. Use `strudel live online` as the setup-free way to open the upstream editor on a connected browser.

## Try the CLI, TUI and Electron

Inside the native Mariana prompt, run these commands in order. The export creates a new file and preserves earlier exports. Quote paths containing spaces.

```text
strudel new Study
strudel render Study "study-preview.wav"
strudel export Study "study.js"
strudel show Study
```

For a round trip, edit the source in the web player, download it, and run `strudel import Study 1 "mariana-pattern.js" 8` in native Mariana. Replace 1 with the project's current revision if it has changed. The web draft is local to its browser or phone. Exchange source files to move between devices.

In a desktop development checkout, install the locked Node dependencies with `npm ci`, then run `npm run dev` after setting up Mariana’s Python backend. Click **Strudel** or enter `strudel open` at the Electron terminal. Open **Study**, edit, save, then select **Render & play**. The Electron project uses a 48 kHz offline render and forwards the resulting WAV to Mariana. To check a production build, run `npm run build` and confirm the inputs produced `dist/strudel.html` and `dist-electron/strudelPreload.cjs`.

## Portable synth support

The built-in renderer accepts `setcps(0.5)`, a `note("c4 eb4 g4 ~")` sequence, or a `stack(...)` with up to four layers. Use `.s()` to select sine, triangle, square, or sawtooth, plus `.gain()`, `.rev()`, `.fast()`, `.slow()`, and single-pole `.lpf()` and `.hpf()`. Add retriggers with `c4*4` or pauses with `~`. Up to 64 slots and 16 retriggers per slot are supported. Formats beyond this subset can use the locally built full engine, the upstream web editor, or the Electron editor.

WAV exports from the built-in renderer are 16-bit mono PCM at 22,050 Hz and 1–60 seconds. The renderer parses source as data. Engine modules, MIDI/OSC, shared jam synchronization, device-specific audio behavior and separately cached sample packs have independent support and release requirements. [Strudel offline guide](https://strudel.cc/learn/pwa/)

## Distribution

Electron and the optional browser engine use `@strudel/repl` and `@strudel/webaudio` 1.3.0 from the same dependency lock. This checkout’s browser preview does not ship their compiled bundle. Upstream identifies its license as AGPL-3.0. Mariana’s package metadata declares AGPL-3.0-or-later. Before distributing compiled Electron builds or hosting a full-engine web build, include the applicable license notices and matching source through the release process. The portable oscillator implementation is included as readable Mariana source. [Strudel integration and licensing](https://strudel.cc/technical-manual/project-start/)

## Verification

```powershell
node --test tests/web_strudel.test.mjs
python -m pytest tests/test_strudel_portable.py tests/test_strudel_projects.py
npm test -- desktop/StrudelPanel.test.tsx desktop/strudelRuntime.test.ts desktop/strudelRenderLifecycle.test.ts
```

The Node tests check A4 frequency, the silent rest, distinct waveform output, retriggers, filter output, complete input validation and cancellation. Python tests invoke the actual Node renderer and decode its PCM output, including collision protection. The Electron tests exercise the save revision and renderer protocol with test doubles. Confirm sample-bank availability and audible output separately in a real desktop build.

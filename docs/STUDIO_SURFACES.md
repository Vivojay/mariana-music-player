# Start Mariana and test the studios

See [portable downloads, Docker and native builds](PORTABLE_RELEASES.md) for standalone launchers, checksums and release status.

Mariana has two playback sessions you can run on one computer. The Python session supplies the CLI, full-screen TUI and Electron terminal. The portable player has its own queue, storage, Console and Flow views. Switching between Console and Flow preserves the portable player's current playback. Launching Electron starts another native session. Phones package the portable interface. Watches have purpose-built companion controls.

## Windows development laptop

Start from the checkout that contains the update. These examples assume the repo’s existing Python 3.12 virtual environment.

```powershell
Set-Location -LiteralPath 'D:\Vivo Jay\projs\mariana-music-player' -ErrorAction Stop
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe' -ErrorAction Stop).Path
```

| To test | Run from the repository root | First thing to check |
| --- | --- | --- |
| Native CLI | `& $python .\main.py` | Run `help dj` at the Mariana prompt. |
| Native TUI | `& $python .\main.py --tui` | A full-screen workspace appears inside the same terminal. F6 opens the command browser, F8 opens the DJ view, and Q from a browsing view asks to exit Mariana. If opened with `tui` inside the CLI, Q returns to that CLI. |
| Portable Flow | `& $python .\tools\build_web_player.py --serve --view flow --open` | A browser opens on the graphical player. Click **DJ studio → Open mixer**. The server prints its URL and stays in this terminal. |
| Portable Console | Open `http://127.0.0.1:8767/?view=console` on that server | Type `help`, then `flow`, or use the Console and Flow buttons in one tab. |
| Electron desktop | In a second PowerShell, run `npm.cmd ci` once for this checkout, then `npm.cmd run dev` | A separate desktop window opens with its own Mariana terminal and a Strudel toolbar button. Use Node.js 24 and the existing Python environment. |
| Same-computer browser controlling the native player | At the native Mariana prompt, type `web session` | Open its one-time invitation and connect. Native commands run against that host after the terminal review. |
| Voice room | Open `http://127.0.0.1:8767/?view=voice` on the running server | The invite panel opens. It contacts the meeting provider when you choose to join. |

Ctrl+C stops the web server. For an occupied port, add `--port 8768` and use the printed address. A running old `python -m http.server` can occupy the same port. Stop it in its own terminal or choose another port. The Mariana launcher builds and validates the directory before serving it. The Vite-only `npm run dev:web` target develops the Electron renderer, which uses the Electron bridge.

If the native environment is missing, use Python 3.12 to run `python -m venv .venv`, then `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`. On Bash, use `./.venv/bin/python main.py --tui`, `./.venv/bin/python tools/build_web_player.py --serve --view flow --open`, and `npm ci && npm run dev` in separate terminals. On Windows the source checkout expects its virtual environment under `.venv\Scripts`, including when running Git Bash.

## What travels between platforms

| Capability | Native CLI, TUI and Electron terminal | Local web Console and Flow | Phone and watch |
| --- | --- | --- | --- |
| Users, login, sessions | Local Mariana library plus external account connections. A Matrix login identifies the user in listening rooms. | Loopback broker can use that OS profile's Matrix session. Portable playback state belongs to the browser profile. | Phone keeps local player state. Independent Matrix login/room membership in the packaged phone and watch clients is pending. |
| Jams and stream rooms | Invite-only Matrix room, join, leave, roster, suggestions, host cues and explicit cue application. Fanroom commands provide messages and reactions. Existing native Icecast broadcasting uses a configured server. | Listening rooms show the same membership and cues using the local Python service. Voice meetings have a separate join and hang-up. | Phone can open a voice invite in its browser. Watch has standalone playback and practice controls. |
| Multi-singer lyrics and karaoke | Singer-labelled words, overlapping lines, part selection, timing import, vocal controls for eligible material. | **Try a duet**, then switch parts. Exact recording identity and word evidence gate timed playback. | Phone shares portable karaoke. Watches play the bundled duet and export a selected practice range. |
| Speech and recording | Record the local mic, use an optional installed Vosk model for live captions, label speaker changes, export WAV/VTT/TXT. | Mic recording, export and device sharing where supported. Browser live captions depend on its recognition service and permission. | Phone wrappers have a microphone path and sharing bridge. OS/WebView capabilities and device validation still matter. |
| DJ | Two independent decks, local audio, transport, hot cues, ranges, playback rate, crossfades and master WAV recording. F8 opens the TUI mixer. `dj mixxx` opens a separate installed Mixxx with the loaded tracks. | Two-deck graphical mixer, EQ, master recording, hot cues, loops and output selection where supported. | Phone packages the mixer. Actual hardware, background behavior and output selection vary. Watch has no deck UI. |
| Strudel | Saved projects, source import/export and WAV rendering of the supported oscillator grammar with Node. Electron also provides the isolated Strudel editor for richer syntax. | Offline pattern editor, bounded oscillator rendering, preview and WAV export. | Phone shares the portable engine. Watch has no Strudel editor. |
| Podcasts and audiobooks | Public RSS, episodes, LibriVox books and sections, Podbean discovery and follows, resume and spoken listening controls. | Catalog, public feeds, library, Podbean and LibriVox, playback controls and eligible publisher transcripts. Providers must allow browser feed access. | Phone shares the portable catalog. Watch supports direct stream playback and its practice tools. |

A **90% karaoke eligibility threshold** is a gate on the supplied timing evidence and coverage for the exact recording. It does not measure acoustic recognition accuracy. An unscored or below-threshold sheet can still supply readable lyrics. Automatic singer identification, separation of overlapping speakers and reliable song transcription from arbitrary audio remain open. [Karaoke scoring and fixtures](KARAOKE.md)

## Two-person rehearsal

1. On two computers or two OS user profiles, sign in to the same reachable Matrix ecosystem with separate accounts using `jam login https://YOUR-HOMESERVER`. The selected server must support browser SSO for this flow. Look at `jam status` on both computers.
2. One person runs `jam create Evening rehearsal` and `jam invite !ROOM:server @friend:server`. Use the actual room ID from the first command and the other person's actual Matrix ID.
3. The other person runs `jam invites`, `jam join !ROOM:server`, then `jam members !ROOM:server`. Load the same edition of a recording in each player.
4. The host runs `jam send !ROOM:server`. The other person inspects `jam current !ROOM:server` and uses `jam apply !ROOM:server`. This applies the stated playhead position. For a playing cue, `jam sync !ROOM:server` can align once using the homeserver timestamp. Continuous clock correction and sample-accurate performance over the network remain open.
5. For talking, open **Voice room → Create invite link** and share the generated link only with the participants you choose. Each person joins in the browser. The public meet.jit.si service handles the microphone, sign-in and hang-up. Its room creator needs to authenticate. A meeting invite grants access according to the meeting provider’s rules independently of Matrix membership. [Jitsi authentication](https://jitsi.org/blog/authentication-on-meet-jit-si/)
6. Hang up in the conference and run `jam leave !ROOM:server` to leave the listening room. `jam logout` closes the Matrix session. Distinct OS users let you exercise both sides independently. [Jam command guide](JAM_ROOMS.md)

For an operator-controlled Jitsi deployment, set `$env:MARIANA_JITSI_ORIGIN = 'https://meet.your-domain.example'` before building the web player. Replace that example with your working Jitsi origin. The computer browser then offers **Join here** and **Leave embedded call**. Public meet.jit.si is opened externally. The provider must allow embedding for this deployment. No credentials or meeting links are bundled. [Jitsi embedding options](https://jitsi.org/jaas/)

## Short audio checks

| Test | Try | Expected result |
| --- | --- | --- |
| DJ transition | Load two short local tracks on A/B in Flow, play both, start **Record master**, move the crossfader, stop recording and download the WAV. | Listening back to the WAV reproduces the transition. A headphone preview requires compatible output selection and separate hardware. |
| Duet | Run `karaoke demo` in the native session or press **Try a duet** in Flow. Change the highlighted singer and jump to the next phrase. | Timing follows playback. On a track without an eligible sheet the UI explains the missing evidence. |
| Speech | In the native session enter `speech record`, speak, then `speech stop` and `speech export take.wav`. For offline captions, install Vosk in the virtual environment and supply an extracted language model to `speech start "MODEL_DIRECTORY"`. | WAV contains the local microphone. For a transcribed take, export `take.vtt` and inspect word/phrase timing and any manually assigned labels. |
| Strudel | In Flow open **Strudel patterns**, render the starter, play it, then save its WAV. In Electron open **Strudel** and render a saved project. | The portable example plays offline. Full Electron patterns may depend on additional sound banks. |
| Podcasts / audiobooks | In Flow open the catalog selector. Try **Podbean by title**, **Podbean by slug or URL**, then **LibriVox**. In native Mariana try `podbean search music` and `librivox search Dracula`. | Open a returned show or book, queue an episode or chapter, seek forward and resume it. Online results depend on the provider. |

To record a jam from a supported desktop browser, open the call in a separate tab, then choose **Microphone studio → Record a jam with other performers**. After all participants agree, select the call tab, enable its audio and allow microphone access. Stop the recording in Mariana and use the resulting download or share control. The file mixes both sources. Closing a meeting and leaving the Matrix room are independent. [Speech and jam recording](LIVE_SPEECH.md)

A native `session record NAME` saves a listening recipe. Use a DJ master recording for the mix or a speech recording for the selected input. Different people’s isolated stems, room-wide cloud recordings, automatic replay publishing, an always-on streaming backend and centralized Mariana accounts/library sync remain open. Advanced DJ work including beat-grid synchronization, controller mapping and four native decks is tracked separately. Podbean creator publishing, analytics, subscriptions and paid entitlements require additional provider integration. [Native DJ controls](DJ_STUDIO.md) · [Portable mixer](PORTABLE_DJ.md) · [Strudel](STRUDEL_SURFACES.md) · [Spoken catalogs](SPOKEN_SUITES.md) · [Platform tracker](PLAYER_EXPANSION_STATUS.md)

## Android and Apple previews

For the Android phone and Wear OS archives, use JDK 17, Gradle 8.13, Android SDK platform 36 and Build Tools 35.0.0. Choose an authorized debug target with `adb devices`.

```powershell
& $python .\tools\build_web_player.py
gradle -p mobile/android :app:assembleDebug :wear:assembleDebug
adb install -r .\mobile\android\app\build\outputs\apk\debug\app-debug.apk
```

After installing the phone APK, open **Mariana** from the app drawer and choose **Flow**. Test a local file, a duet and the DJ master export before trying microphone permissions or external accounts.

If several devices are attached, use `adb -s DEVICE_SERIAL install -r APK_PATH`. Install the separate Wear APK on the watch. For iOS and watchOS use a Mac with Xcode/XcodeGen to generate the project, build the player assets plus Apple icons, and run the MarianaPhone or MarianaWatch simulator scheme. The platform guide supplies both xcodebuild commands and the manual preview workflow. Physical-device signing, TestFlight, Play/App Store submissions and publishable cloud hosting require separate release work. [Phone and watch builds](WEB_MOBILE_WATCH.md) · [Watch controls](WATCH_PRACTICE.md)

# DJ studio in Console, Flow and the phone player

From the repository root on the development laptop, start the local player.

```powershell
python tools/build_web_player.py --serve --port 8767
```

Open [the local player](http://127.0.0.1:8767/). Type `dj` in its Console, or open **Studio → DJ studio → Open mixer** in Flow. Both views operate the same live decks. Android and iOS phone builds package this player. Native CLI, TUI and Electron's native session have their own DJ implementation.

## Make a first mix

1. Import recordings in **Local library**, then search **Local tracks** in the mixer and select **Load A** or **Load B** beside each result. **Choose file** loads a one-off recording directly into a deck. **Use current track** accepts the local queue selection, including a generated tone.
2. Click a deck overview to jump within the entire recording. The parallel waveforms above the decks scroll around fixed playheads. Set **Window** to view 4, 8, 16, or 32 seconds at the current playback rates. A mouse or touch action on either waveform seeks to that point, and the position slider offers keyboard seeking. Cue lines and the shaded loop use the same time coordinates as their deck.
3. Start deck A. The crossfader starts fully on A. Start deck B, then move the fader toward B in the center mixer. Its center position combines both decks with an equal-power curve. The center mixer also contains each deck's gain and three EQ bands, plus the stereo master peak meters.
4. Select an empty hot cue pad to store the current position. Select a populated pad to jump back, or use **Clear cue** to remove the selected point. During playback, press **Mark in**, then **Mark out**. The audio engine repeats that region until you clear the loop or seek outside it.
5. For a long set in a browser offering **Record to disk…**, choose a WAV destination first. For an in-memory take, press **Record master**. With recording active, perform a transition, then **Stop recording**. Choose **Download WAV** or **Share WAV…** where the OS accepts audio files. A new take replaces the previous download when it finishes. Save each take before you close the page.
6. On a browser with output selection and separate hardware, choose a headphone output and enable **Headphone cue** for the deck you want to audition. Play that deck with the crossfader at the opposite end. Its cue signal is routed through the selected output separately from the master and recording. The master follows the system output. Disconnecting an audio device clears the headphone selection.

| Console command | Operation |
| --- | --- |
| `dj load A`, `dj load B current` | Choose a file or use the current local queue track. |
| `dj play A`, `dj pause B`, `dj stop all` | Start, pause, or stop the decks. Stop returns a deck to zero. |
| `dj seek A 12.5`, `dj rate A 1.05` | Seek in seconds or change playback rate from 0.25× to 4×. Pitch changes with rate. |
| `dj gain B 85`, `dj eq A low -6` | Adjust deck gain from 0–200% and low/mid/high EQ from −24 to +12 dB. |
| `dj cue A set 2`, `dj cue A go 2`, `dj cue A clear 2` | Store, recall or remove the selected deck's cue in slot 1–8. |
| `dj loop B 8 16`, `dj loop B off` | Loop the exact 8–16 second region or resume straight playback. |
| `dj crossfade 50` | Set the fader from 0 (A) to 100 (B). |
| `dj headphones choose`, `dj pfl B on`, `dj headphones off` | Choose a headphone device, enable pre-crossfader listening, or disconnect it. |
| `dj record start`, `dj record stop`, `dj export`, `dj share` | Capture the stereo master and download or share the finished WAV. Use `dj record disk` to write a long set directly to a chosen file where supported. |
| `dj status`, `dj help` | Inspect both transports or list commands. |

## Current coverage

| Capability | Status |
| --- | --- |
| Mixing and timing | Two independent local decks with PCM waveform overviews and parallel scopes, seek, rate, three-band EQ, gain, hot cues, sample-timed loops, equal-power crossfader, master dynamics and stereo peak meters. Console and Flow share state until the page closes. |
| Media input | Browser-supported local audio. Each input is limited to 96 MiB compressed and 192 MiB decoded. Queue items that refer to remote streams cannot load onto these decks. |
| Recording | Stereo 16-bit PCM WAV at the audio context sample rate. In-memory takes are bounded at 128 MiB in the browser and 32 MiB with the phone share bridge. At 48 kHz these are approximately 11 minutes and 2 minutes 54 seconds. The recorder shows the available time, stops at the limit and keeps the captured audio. Direct-to-disk recording on browsers with a save-file picker writes samples progressively and finalizes the WAV header on Stop. The standard RIFF size ceiling is just under 4 GiB (about 6 hours at 48 kHz). Stop before closing the page to commit the file. |
| Monitoring | Independent headphone output requires a browser with both an output picker and audio-element sink selection, plus a second physical output. A browser with only a single output still supports hot cues and master playback. [Browser output selection](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/selectAudioOutput) |
| Scope of master capture | The WAV includes audio from both DJ decks. Microphone speech, other apps, Strudel and remote room audio require their respective capture/routing paths. A room membership alone does not add participant audio to a DJ recording. |
| Open work | Long-form recording on phone shells, RF64 files above 4 GiB, multitrack room capture, four decks, persistent crate/cue import, key lock, BPM/beat-grid analysis/sync, scratch/DVS, MIDI/HID mapping, and streaming the mix into a room. These are candidates for further native integration. [Mixxx manual](https://manual.mixxx.org/) |
| Release acceptance | Browser graph, transport and WAV tests are automated. Stereo output devices, real-time latency, iOS/Android saving and physical headphone routing require device checks. |

The parallel-waveform, deck, mixer and local-track layout takes its workflow from the open-source Mixxx interface. Mariana's browser mixer operates through Web Audio. [Mixxx interface guide](https://manual.mixxx.org/2.5/en/chapters/user_interface)

Run the deterministic tests with `node --test tests/web_dj.test.mjs`. The browser test in `web/tests/dj.spec.ts` loads two WAVs into real decks and checks channel levels before and after a live crossfade. With the desktop npm dependencies and the Playwright Chromium binary installed, run the following from the repo root.

```powershell
python tools/build_web_player.py
npx playwright test --config web/player.e2e.config.ts dj.spec.ts
```

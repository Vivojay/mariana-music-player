# DJ studio

Press **F8** in the terminal player to see both playheads, the crossfader and recording status. Use the arrow keys and Enter to load or control a deck. Controls that take a value open in the editor. Esc returns from the editor or transcript to the mixer. You can also type the commands below at Mariana's prompt, in its Electron terminal, or in the TUI command editor (F1).

From the repository in PowerShell, start the terminal player directly:

```powershell
& '.\.venv\Scripts\python.exe' '.\main.py' --tui
```

On a system with the Bash virtual environment, use `./.venv/bin/python main.py --tui`. The native mixer needs FFmpeg, the project's NumPy and sounddevice dependencies, PortAudio, and a default two-channel output that accepts 48 kHz. Loading a deck decodes its first audio stream into temporary disk-backed PCM. A track can be up to two hours and consumes about 23 MB of temporary disk per minute. Closing or replacing the deck releases that storage.

## Make a first mix

Pause ordinary player playback if it is running. Load two different local audio files, two library indexes, or use the bundled six-second practice track on both decks. Each command below runs inside Mariana. The example places deck B three seconds ahead of deck A.

```text
dj load A res/karaoke/practice-duet.wav
dj load B res/karaoke/practice-duet.wav
dj seek B 3
dj cue B set 1
dj loop A 0 6
dj loop B 3 6
dj crossfade 0
dj record start
dj play all
dj crossfade 100 3
```

Let the transition play for a few seconds. Then enter:

```text
dj record stop
dj stop all
dj export
```

The exported path points to a playable stereo WAV. Give `dj export` a new filename to make another copy. On your Windows laptop, use the path to your downloads folder directly inside Mariana:

```text
dj export "D:\C DOWNLOADS\Mariana first mix.wav"
dj share
dj close
```

`dj share` opens the last finished recording in the local browser share page. If the browser and chosen app accept WAV files, press **Share file**. Otherwise use **Save** or attach the exported file in that app. The share link stays on this computer and expires after ten minutes. `dj close` releases the output, finishes an active recording and unloads both tracks.

## Controls

| Command | What it does |
| --- | --- |
| `dj load A FILE`, `dj load B 7`, `dj load A current` | Replaces one deck with a local file. The other deck continues playing while FFmpeg decodes the replacement. Failed loads leave the previous track available. |
| `dj play A`, `dj pause B`, `dj stop all` | Each transport accepts A, B or all. Pause holds the playhead. Stop rewinds. |
| `dj seek A 12.5` | Moves the playhead to a position measured in seconds. Seeking or recalling a cue outside an active loop releases that loop. |
| `dj cue A set 2`, `dj cue A go 2` | Sets or recalls one of eight hotcues. Returning to a cue preserves play/pause. Cues are scoped to the loaded track and deck. |
| `dj loop A 12 16`, `dj loop A off` | Starts a loop at the given boundaries, in seconds. Disabling it continues from the current playhead. |
| `dj gain B 80`, `dj rate A 1.1` | Sets gain between 0% and 200%, or changes playback speed and pitch together from 0.25× to 4×. |
| `dj crossfade 50`, `dj crossfade 100 4` | Sets the equal-power crossfader immediately or ramps to its new position over the specified seconds. Full left is A, full right is B. Reduce deck gain if the sum clips. |
| `dj record start [FILE.wav]`, `dj record stop` | Records the two-deck master after gains and crossfading, including audible silence, to 48 kHz 16-bit stereo PCM. Choose a new filename or use the suggested destination in Mariana's data directory. Stop before the WAV approaches 4 GiB, about six hours. |
| `dj status` | Shows source, play state, position, duration, gain, rate, loop, cues, crossfade, master peak in dBFS, clipped sample frames, recording and output timing warnings. |
| `dj mixxx` | Opens a locally installed Mixxx with loaded files in A/B order, pauses the Mariana decks and releases their output. Finish a Mariana recording before switching. Mixxx uses its own transport, cues, library and recording settings. |

## Delivery and outstanding work

| Capability | Status |
| --- | --- |
| Native desktop DJ mixer | Implemented in Mariana's interactive CLI and F8 TUI. An Electron terminal uses the same engine. A paired loopback browser can request the native commands through the normal host approval flow. |
| Portable browser DJ mixer | Console and Flow share a two-deck mixer with parallel decoded waveforms, a local-track picker, visible hot cue pads and a central stereo mixer. Browser tabs and native decks keep separate playheads and recordings. [Portable studio controls](PORTABLE_DJ.md) |
| Timing and recording checks | Automated tests decode real stereo WAVs with FFmpeg. The output callback is driven with test audio buffers. Assertions cover both channels, 50% equal-power mixing, timed fades over block boundaries, sample-accurate cue/loop/seek/EOF, rate interpolation, WAV bytes, file protections and release of the output. |
| Physical release acceptance | Listening tests on Windows, macOS and Linux sound cards, installed Mixxx launch per OS, mobile background playback, headset routing and device latency measurements are pending. |
| Extended DJ controls | Four decks, controller mappings, beatgrid analysis/sync, key lock, headphone pre-fader listening, scratch and effects are available in an independently installed Mixxx. In-process implementations, saved cue libraries and transfer of Mariana's performance state to/from Mixxx are open. |
| Capture and broadcast | This WAV captures the native DJ stereo master. Microphone input, main-player audio, jam-room voices and speech-to-text are separate signal paths. Combining them with the live DJ master, multitrack stems and network broadcast remain open. |
| Device and overload limits | The native mixer uses the OS default stereo output and fixed 48 kHz sampling. An unavailable or busy device is reported when playback starts. If disk writes cannot keep pace or the WAV size limit is exceeded, the recorder reports the interruption and retains the partial capture for recovery. Hardware device selection and high-load profiling are open. |

## Reference workflows

Mixxx documents loading music files into successive decks at startup. Mariana uses that public command-line interface, so users keep their existing Mixxx installation, audio settings and controller mappings. [Mixxx command-line manual](https://manual.mixxx.org/2.5/en/chapters/appendix/commandline_dev_tools) · [Mixxx features](https://mixxx.org/features/)

VirtualDJ's deck controls separate transport, cue pads, effects and loop controls. Mariana's F8 workspace presents its implemented transport, hotcues and manual loop bounds for each deck. [VirtualDJ deck manual](https://virtualdj.com/manuals/virtualdj/interface/decks/decksadvanced.html) · [VirtualDJ pads](https://virtualdj.com/manuals/virtualdj/interface/decks/decksadvanced/pads.html)

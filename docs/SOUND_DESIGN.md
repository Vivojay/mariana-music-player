# Sound design

Use `fx presets` to list factory racks and your saved racks, then try `fx preset choir` while a track plays. In the native TUI enter commands with **:**. In the portable player or FLOW select **Sound design → Effect preset** or use its command box. Effects begin dry each launch.

| Command | Result |
| --- | --- |
| `fx preset vocal-booth` | All-media de-essing and short room reflections |
| `fx preset synth-voice` | Vocodes the input signal onto a 110 Hz sawtooth carrier and adds chorus |
| `fx set pitch -3` | Shifts pitch down three semitones during playback, preserving the source playhead |
| `fx set tune 75` | Corrects a single voiced melodic line toward the nearest chromatic note at 75% strength |
| `fx set deess 70` | Reduces sibilance on any input, including music and the microphone |
| `fx set chorus 45`, `fx set room 25`, `fx set delay 30` | Stereo modulation, room reflections and rhythmic repeats |
| `fx set drive 20`, `fx set tremolo 50`, `fx set robot 70` | Soft saturation, 5 Hz amplitude modulation and ring modulation |
| `fx set bitcrush 75`, `fx preset bit-sampler` | Reduce bit depth and hold output samples for a lo-fi digital effect |
| `fx set tapestop 80` | Slows the captured sound to silence over about 0.82 seconds while the source playhead continues. Set the amount to zero to release it |
| `fx save evening`, `fx load evening` | Save or recall the complete rack in the current profile. Save again to update it |
| `fx mic on`, `fx mic off` | Start or stop local headphone monitoring with the same rack and an independent DSP instance |
| `fx status`, `fx off` | Inspect or bypass the rack. A microphone already in use continues monitoring dry until `fx mic off` |
| `speed 0.8`, `speed 1.25`, `speed 1` | Change speed on the current finite, seekable native track with pitch preserved. Use `speed status` to inspect the native rate. The portable player also supports `speed RATE`. [Timing and limits](SPOKEN_LISTENING.md) |
| `fx tempo 0.8 "song.wav" "practice.wav"` | Native offline time stretch between 0.5× and 2×, preserving pitch and writing a new WAV |
| `fx plugin install NAME ZIP_OR_HTTPS_URL SHA256` | Explicitly install a verified vendor ZIP in the active listener profile |
| `fx plugins` | List vendor packages installed in this profile |
| `fx plugin "Effect.vst3" "voice.wav" "processed.wav"` | Render through a locally installed effect, in a separate native process, with its default parameters |

Except for pitch (−12 to +12 semitones), control values range from 0 to 100. The rack includes eleven original presets and ships with the tone, synth and sound effect generators in the native and browser players. Chorus and pitch shifting use modulated fractional delay lines. The vocoder tracks eight speech bands. Chromatic tuning estimates a monophonic 70–900 Hz fundamental and leaves unvoiced input alone. Dense backing tracks, polyphonic vocals and breaths can make pitch estimates unreliable. The room effect uses a short sequence of stereo reflections. Editing live parameters starts new filter and delay memories. The master bounds final samples to the output range.

## Routing and setup

* **Native CLI, TUI and Electron's Mariana console** apply rack controls to the native local-listening output before graphic EQ and master volume. `eq` continues to control the existing graphic EQ. `eq deesser` retains its spoken-media setting. Leave it off when using the rack de-esser on spoken material to avoid applying both. Playback recording, broadcast and audio identification taps retain their original source signal.
* **Microphone** uses a separate mono input and stereo output at 48 kHz. Connect headphones before starting. Native monitoring needs a working duplex PortAudio device, NumPy and sounddevice. The default native dependencies include SciPy for the vocoder and de-esser. Browser monitoring needs microphone permission, a secure origin (HTTPS or localhost) and Web Audio worklet support. The monitor plays locally. It does not record a file or send the microphone to other applications. Stop it explicitly with `fx mic off`.
* **Portable browser, FLOW and the mobile web wrapper** apply the rack to local files, generated arrangements and microphone monitoring. Direct remote media stays on its ordinary media element to preserve CORS-compatible playback. The browser's listening-speed selector and `speed RATE` change ordinary media speed in real time. A native DJ deck supports real-time varispeed from 0.25× to 4× using `dj rate A 1.25`. The native main player's `fx tempo` command renders a new file. A DJ deck and the main-player monitor have independent signal paths.
## Optional VST3 and Audio Unit effects

Third-party effect binaries and their separate Python host are absent from the base installer. The factory rack works immediately. To install one portable effect package, get its platform-specific vendor ZIP and an independently published SHA-256 digest. From the native Mariana command prompt run:

```text
fx plugin install my-effect "D:\Downloads\Vendor-Effect.zip" <sha256>
fx plugins
fx plugin my-effect "voice.wav" "processed.wav"
```

You can give a direct vendor HTTPS ZIP URL instead of the local path. Mariana downloads or copies the archive on this explicit command, verifies its SHA-256 before extraction, and installs it under the current profile's FX folder. The ZIP must contain one .vst3 bundle or, on macOS, one .component bundle. Downloading and listing never load the plug-in. Packages with license managers, installers or symbolic links use the vendor installation process. You can pass the resulting plug-in path directly to `fx plugin`.

For rendering from a source checkout, first install the optional host in its active Python environment with `python -m pip install --only-binary=:all: pedalboard==0.9.26`. For a packaged release, point `MARIANA_PLUGIN_PYTHON` to a compatible external Python with Pedalboard installed and then launch the application from that environment. On Windows, a separate host environment keeps the native distribution small:

```powershell
$pluginHost = Join-Path $env:LOCALAPPDATA 'Mariana\plugin-host'
python -m venv $pluginHost
$env:MARIANA_PLUGIN_PYTHON = Join-Path $pluginHost 'Scripts\python.exe'
& $env:MARIANA_PLUGIN_PYTHON -m pip install --only-binary=:all: 'pedalboard==0.9.26'
```

Launch Mariana from the same PowerShell session so the application inherits the environment variable. On macOS and Linux use the environment's `bin/python` for `MARIANA_PLUGIN_PYTHON`. Match the host interpreter and plug-in to the operating system and CPU.

Render effects from vendors you trust. The helper loads native plug-in code in a separate process with your OS account's permissions. The separate process protects main-player responsiveness. It renders with the plug-in's default parameters and exactly the source duration. A crash or timeout prevents activation of that output. Classic VST2, instruments, GUIs, live third-party inserts, parameter automation, and unbounded effect tails remain outside this renderer. [Pedalboard API](https://spotify.github.io/pedalboard/reference/pedalboard.html) · [Plug-in compatibility](https://spotify.github.io/pedalboard/compatibility.html)

## Verification and remaining work

The Python tests send stereo samples through the native player's real output callback, verify the pitch change, measure chromatic correction, check all presets, reset delay memories across a source change, drive the duplex microphone callback with a test stream and run an actual FFmpeg tempo render. The browser tests run both worklet processors with stereo buffers, assert echo timing, octave shifts and correction, then exercise the web commands and profile storage. Native and browser tests verify that bitcrush keeps the same output across callback boundaries. Native package tests cover opt-in installation, mismatched hashes, rejected archive paths and symlinks, and alias selection for an offline render.

A Linux acceptance run drove the complete native application through first-run tool selection and the regular CLI prompt. It saved and loaded a choir rack, played the Twinkle arrangement through FFmpeg, changed its speed to 1.25×, paused, sought, inspected FX and profile status, and exited cleanly. The timed stereo PCM sink captured more than 72,000 non-silent frames. A separate terminal session opened the full TUI, searched its palette, inspected the rack and played the arrangement. The Linux system's audio device was simulated for these checks.

Physical microphone and device-loopback latency, commercial plug-in interoperability, wearable effects, live VST hosting, MIDI instruments, selectable vocoder sidechains/carriers, formant-preserving or scale-specific vocal tuning, persistent whole-song automation, multi-band mastering and spectral resonance suppression are pending. The factory racks are original algorithms and presets. Third-party product libraries and presets require their own installations and licenses.

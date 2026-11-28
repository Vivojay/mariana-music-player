# Mariana Studio Workbench

For the newer browser library, video defaults, on-demand plug-ins and scope by platform, see the [studio follow-up](STUDIO_NEXT.md).

Start in a terminal with `python main.py tui`. Press **F2** to open Player, **Ctrl+K** to search commands, or **:** to enter a command. In a standalone browser run `python tools/build_web_player.py --serve --view flow --open` from the checkout. A local browser can also operate a running native player through `web session`.

| Try this | What to expect |
| --- | --- |
| `tone procedure play twinkle` | A complete stereo arrangement with melody, accompaniment and bass. Adjust it with `--bpm 85 --chorus 55`. Pause or seek with the regular player. |
| `tone keys glass` or `tone sfx footstep` | Play a synth voice from the keyboard, or hear a synthesized sound effect. |
| `soundbank play glass-opal 330` | Hear a morphing wavetable at 330 Hz. Use `soundbank list` to explore all 64. |
| `speed 0.8` or `speed 1.25` | Slow down or speed up a finite, seekable native track with its pitch preserved. The picture and seek bar follow source time. Use `speed 1` to restore the original rate. |
| `fx preset choir`, then `fx off` | Compare processed local audio with the dry track. `fx set pitch -3` shifts down three semitones. `fx mic on` and `fx mic off` explicitly start and release headphone monitoring. |
| `profile create Studio` followed by `profile use Studio` | Keep a separate library and listening history. Relaunch a native session or allow the browser tab to reload. |
| `accounts setup` | Pick an available service or start the guided karaoke, podcast or audiobook workflow. |
| `play current --video` followed by `video status` | See the picture surface immediately and inspect extraction, probing or buffering progress. Close with `video close`. |

## Implementation and acceptance ledger

| Area | Included and verifiable | Remaining work and detailed status |
| --- | --- | --- |
| Commands and terminal UI | Standalone keyboard workspace, searchable command catalogue and input recall, navigable transcript blocks, profile-scoped opt-in native history, browser session recall. | Physical console, screen-reader and keyboard-layout acceptance across operating systems. [TUI](TUI_CAPABILITIES.md) · [completion and history](COMMAND_COMPLETION.md) |
| Synthesizers, tone and harmony | Procedural instruments, named scores with multiple parts and a stereo chorus, playable keys and synthesized foley, separate library of 64 original morphing tables. | Commercial synthesizer formats, sample instruments, hardware MIDI controllers and vendor preset import require dedicated integrations. [Stored scores](TONE_PROCEDURES.md) · [waveforms and external banks](WAVETABLES.md) |
| Effects, microphones and voice | Native PCM rack and browser DSP for local audio, microphone monitoring, chromatic monophonic correction, built-in-carrier vocoding, pitch shifting, modulation, de-essing, time stretch and offline plug-in processing as documented. EQ remains independently usable. | Third-party real-time insert chains, arbitrary sidechain carriers, polyphonic vocal separation, artist voice conversion, high-end mastering equivalence and measured physical input/output latency remain open. [Sound design](SOUND_DESIGN.md) · [EQ](EQUALIZER.md) |
| Video | Separate synchronized window, readiness feedback, reuse of recent format metadata and seek-local byte-range retention for supported recordings. Transient extraction can retry with a separately installed yt-dlp or public-recording youtube-dl executable. | Startup timing depends on providers, machine, codec, and access. Public-provider timing, signed cross-platform installers and physical A/V alignment require acceptance. [Video, cache and recovery](VIDEO_PLAYBACK.md) |
| Profile, service and account setup | Local listener isolation, storage, restore of the original Default profile, browser-based consent and feature-specific setup where available. | Cloud accounts, profile sync between devices, publisher registrations and live OAuth/device-keychain acceptance. [Profiles](LISTENER_PROFILES.md) · [connections](CONNECTIONS.md) |
| Desktop, website, Docker, phone and watch | Source integrations, portable browser bundles, a separate Linux x86-64 local-studio CLI/TUI preview, build instructions and platform workflows. The release guide names the exact artifacts produced. | Signed desktop releases, production containers on target hosts, phone/watch installation, accessibility and store distribution require their listed acceptance steps. [Release matrix](PORTABLE_RELEASES.md) · [surface parity](SURFACE_PARITY.md) |

The earlier expansion ledger covers artist discovery, catalogues and vendors, themes, spoken-word listening, DJ decks, jam and fan rooms, clipping, social sharing, karaoke confidence and multi-singer scores, speech recognition, Strudel, audiobook/podcast suites and watch practice. Existing feature-specific limits and open items still apply. [Player expansion status](PLAYER_EXPANSION_STATUS.md) · [studio surfaces](STUDIO_SURFACES.md) · [competitor research](MARIANA_COMPETITOR_RESEARCH.md) · [social and karaoke comparison](SOCIAL_AND_KARAOKE_RESEARCH.md)

## Verification for this kit

- The native CLI completed first run, played the included arrangement through FFmpeg, changed speed, paused, sought and remained available for the next command. A Linux pseudo-terminal exercised the actual TUI, palette and command output. A timed PCM sink replaced the physical output device.
- In a graphical Linux test, a window appeared in 0.162 seconds while its provider was deliberately stalled. A range-served test recording reached the first picture in 0.276 seconds and sought in 0.098 seconds. A separate whole-CLI local-MP4 run mapped its window in 0.539 seconds. These measurements apply to the fixtures. A public YouTube video can take longer or be unavailable.
- The separately frozen native Linux studio ran outside the source checkout, with genuine PortAudio and ALSA null output. Its command loop played Twinkle and the TUI opened its palette.
- The frozen Linux browser host served 61 assets. Its actual browser media element decoded the stereo, 28.8-second arrangement and advanced during playback. Browser controls exercised the soundbank, FX rack and profile commands. The static archive and fresh source build matched file for file. The Windows kit embeds the same portable player.
- A combined 128-test Python run exercised the soundbank, typed command grammar, profiles, TUI history, effects, scores, playback speed, video commands and web launcher. All 86 portable JavaScript tests passed. These counts cover the selected test runs. They do not establish physical-device, live-provider or store-release acceptance.

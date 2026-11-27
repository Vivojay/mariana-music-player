# Listening to podcasts and audiobooks

The main Electron player puts a voice control beside the playback strip. Choose **Soften sharp S sounds** before starting an episode or during playback. Off preserves the original audio. Gentle, Balanced and Strong cap gain reduction at 3, 6 and 9 dB respectively. Use Back 15s to rehear a phrase or Forward 30s to move ahead. Jump to chapter appears when a seekable episode exposes markers. For a LibriVox book whose chapters are separate files, use the existing `librivox goto <chapter>` command.

In the terminal, `eq deesser gentle` selects a level and `eq status` shows it. The setting uses the same revision-checked settings service as the desktop control. It persists across launches, operates with the graphic equalizer bypassed and survives EQ preset changes. The default is Off.

## Audio path

At Mariana's 48 kHz device rate, a 4.5–11 kHz band-pass detector compares stereo-linked sibilant energy to overall speech energy. Loud, predominant sibilants trigger a smoothed broadband reduction. Quiet passages and low-frequency speech retain their level. The detector carries state between audio blocks. Switching decoder sessions clears its history. Gain only decreases. The processor runs on local monitor PCM after the broadcast tap. Recordings, exports and broadcast audio use the original signal.

The player recognizes podcast media, including chapters from the LibriVox catalog. Mixed overlaps containing music bypass the voice treatment. External video players and arbitrary desktop audio files without podcast identity use original audio. The unit suite exercises synthetic sibilance and vowels, channel matching, bypass, stream changes, settings persistence and interrupted writes. Listening tests on recordings made with varied microphones are pending.

## Web and phone listening

The browser player and its Android and iPhone shells offer an independent voice setting on imported audio files. Choose a mode per file, including an imported podcast or audiobook. An AudioWorklet carries the detector between output blocks. The player reserves a separate audio element for local files. Links and RSS enclosures use ordinary streaming so that sites that restrict Web Audio access can still play. Download an episode through its publisher and import the file to use voice processing. A browser without AudioWorklet support, or a mobile file context that cannot load it, plays the original recording. No audio is uploaded for processing.

Run `node --test tests/web_speech.test.mjs` for the worklet signal and unavailable-module checks. Android and iPhone device playback checks are pending.

## Publisher episode transcripts

Import an RSS feed or add an episode from the podcast catalog. If the publisher supplies a Podcasting 2.0 transcript, **Episode transcript** appears for that episode. Choose a language or format and press **Read transcript**. Search for literal words or phrases within a cue or paragraph, then select a timestamp to seek the current episode. Plain text supports reading and search. WebVTT, SubRip and Podcasting 2.0 JSON support cue navigation. For HTML editions or a server that restricts CORS, open the publisher link or copy it into a browser.

Only transcript references are stored with the local queue. Reading makes an explicit request with a 15-second timeout, 2 MiB limit and no credentials. Changing episodes cancels pending reads. Results display in pages of 40. Word-level highlighting, speaker diarization, generating missing transcripts, TTML, synchronization with dynamically inserted ads, and native Electron transcript UI are pending. Run `node --test tests/web_transcripts.test.mjs` to check parsing, track switching, bounded responses, literal search and cue navigation.

Apple documents its reader and tap-to-seek interaction. Podcasting 2.0 specifies the episode tag and JSON cue format used here. [Apple Podcasts transcripts](https://podcasters.apple.com/support/5316-transcripts-on-apple-podcasts) · [Episode tag](https://podcasting2.org/docs/podcast-namespace/tags/transcript) · [Transcript file formats](https://podcasting2.org/docs/podcast-namespace/examples/transcripts/transcripts)

## Product references

- Apple Podcasts puts voice enhancement, chapter navigation and 15/30-second skip controls near playback. [Apple Podcasts controls](https://support.apple.com/guide/iphone/play-podcasts-on-iphone-iph3a22707a5/ios)
- Podbean offers intelligent speed, volume boost and sleep timers. Its silence trimming and loudness leveling serve different listening needs from reducing sibilance. [Podbean playback controls](https://help.podbean.com/support/solutions/folders/25000030866)
- Spotify offers audiobook speed and sleep controls. [Spotify audiobook playback](https://support.spotify.com/us/article/audiobooks-unlock/)
- Mariana's existing LibriVox integration provides public-domain books and their individual sections. [LibriVox catalog API](https://librivox.org/api/info)

## Follow-up work

| Feature | Status | Acceptance |
|---|---|---|
| Native pitch-preserving listening speed | Available on finite, seekable tracks. | `speed 0.8`, `speed 1.25`, `speed 1` and `speed status`. Choose 0.5–2×. The current occurrence keeps its speed when paused or seeking. Each new recording starts at 1×. |
| Silence shortening | Pending | Needs a variable mapping between source and listening time. |
| Per-show listening presets | Open | Preferences follow a stable feed ID, with a visible per-show override. |
| Electron local spoken-file selection | Open | User can identify an arbitrary local recording as spoken and revoke the setting. Web and phone controls already work on imported files. |
| Audio review and mobile parity | Open | Test stereo, mono, listener bypass and partial-track skips with real episodes on devices. |

The native player changes speed at an audio block boundary. FFmpeg prepares the replacement decoder while the current one stays audible. Track time, seeks, captions, video and preferred regions use source seconds. A new item reached by crossfade starts at its normal rate. Wait for an active crossfade to finish before adjusting its incoming item. Restore 1× for verified session-recipe recording, prepared stem monitoring or fingerprint capture. DJ deck rate remains independent.

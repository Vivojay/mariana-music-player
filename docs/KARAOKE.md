# Singing with Mariana

Play the supplied six-second original duet with `karaoke demo` in the native player. Space pauses or resumes the transport. Left and Right jump to lyric lines, Tab switches the highlighted singer, and Q returns to the session. `karaoke start` opens the singing view for a loaded recording. In the TUI, press `:` before entering a Mariana command. In Electron use the Karaoke surface or the embedded terminal. In the portable player, including Flow, choose Karaoke and the practice duet.

| Native command | Result |
| --- | --- |
| `lyrics voices "duet.ttml"`, `lyrics voices` | Import or read singer-labelled lyrics as plain text. Unscored timing can still supply readable lyrics while Karaoke remains unavailable. |
| `karaoke status` | Shows availability, whole-recording timing score, or the first unmet requirement. |
| `karaoke current`, `karaoke singers` | Shows the current multi-singer line or the names of participating voices. |
| `karaoke part Alto`, `karaoke part all` | Emphasizes a chosen part, or both sides of a duet. Repeated and overlapping words have independent timing for each vocalist. |
| `karaoke next`, `karaoke previous` | Seeks the actual player to the next or preceding sung phrase. During an instrumental the stage indicates what comes next. |
| `karaoke import "duet.json"` | Binds a score to the exact loaded recording. Native playback also recognizes a sibling named, for example, `Track.flac.karaoke.json` beside `Track.flac`. |
| `karaoke compare "session.ttml" "independent.ttml"` | Builds a score from two independently prepared word-timed transcriptions of this recording. The result is saved for the current audio. |
| `karaoke export "duet.json"` | Writes an eligible score to a new file. Import the same media file and score into another client to use the same timings and singer labels. |
| `karaoke clear` | Forgets the imported score for this recording and suppresses automatic sidecar loading until another import. |
| `karaoke vocals off`, `karaoke vocals on` | On the native transport, listens to prepared instrumental stems or restores the original mix. `stems prepare` uses Mariana's existing optional local separator. Preparation status and failures appear in `stems status`. |

## Invite someone to practice a part

1. Load an eligible recording and seek to the line where the other singer should start.
2. At the Mariana prompt or inside the TUI, enter `karaoke invite "practice.duet.json" Tenor`. Omit the singer to use your currently selected part, or use `all` for all voices. A new invite file carries the vocalist label, start time, duration, recording fingerprint and timing fingerprint. Audio, lyrics, local paths, account details and messages stay out of the invitation.
3. Share the JSON file. The other singer loads their own matching recording and timing sheet, then runs `karaoke open "practice.duet.json"` to preview the cue. Only `karaoke accept` seeks the player and selects the part. Accepting preserves the player's play/pause state.

The portable player can open and share the same invitation. Playback on each device is independent. Both sides must pass the 90% gate. Changing the recording, word timing or vocalist assignments invalidates the invitation. The recipient can supply the same timing independently, with its own qualifying confidence. An invite can name a singer exactly as printed in the score, so use a stage name when the part will be shared publicly.

## When the stage is available

A score must match the SHA-256 of the actual local media bytes, and the known playback duration must agree within 250 milliseconds. Retagging a file or using a different encode changes its digest. Every millisecond must belong to a segment extending from zero to the declared end, with explicit empty-voice segments for instrumental sections. Each sung word must specify start, end, singer and confidence. Word times may overlap across voices. A singer’s own words must be ordered. High-scoring first verses cannot conceal a weak final word or an uncovered outro.

The threshold is **90% inclusive**. Mariana takes the lower of the whole-recording score and every individual word score. A supplied score records the source's stated confidence. It does not certify an independently measured probability that the transcription is right. A listener can inspect the source before trusting its values. The bundled duet's score is exact because its vocal sounds and word timings were generated on the same sample clock. Plain lyrics and line-only LRC files have insufficient word or speaker evidence. Changing the lyric display offset or splitting text evenly cannot qualify a file.

`lyrics detect OUTPUT.json` and `speech transcribe OUTPUT.vtt` can draft time-coded lyrics and speaker-labelled captions for review. Transcription confidence remains separate from verified karaoke confidence. Drafts use a separate schema and cannot enter the practice stage. [Transcription setup](LIVE_SPEECH.md#draft-a-transcript-for-a-recording)

The portable and native stages use the same schema and half-open timing windows (a word stops highlighting at its end). They read the existing playback clock, including pauses and seeks. Streaming services that withhold media bytes or rights-cleared timing data, live radio, and files with an unknown duration show an availability reason. Mariana does not fetch or copy proprietary Apple Music Sing lyrics. Users provide the recordings and timing data they have permission to use.

## Working with ordinary TTML

Use two transcriptions of the same full recording from independent alignment passes or editors. `karaoke compare` accepts bounded UTF-8 TTML with a standard TTML namespace, a media clock, and an explicit duration or end for the entire `body`. Use explicit word-level `span` elements, `p` verse lines, and `ttm:agent` references. An optional metadata agent name becomes the display label. Each element's times are relative to its enclosing timed interval. Seconds, milliseconds and media-clock expressions are supported. Frames, tick timing, timed sequences, inline untimed lyric text, and group or missing word boundaries are rejected. Both full timelines must explicitly identify the instrumental passages between timed paragraphs, including lead-in and outro. For example, `<p begin="0s" end="3s" ttm:role="x-instrumental"/>` marks a three-second introduction. An uncovered section, a sung word in an instrumental interval, or a vocal paragraph containing an unexplained gap over two seconds makes the evidence insufficient. Many publisher TTML files omit instrumental declarations and need editorial review before this comparison can cover the whole song. Division into verse lines may differ between the two files. Each singer's complete word sequence must agree.

For each matched word, the comparison takes the larger start or end disagreement in milliseconds. Its score is `max(0, 1 − disagreement / 1000)`. To pass 90%, every start and end must agree within 100 ms. Both declared durations must agree. Identical timing copies, unmatched words, missing singers and divergent full durations cannot establish corroboration. This is a measure of **agreement between supplied transcriptions**. Two transcriptions can share a systematic error. This workflow does not perform acoustic forced alignment, infer singers from audio, identify vocal pitch, obtain licensed scores, or estimate a calibrated accuracy probability. Use separate, independently prepared sources.

## Portable score format

The playable example and full interoperable sheet live in `res/karaoke/practice-duet.wav` and `res/karaoke/practice-duet.json`. The following abbreviated example describes a 2-second clip with 500 ms of instrumental lead-in. Replace the example digest with the actual SHA-256. In PowerShell use `(Get-FileHash -Algorithm SHA256 -LiteralPath '.\track.wav').Hash.ToLowerInvariant()`.

```json
{
  "schema": "mariana.karaoke.v1",
  "media_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "duration_ms": 2000,
  "source": "Name of the alignment provider or reviewed score",
  "confidence": 0.97,
  "segments": [
    {"start_ms": 0, "end_ms": 500, "voices": []},
    {"start_ms": 500, "end_ms": 2000, "voices": [
      {"singer": "Alto", "words": [{"text": "Ah", "start_ms": 500, "end_ms": 1500, "confidence": 0.95}]},
      {"singer": "Tenor", "words": [{"text": "Oh", "start_ms": 800, "end_ms": 2000, "confidence": 0.94}]}
    ]}
  ]
}
```

Native import accepts up to 2 MiB per document, 10,000 segments and 16 simultaneous vocal parts per segment. Standard Windows/macOS terminals, physical output, voice separation quality and licensed third-party alignments still require acceptance testing. Watch playback and separate offline phone installations require platform-specific acceptance. See the [release status](PLAYER_EXPANSION_STATUS.md).

## Browser, Flow and phone players

Choose **Try a duet** to load the bundled Alto and Tenor practice track. Both parts are synthesized from the same word schedule as the timing sheet. Tap **Sing along with** to select a part and **Previous line** or **Next line** to rehearse it. Switching between Flow and Console keeps playback and the selected singer. The stage carries plain-text singer names, a distinct current-word underline, advance cues and one screen-reader announcement per phrase.

For a recording of your own, add the local media, then choose **Import timing sheet** or **Compare two TTML files**. The comparison accepts the word and instrumental coverage described above. **Save timing sheet** exports the resulting JSON. The selected recording and its verified sheet can be reopened offline when the browser grants device storage. Local browser scores use the file’s SHA-256 and the same duration tolerance and 90% gate as the native player. A score below 90% still provides singer-attributed plain text. Hosted streams can use **Import singer-labelled lyrics** for reading. Word highlighting requires a verifiable local recording.

**Vocal mix** accepts an isolated vocal stem from the exact mix you loaded. Choose 100%, 75%, 50%, 25% or Off. The browser decodes the original and stem at the same rate, checks channel layout, sample length and positive zero-lag correlation, then subtracts the selected amount per sample and switches the current player to the adjusted mix. Original restores the source. Use a sample-aligned, unscaled stem. Mastering or lossy encoding can leave residual voices. This local control supports mono/stereo recordings up to five minutes and 64 MiB per input file. The stem is session-only. Native stem preparation on a supported desktop remains available for creating isolated parts. Physical phone playback and context-specific file export still require device acceptance.

### Send a duet practice invite

In **Duet invites**, choose **Create invite**, then **Save invite** or **Share invite** when the browser can share JSON files. The invite captures the selected part and current position. The recipient loads the same recording and timing sheet, opens the invite to preview its part and timestamp, then selects **Apply part and position**. This also works between the portable player and native CLI. Applying an invite keeps the current play/pause state. Only the media and timing digests, duration, part name and start time are exchanged. Each side checks its own karaoke eligibility.

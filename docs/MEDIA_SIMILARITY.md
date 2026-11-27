# Find similar local media

Press `:` in the TUI or type these commands at the Mariana CLI prompt.

| Command | Result |
| --- | --- |
| `similar` | Find items related to the current indexed local recording using both available audio and metadata, with recording matches first. |
| `similar 17 --mode tags --limit 8` | Rank library items using the artist, album, title, genre and profile tags on item 17. |
| `similar current --mode fingerprint` | Find alternate files with a matching indexed Chromaprint fingerprint or sampled file signature. |
| `similar scan --limit 20` | Analyze pending local files in a bounded batch. Repeat the command to cover more of the library. |
| `similar scan 17` or `similar scan current` | Prioritize analysis of one reference track. |
| `similar 17 --mode audio` | Compare sound after item 17 and other tracks have acoustic profiles. |

The first column is the library number, so a result can be opened with `play <number>`. The numerical score orders results within a mode. The explanation names evidence used for that result. Blocked, missing and changed files are excluded. Use `library scan changed` to refresh a changed file before running `similar scan` again.

Tag mode works as soon as relevant metadata is present. Acoustic mode samples up to 12 seconds of the first audio stream with local FFmpeg. For longer tracks the excerpt begins near the first quarter, capped at 90 seconds. It compares normalized spectral-band energy and, where measurable, recurring onset patterns. This works for video files with audio. The extracted audio stays in memory during analysis. Only compact numerical profiles and their file revision stay in the active listener's database. A batch analyzes up to 50 items and has a 12-second scheduling budget. Use `similar scan --retry` after resolving decoding issues. Silent, very short and unsupported files can still use tag mode when metadata is available.

Hybrid mode first ranks matching fingerprints or sampled file signatures, then combines available acoustic and tag scores. Fingerprint equality is a recording-match hint. It can miss trims, performances and transformed encodes. Spectral and rhythmic similarity can find related textures without metadata. Melody, mood, language and visual semantics require different models and are not part of the acoustic profile.

## In paired Flow

Run `web session flow` in Mariana and select **Show my library and collections in this tab** when you connect. In **Local library**, choose **Similar** next to a recording. You can also choose **Find similar** under the player while an indexed local item is loaded.

Choose audio and tags, audio, tags, or fingerprint to see up to 20 matches with their scores and matching evidence. Use **Play** or **Queue** on a result. **Analyze next 12 tracks** asks the native session to index a batch, then refreshes the matches. Type `similar scan current` in Console to prioritize the playing item. Browser commands follow the session approval policy.

The standalone web player has a separate, browser-owned library. The acoustic index and matching for native recordings run on the paired host without an account or network requests.

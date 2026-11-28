# Clip a recording and share it

With a recording loaded in Mariana, mark the moment you want to share. The player can be paused while you set either mark or render the clip. Exporting uses a separate decoder and leaves playback at its current position.

| At the Mariana prompt or in the TUI command bar | Result |
| --- | --- |
| `clip start`, then `clip end` | Capture the current playhead at each end. |
| `clip start 0:12.250`, `clip end 0:28` | Set one boundary explicitly. |
| `clip range 12.250 28` | Set both ends together on the loaded media. |
| `clip link` | For a loaded YouTube or YouTube Music recording, copy the printed canonical watch link at the selected start or current playhead. Only the video ID and whole-second timestamp are included. Live broadcasts get the canonical link. |
| `clip status`, `clip clear` | Inspect the title, marks and current position, or clear the selection. |
| `clip export "D:\Music\My clip.wav"` | Save a new file using the extension to select the format. |
| `clip export --format mp3` | Write an automatically named MP3 in the Mariana data directory's `clips` folder. |
| `clip share` | Export the selected range and open the file handoff in the default browser. |
| `clip share --format story` | Create a 720 × 1280 H.264 MP4 for a video-based destination. |

The native renderer re-encodes the selection with FFmpeg. Auto uses AAC in M4A for an audio recording and H.264 in MP4 for video. WAV preserves decoded PCM with 16-bit samples. MP3 provides a smaller audio attachment. For a Story, landscape video fits inside the vertical frame with padding. Audio receives a moving waveform and the original sound. Encoded video and compressed audio use their ordinary frame boundaries. Marks refer to the original source timeline. Live equalization, lyrics, a local stem monitor and other listening effects are independent of this export.

Native clipping accepts local audio/video and seekable finite HTTP(S) podcast enclosures or direct media URLs that allow downloading and expose the media directly. The source must report a duration to the player. For YouTube and YouTube Music, `clip link` shares a timestamp without exporting audio. The end mark applies only to an exported file. Protected services, web watch pages, logged-in resolver streams and live broadcasts require a different file-sharing route. Import a compatible local copy when available. Local file replacement and track changes invalidate old marks. Existing exports are preserved when choosing a name.

## Share on the device

On the local handoff page, preview the exported file and select **Share file…**. The browser checks the actual file against its Web Share capabilities and shows the operating system's eligible destinations. Choose a destination, audience, edits and final posting action in that app. Video handoffs also link to Instagram, Snapchat, TikTok and YouTube Studio for manual attachment. **Save clip** works when the browser or receiving app cannot take the file through the OS picker. Handoffs run on this computer's loopback interface for ten minutes while Mariana is open. The exported file remains available in the printed location.

The portable Console and Flow player have their own clip renderer using browser media APIs. Imported audio can be exported as WAV. Check the in-app media-type and recording support on the current device for portrait video. Native commands and the portable player share range-marking semantics. FFmpeg and native codec choices are available in the desktop/CLI host.

## Acceptance status

| Scope | Verification or remaining work |
| --- | --- |
| Native codec paths | Real FFmpeg tests exercise sample boundaries, local and HTTP audio, a video with audio, and a vertical waveform. File export and stale-source checks run without an audio device. |
| Share sheet and destination | The picker is capability-checked at runtime. Real signed-in handoffs to Instagram, Snapchat, TikTok and other receiving apps on Windows, macOS, Android and iOS require device acceptance. Installed apps, region, target MIME type and account settings can change the choices. |
| Provider publishing | The handoff opens the user's selected app or web composer. Direct provider uploads, destination-specific drafts and their review requirements are tracked separately from file sharing. |

Sources include [YouTube timestamp sharing](https://support.google.com/youtube/thread/425735532), [Web Share API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Share_API), [Snapchat web uploader](https://help.snapchat.com/hc/en-us/sections/5689704401300-Posting-Snaps-with-Web-Uploader), [TikTok upload](https://www.tiktok.com/upload), [YouTube Studio uploads](https://support.google.com/youtube/answer/57407).

On the phone shells, **Share a music link** and `clip social` hand a normalized public music link to the OS share sheet. Mariana uses the loaded recording’s official link or lets you paste one. Exported clip files use the separate file-sharing action.


## Public link sharing

Use `clip social` in the CLI, TUI or portable Console, or choose **Share a music link** in the portable clip editor. With an eligible YouTube recording, the public composer uses the start mark or playhead. For a different recording, paste a public page from YouTube, Spotify, Apple Music, TIDAL, Bandcamp, SoundCloud or MusicBrainz. The composer removes unrelated query parameters. Copy a link, use the system chooser, or choose Facebook, WhatsApp or Snapchat. The Snapchat web integration loads only after selection and uses a separate sandboxed frame. Phone wrappers use the system share sheet for public links. File destinations for actual audio and video are described in [portable clips](WEB_CLIPS.md).

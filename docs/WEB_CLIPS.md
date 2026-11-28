# Share a clip from Mariana

Open **Clip & share** next to Play in either Console or Flow. The editor starts with a 15-second selection near the playhead. Play, pause or seek the recording and use **Mark in here** or **Mark out here**. Both fields also accept seconds, `m:ss.mmm` and `h:mm:ss.mmm`.

Choose an output and press **Prepare clip**. Preview the exported file or use **Share clip…** to send it to a compatible app. On browsers without file sharing, choose **Download clip** and pick the saved file in the destination app. Preparing a clip keeps the current playhead intact. Starting the preview pauses the main player. Changing the track, marks or format discards the previous export. Nothing is uploaded when you prepare a clip.

| Output | How Mariana creates it | Limits and availability |
| --- | --- | --- |
| Audio clip | A PCM WAV cut at the selected sample frames. For mono or stereo integer PCM WAV, Mariana copies the original sample rate, bit depth and bytes. Other supported formats are decoded locally to 48 kHz and exported as 16-bit PCM. | Browser-decodable mono or stereo audio, up to 32 MiB per output. For compressed inputs the source limit is 96 MiB and 30 minutes. Local PCM WAV can be sliced without loading the full file. |
| Portrait video | A 720 × 1280 title card with the track name, active theme and selected audio waveform, rendered with the selected recording. | Up to 90 seconds and 32 MiB. Requires Web Audio, canvas capture and MediaRecorder. The browser chooses supported MP4 first, then WebM. Keep the tab in the foreground for the duration of the render. |
| Original video | Re-encodes the selected moving pictures and original audio through a separate video element. Preserves aspect ratio and scales the longest edge to at most 1280 pixels. | Up to 90 seconds and 32 MiB, browser-decodable video, real-time rendering. Source cuts follow playback frame timing. Use the native FFmpeg export for precision editing, longer selections or unsupported codecs. |
| YouTube timestamp link | **Copy YouTube timestamp link**, or `clip link 1:23`, reconstructs an official watch link with the video ID and start second. | Official watch, Shorts, embed or youtu.be URLs. This can be shared even when the static browser player cannot play a YouTube page. |

Online audio/video export requires a finite media file that its host allows the browser to fetch without credentials. A share link, subscription stream or protected playback session may offer no readable media bytes. Local files and generated tones work offline. Use the native [clip commands](CLIP_SHARING.md) for supported desktop sources.

## Console

```text
clip
clip start
clip end 1:24.250
clip range 0:40.100 0:51.900
clip export --format wav
clip export --format story
clip export --format video
clip share
clip link 40
clip clear
```

`clip status` shows the current selection. The first share command can prepare a file. The visible Share button or a second `clip share` supplies the explicit user gesture required by the browser.

## Where the file goes

| Surface | Handoff |
| --- | --- |
| Web/PWA | The browser checks file sharing with `navigator.canShare({files})`. Its system sheet lists eligible installed apps. Downloads provide a fallback. The website cannot enumerate or force installed apps. |
| Android phone | The bundled WebView transfers the prepared file in bounded chunks over an origin-scoped message port. Mariana grants temporary read access to one cache file using FileProvider. **All apps** opens the Android chooser. The destination selector checks Instagram, Snapchat and the supported TikTok package variants for an activity that handles this exact MIME type. |
| iPhone and iPad | The bundled main document uses a WebKit reply handler to transfer the prepared file and presents UIActivityViewController, including Save to Files when the system offers it. Individual share extensions and accepted formats depend on the installed apps. |
| Instagram Stories on phones | **Instagram Stories** opens Meta’s composer with a portrait video of up to 20 seconds. Android uses the Stories intent with a file URI grant. iOS uses the Instagram Stories URL scheme and an expiring, device-only pasteboard item. The app must be installed and the publisher must configure their Meta app ID. The selector shows the reason when the destination is unavailable. |
| Watches | Handheld media editors and recipient compose screens require a phone, browser or desktop. The existing watch players do not encode clips. |

Android packagers can set the `marianaMetaAppId` Gradle project property. For iOS, set the `MARIANA_META_APP_ID` Xcode build setting for the MarianaPhone target. Listeners do not supply app credentials. Generic system sharing and Android’s compatible ordinary send targets work independently of this optional publisher setting. The receiver owns editing and publishing. Handing a file to an app does not confirm a post.

See the [Web Share file capability reference](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/canShare), [Android Sharesheet documentation](https://developer.android.com/training/sharing/send), [FileProvider reference](https://developer.android.com/reference/androidx/core/content/FileProvider), [WebKit message handler reference](https://developer.apple.com/documentation/webkit/wkscriptmessagehandlerwithreply) and [Instagram Stories integration documentation](https://developers.facebook.com/docs/instagram-platform/sharing-to-stories/).

## Acceptance

- Automated checks exercise sample bytes, bounds, stale selection cancellation, queued media identity, recipient checks, bounded Android and iOS transfer ordering and simulated video capture. A real 24-bit PCM source was cut and its output duration and format independently read with FFprobe.
- A Playwright test covers importing/generating media, preparing from Flow and handing the real resulting WAV to a test share handler. Run it where Chromium can start.
- Physical Android and iOS share sheets, receiver app versions, actual MediaRecorder portrait/original video output and recipient codec acceptance still require device testing. Native SDK builds and a signed Meta publisher configuration are part of that acceptance.

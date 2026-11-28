# Duet practice on a watch

Open **Practice duet**, then press **Play**. The six-second original recording and its timing sheet are bundled with the Apple Watch and Wear OS apps, including Wear OS Galaxy Watches. Each voice appears on its own labelled line. Bold underlining follows the sung word, including both lines during the overlapping phrase. Pause or scrub the duet to rehearse a particular entry.

**Mark start here** and **Mark end here** capture the current playback position. Scrubbing while paused lets you mark both ends without replaying the phrase. On an Apple Watch choose **Prepare clip** and **Share WAV**. On Wear OS choose **Share selected WAV**. This exports the selected PCM samples and offers compatible installed share activities. A receiving app determines which destinations are available. Both marks initially cover the entire duet.

Both apps load the same packaged WAV and JSON used by the portable and native players. They check SHA-256, duration (250 ms tolerance), full contiguous segment coverage, word ordering and a minimum 90% score across the recording and every word. Playback highlights follow AVPlayer time or MediaPlayer position. The watch continues to play an entered HTTPS stream and shows why its lyrics are unavailable.

| Capability | Watch status |
| --- | --- |
| Offline multi-singer rehearsal, pause and scrubbing | Implemented for the supplied duet on both watches. |
| Selected-range WAV export | Implemented for the packaged duet. On Wear OS, file grants are limited to the exported clip cache. watchOS sends WAV bytes using a transferable share item. |
| Imported scores, external recordings, linked accounts, native desktop companion and social platform SDKs | Available on other surfaces according to the [surface guide](SURFACE_PARITY.md). Watch implementations and phone handoff are pending. |
| Physical device acceptance | Test actual audio routes, interruptions, seeking and word alignment on a round Wear OS device and Apple Watch. Verify WAV delivery to whichever share activity is actually installed. |

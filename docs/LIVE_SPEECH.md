# Record a microphone or jam session

Mariana starts with the microphone off. Choose the source that you want in the resulting file.

| Source | Where to start | What the export contains |
| --- | --- | --- |
| Speech, rehearsal or interview on your microphone | Native `speech record` or **Microphone studio → Record microphone** in Console or Flow | Audio from the selected operating-system microphone. Playback and remote room tracks have independent audio paths. |
| Microphone with live captions | Native `speech start MODEL_DIRECTORY` or **Record with captions** on a compatible browser | The microphone recording and separate, editable TXT or WebVTT captions. |
| A multi-person jam heard in a browser tab | **Microphone studio → Record a jam with other performers** on a desktop browser with tab-audio sharing | A stereo audio mix of the selected tab and your microphone. |
| A performance on the portable DJ decks | Use the master recording control in the DJ panel | The deck master output. |

## Try the native recorder

In the Mariana prompt, including the TUI command editor or Electron terminal, enter `speech record`, say a sentence, and enter `speech stop`. The result gives the path to a mono, 16 kHz PCM WAV under Mariana's `speech` state directory. Each take gets its own filename. Listen to it in the player or use `speech share` to open the system browser handoff. To make a separate copy, use a new destination name.

```text
speech export "D:\C DOWNLOADS\Mariana rehearsal.wav"
```

Recording uses the default input device via the project's sounddevice dependency and requires a working PortAudio input at 16 kHz. Windows users can select their preferred microphone and allow desktop-app microphone access in system settings.

For optional offline captions, install Vosk into the same Python environment as Mariana and extract a model for the spoken language. The model directory contains its acoustic and language model files. For a source checkout, these PowerShell commands use the repository interpreter if you have activated its virtual environment. Then run Mariana as usual. [Vosk installation](https://alphacephei.com/vosk/install) · [Language models](https://alphacephei.com/vosk/models)

```powershell
python -m pip install vosk
$env:MARIANA_VOSK_MODEL = 'D:\C DOWNLOADS\vosk-model-small-en-us-0.15'
```

```text
speech start
speech speaker Jay
speech live
speech stop
speech export "D:\C DOWNLOADS\Mariana interview.vtt"
speech export "D:\C DOWNLOADS\Mariana interview.txt"
```

Press **S** in the live view to stop the microphone or **Q** to return to the command prompt while recording continues. Use `speech text` to inspect the latest words without opening the live view. Set each speaker's name **before** they begin speaking. Vosk provides recognized word times, and Mariana labels each utterance using the name in effect at its first word. Final VTT and plain-text transcripts are saved beside the WAV if any phrases were recognized. Use `speech share vtt` or `speech share txt` to share either file directly. With a paired browser workspace the native microphone belongs to the host computer.

## Draft a transcript for a recording

Load a local audio or video file, then enter `speech transcribe "My captions.vtt"` inside the CLI, TUI or Electron terminal. `lyrics detect "My captions.json"` uses the same workflow. It extracts the first audio track through FFmpeg and accepts up to 30 minutes of audio. A stopped, paused or playing local file works. Use a new destination filename. JSON retains available per-word timings, language and speaker evidence. WebVTT gives you time-coded captions with speaker labels.

The default backend uses **whisper.cpp** locally. Install an upstream release and download a multilingual GGML model separately. A quantized multilingual Tiny model such as `ggml-tiny-q5_1.bin` reduces memory and download size. Use a stronger model when the draft misses words. The `.en` variants only support English. The CLI and model are optional host files. [whisper.cpp releases](https://github.com/ggml-org/whisper.cpp/releases) · [Upstream models](https://huggingface.co/ggerganov/whisper.cpp/tree/main)

```powershell
$env:MARIANA_WHISPER_CLI = 'D:\C DOWNLOADS\whisper\whisper-cli.exe'
$env:MARIANA_WHISPER_MODEL = 'D:\C DOWNLOADS\whisper\ggml-tiny-q5_1.bin'
```

Set the variables in the shell that launches Mariana. If `whisper-cli` is already on PATH, only the model variable is required. Enter the following inside Mariana.

```text
speech transcribe "D:\C DOWNLOADS\captions.json"
speech transcribe "D:\C DOWNLOADS\Hindi captions.vtt" --language hi
```

The local backend returns phrase times and one recording-level language when reported. Choose `--language auto` for the default automatic language selection. Individual speaker identities and languages are unknown on this backend.

For **automatic spoken-language changes and speaker labels** in a mixed recording, supply your own Deepgram API key as the `DEEPGRAM_API_KEY` environment variable before starting Mariana. Do not enter it into the player. The call sends normalized mono audio when you explicitly include `--send-audio`, and may use paid quota. It never falls back to a hosted backend automatically. `--language hi` can optionally hint at the language while allowing code-switching. [Deepgram supported languages](https://developers.deepgram.com/docs/nova-3-language-prompting) · [Diarization and confidence](https://developers.deepgram.com/docs/diarization)

```text
speech transcribe "D:\C DOWNLOADS\Transcript draft.json" --backend deepgram --send-audio
```

Deepgram's numeric speaker IDs are anonymous estimates. Word and speaker confidence are separate provider fields. Missing fields remain unknown. Heavy music, simultaneous voices and singing require review. Both engines produce drafts. The karaoke stage requires a verified, complete timing sheet. [Karaoke evidence](KARAOKE.md#when-the-stage-is-available)

In standalone Console or Flow, load the same audio or video, go to **Library → Transcript**, then choose **Import captions for this file**. Read, search and click any timestamp to seek. The import stays in that browser session. Processing runs in the native app, so there is no browser credential prompt.

## Try Console or Flow

Run this from the repository, then open **Microphone studio**.

```powershell
python tools/build_web_player.py --serve --open --view flow --port 8767
```

**Record microphone** keeps the recording local. **Record with captions** requires a separate consent checkbox for each take. Some browsers process speech on a recognition service, and availability depends on the browser, language, device and connection. Choose a language tag such as `en-IN` or `es-ES` and set the speaker label before the next utterance. A caption service can end before the audio recorder finishes. The status shows when voice recording continues. [Browser speech recognition](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition) · [MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)

After **Stop microphone**, preview the audio, choose **Audio recording**, **Timed captions** or **Transcript**, then **Save** or **Share**. In Console you can also enter `speech record`, `speech stop` and `speech export audio`. Save before the next completed take or before leaving the page. Audio stays in memory until export, and the recorder automatically stops at approximately 24 MiB. Browser exports use a supported audio format such as WebM/Opus or M4A. On phones, use the native share sheet to save or send files.

### Record the remote performers and your microphone together

1. Open the jam in a browser tab and use headphones so that the speakers do not feed back into the microphone. Confirm that everyone agrees to the recording.
2. In the studio, open **Record a jam with other performers**, tick the participant permission box, then choose **Record shared tab audio + my microphone**. Console also accepts `speech jam` after the checkbox is selected.
3. In the browser picker, choose the tab that is playing the remote participants and enable **Share tab audio**. Allow microphone access when prompted. Mariana checks that the selected surface is a browser tab and supplies an audio track. If the tab has no audio track, the recorder closes the share and asks you to select again.
4. Speak locally while a remote performer speaks. Choose **Stop microphone** or use the browser's **Stop sharing** control. Play back the result, then save or share **Audio recording**. Check that you hear both performers.

The browser's share dialog requests a display surface. Mariana disables the selected video track and sends only the Web Audio stereo mix to the recorder. The source nodes connect to the recorder with equal headroom and no local monitoring. Stopping, revocation or the end of an input closes both sources. A jam recording contains one mix. Individual participant tracks, automatic room-wide consent collection and speaker recognition for remote participants remain open. Tab capture depends on the browser and OS; phone WebViews and watch clients have no supported tab-sharing workflow. [Display capture API](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia)

## Verification and remaining work

| Area | Verified | Remaining acceptance |
| --- | --- | --- |
| Native recording | Automated tests stream known PCM through the capture worker, open the resulting WAV, verify all samples in the test block, and cover stop, sharing, permission failure and overflow. | Physical microphones, device interruptions, default sample-rate support and an installed Vosk model on Windows, macOS and Linux. Frozen executables currently require a separately integrated Vosk runtime for offline captions. |
| Live words and speaker labels | Tests exercise interim and final results, cue export, entity escaping and manual turn labels. Native and browser code retain audio when caption support is absent. | Browser cue times are approximate recognition-event times. Cues may combine speakers in a single utterance. Live automatic diarization, sung-voice recognition and calibrated transcription accuracy remain open. Machine captions do not unlock verified karaoke. |
| File drafts | A test extracts stereo input to mono 16 kHz audio through actual FFmpeg. Provider fixtures exercise mixed Hindi and English, speaker turns, invalid ranges and unreported evidence. Browser tests check draft import, search and timestamp binding. | Calling Deepgram with a real account, measuring recognition with a separately installed whisper.cpp model, and production quality benchmarks for sung or overlapping voices. |
| Web and phone recording | Adapter tests cover separate recognition consent, grant cancellation, audio file handoff and WebVTT/TXT sharing. Android permission handling and iOS usage strings are included. | Physical phone recording, actual recognition services, share destinations, long takes and browser-specific codecs. Headless Chromium could not start under the runner's socket policy. Native watch capture remains open. |
| Multi-person tab capture | Deterministic tests check two distinct inputs, equal gain, recorder-only routing, an audio-only output, participant consent and teardown. Missing tab audio, an incorrect surface, mic denial and cancellation after choosing a tab are exercised. | End-to-end capture with two people and real browser tab selection on each target desktop OS. Recording a server-side room or a meeting running outside a browser tab remains open. |

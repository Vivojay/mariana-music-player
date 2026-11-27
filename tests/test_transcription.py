from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from mariana import transcription as speech


WHISPER_SAMPLE = {
    "result": {"language": "hi"},
    "transcription": [
        {"offsets": {"from": 750, "to": 1850}, "text": "  नमस्ते दुनिया। "},
        {"offsets": {"from": 2100, "to": 2920}, "text": " मैं ठीक हूँ। "},
        {"offsets": {"from": 3200, "to": 3100}, "text": "Invalid range."},
    ],
}
DEEPGRAM_SAMPLE = {
    "results": {"channels": [{
        "alternatives": [{
            "confidence": 0.99,
            "languages": ["en", "hi"],
            "words": [
                {"word": "hello", "punctuated_word": "Hello.", "start": 0.2, "end": 0.5,
                 "speaker": 0, "language": "en", "speaker_confidence": 0.71, "confidence": 0.99},
                {"word": "नमस्ते", "punctuated_word": "नमस्ते।", "start": 0.6, "end": 0.95,
                 "speaker": 1, "language": "hi", "speaker_confidence": 0.58, "confidence": 0.89},
                {"word": "ठीक", "start": 1.2, "end": 1.4, "speaker": 1, "language": "hi"},
                {"word": "मित्र", "start": 1.4, "end": 1.6, "speaker": 1, "language": "hi"},
                {"word": "good", "start": 1.7, "end": 2.05, "speaker": 1, "language": "en"},
                {"word": "bye", "start": 2.06, "end": 2.6},
                {"word": "invalid", "start": 2.71, "end": 2.6, "speaker": 1},
            ],
        }],
    }]},
}


class TranscriptionTests(unittest.TestCase):
    def test_language_and_provider_requirements(self):
        self.assertEqual(speech.parse_request(["text.json"]).backend, "whisper")
        with self.assertRaisesRegex(ValueError, "--send-audio"):
            speech.parse_request(["text.json", "--backend", "deepgram"])
        with self.assertRaisesRegex(ValueError, "language code"):
            speech.parse_request(["text.json", "--language", "hi?other=value"])
        with self.assertRaisesRegex(ValueError, "only once"):
            speech.parse_request(["text.json", "--language", "hi", "--language", "en"])
        req = speech.parse_request(["text.json", "--language", "hi-IN", "--backend", "deepgram", "--send-audio"])
        self.assertEqual((req.language, req.send_audio), ("hi-in", True))

    def test_whisper_preserves_multilingual_phrase_times_and_unknowns(self):
        draft = speech.parse_whisper(WHISPER_SAMPLE, 2.9)
        self.assertEqual(draft["languages"], ["hi"])
        self.assertIsNone(draft["transcriptConfidence"])
        self.assertTrue(draft["reviewRequired"])
        self.assertEqual(draft["segments"][0]["body"], "नमस्ते दुनिया।")
        self.assertEqual(draft["segments"][0]["startTime"], 0.75)
        self.assertEqual(draft["segments"][-1]["endTime"], 2.9)
        self.assertIsNone(draft["segments"][0]["speaker"])
        self.assertIsNone(draft["segments"][0]["language"])
        with self.assertRaisesRegex(ValueError, "No timed"):
            speech.parse_whisper({"transcription": [None]}, 3)

    def test_cloud_preserves_per_word_speaker_and_language_evidence(self):
        draft = speech.parse_deepgram(DEEPGRAM_SAMPLE, 3)
        first, second, changed_language, unknown = draft["segments"]
        self.assertEqual(draft["languages"], ["en", "hi"])
        self.assertEqual(draft["transcriptConfidence"], 0.99)
        self.assertEqual((first["speaker"], first["language"], first["body"]), ("Speaker 1", "en", "Hello."))
        self.assertEqual((second["speaker"], second["language"]), ("Speaker 2", "hi"))
        self.assertEqual(len(second["words"]), 3)
        self.assertEqual(second["words"][0]["speakerConfidence"], 0.58)
        self.assertEqual(second["words"][0]["confidence"], 0.89)
        self.assertEqual(changed_language["startTime"], 1.7)
        self.assertIsNone(unknown["speaker"])
        self.assertIn("<v Speaker 2><lang hi>नमस्ते।", speech._vtt(draft))
        self.assertNotIn("media_sha256", draft)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
    def test_local_media_export_with_real_ffmpeg_and_whisper_format_fixture(self):
        with tempfile.TemporaryDirectory() as work:
            directory = Path(work)
            media = directory / "local audio.wav"
            with wave.open(str(media), "wb") as wav:
                wav.setparams((2, 2, 48_000, 0, "NONE", ""))
                wav.writeframes(b"\x00" * 4 * 48_000 * 3)

            def run_backend(command, **options):
                if command[0].endswith("whisper-cli"):
                    with wave.open(command[command.index("-f") + 1], "rb") as normalized:
                        self.assertEqual(normalized.getparams()[:4], (1, 2, 16_000, 48_000))
                    self.assertEqual(command[command.index("-l") + 1], "hi")
                    output = Path(command[command.index("-of") + 1]).with_suffix(".json")
                    output.write_text(json.dumps(WHISPER_SAMPLE), encoding="utf-8")
                else:
                    subprocess.run(command, check=True)

            destination = directory / "draft.json"
            request = speech.parse_request([str(destination), "--language", "hi"])
            spool = directory / "temporary"
            with patch.object(speech, "_whisper_config", return_value=("whisper-cli", "model.bin")), \
                    patch.object(speech, "_run", side_effect=run_backend):
                saved, draft = speech.transcribe(media, request, ffmpeg=None, temporary=spool)
                self.assertEqual(saved, destination)
                self.assertEqual(draft, json.loads(saved.read_text(encoding="utf-8")))
                self.assertEqual(draft["duration"], 3.0)
                self.assertFalse(list(spool.iterdir()))
                with self.assertRaisesRegex(ValueError, "already exists"):
                    speech.transcribe(media, request, ffmpeg=None, temporary=spool)
                self.assertEqual(draft, json.loads(saved.read_text(encoding="utf-8")))

    def test_cloud_does_not_follow_redirects_and_uploads_normalized_audio(self):
        class FakeResponse:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def iter_content(self, nbytes):
                yield json.dumps(DEEPGRAM_SAMPLE).encode()

        def send(endpoint, **arguments):
            self.assertEqual(endpoint, speech.DEEPGRAM_URL)
            self.assertFalse(arguments["allow_redirects"])
            self.assertEqual(arguments["headers"]["Authorization"], "Token mock_key")
            self.assertEqual(arguments["data"].read(), b"RIFFtest")
            self.assertEqual(arguments["params"], {
                "model": "nova-3", "language": "multi", "diarize_model": "latest",
                "punctuate": "true", "language_hint": "hi",
            })
            return FakeResponse()

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "source.wav"
            audio.write_bytes(b"RIFFtest")
            try:
                import requests
            except ImportError:
                self.skipTest("requests unavailable")
            with patch.object(requests, "post", side_effect=send) as post:
                result = speech._deepgram(audio, "mock_key", "hi", 3, lambda: False)
                self.assertEqual(result["languages"], ["en", "hi"])
                with self.assertRaisesRegex(ValueError, "cancelled"):
                    speech._deepgram(audio, "mock_key", "hi", 3, lambda: True)
                post.assert_called_once()

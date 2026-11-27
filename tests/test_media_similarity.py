"""Regression checks for scoring, audio decoding and profile invalidation."""

import json
import shutil
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from mariana.database import MarianaDatabase
from mariana.media_similarity import RATE, find_similar, scan_library
from mariana.web_session import NativeSession
from mariana.web_similarity import browser_similarity


class LocalMediaSimilarityTest(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.directory = Path(workspace.name)
        self.database = MarianaDatabase(self.directory / "profile.sqlite")
        self.addCleanup(self.database.close)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO library_roots(root_id,path,path_key,kind) VALUES('root',?,?,'local')",
                (str(self.directory), str(self.directory)),
            )

    def add(self, key, *, hz=220, pulse=True, artist="", album="", title=None, signature=None, fingerprint=None):
        path = self.directory / f"{key}.wav"
        timeline = np.arange(RATE * 3) / RATE
        signal = .3 * np.sin(2 * np.pi * hz * timeline)
        if pulse:
            signal *= np.exp(-8 * (timeline % .5))
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            wav.writeframes((signal * 32767).astype("<i2").tobytes())
        info = path.stat()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO library_files(library_id,root_id,canonical_path,path_key,size,mtime_ns,"
                "extension,metadata_json,fingerprint,content_signature,updated_at) "
                "VALUES(?,'root',?,?,?,?,'.wav',?,?,?,0)",
                (key, str(path), str(path), info.st_size, info.st_mtime_ns,
                 json.dumps({"artist": artist, "album": album, "title": title or key, "duration": 3}),
                 fingerprint, signature),
            )
        return path

    def test_different_modes_and_blocked_media(self):
        self.add("seed", artist="María", album="Live", fingerprint="same")
        self.add("metadata", artist="MARÍA", album="live")
        self.add("duplicate", fingerprint="same")
        self.add("blocked", artist="María", album="Live", fingerprint="same")
        self.add("unrelated")
        with self.database.transaction() as connection:
            connection.execute("INSERT INTO blocked_media(stable_id,updated_at) VALUES('blocked',0)")
        _, results = find_similar(self.database, "seed", "hybrid")
        self.assertEqual([item.track.library_id for item in results], ["duplicate", "metadata"])
        self.assertEqual(results[0].reasons, ("matching Chromaprint fingerprint",))
        self.assertIn("same artist", results[1].reasons)
        _, results = find_similar(self.database, "seed", "tags")
        self.assertEqual([item.track.library_id for item in results], ["metadata"])
        _, results = find_similar(self.database, "seed", "fingerprint")
        self.assertEqual([item.track.library_id for item in results], ["duplicate"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for this acoustic fixture")
    def test_acoustic_index_ranks_related_audio_and_invalidates_changed_file(self):
        self.add("seed", hz=220)
        similar = self.add("sounds-alike", hz=230)
        self.add("similar-pulse", hz=2800)
        self.add("unrelated", hz=2800, pulse=False)
        ffmpeg = shutil.which("ffmpeg")
        self.assertEqual(scan_library(self.database, ffmpeg, library_id="seed").analyzed, 1)
        self.assertTrue(scan_library(self.database, ffmpeg, limit=1).stopped)
        result = scan_library(self.database, ffmpeg)
        self.assertEqual((result.analyzed, result.unavailable), (2, 0))
        self.assertEqual(scan_library(self.database, ffmpeg).analyzed, 0)
        _, matches = find_similar(self.database, "seed", "audio")
        self.assertEqual([item.track.library_id for item in matches], ["sounds-alike", "similar-pulse"])
        self.assertIn("similar audio spectrum", matches[0].reasons)
        self.assertEqual(matches[1].reasons, ("similar rhythmic pulse",))
        similar.write_bytes(b"replaced audio")
        _, matches = find_similar(self.database, "seed", "audio")
        self.assertEqual([item.track.library_id for item in matches], ["similar-pulse"])

    def test_reference_needs_audio_index_and_limits_are_validated(self):
        path = self.add("seed")
        with self.assertRaisesRegex(ValueError, "acoustic profile"):
            find_similar(self.database, "seed", "audio")
        with self.assertRaisesRegex(ValueError, "result limit"):
            find_similar(self.database, "seed", "tags", 0)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "library scan changed"):
            find_similar(self.database, "seed")

    def test_paired_similarity_requires_sharing_and_binds_actions_to_indexed_files(self):
        reference = self.add("seed", artist="María")
        match = self.add("match", artist="María", title="Related recording")
        self.add("not-shared", artist="María")
        paths = [reference, match]
        session = NativeSession()
        session.library = lambda: [("Reference", "María", None, reference)]
        session.library_path = lambda number: paths[number - 1] if 1 <= number <= len(paths) else None
        session.similarity = lambda source, _, mode, limit, key_for_path: browser_similarity(
            self.database, source or reference, mode, limit,
            library_paths=lambda: tuple(paths), key_for_path=key_for_path,
        )
        session.playback = {"occurrence": "current"}

        def request(route, bearer, **data):
            return session.request(route, bearer, data, [])

        invite = session.invite
        self.assertEqual(request("similarity", invite, occurrence="current")[0], 403)
        status, paired = request("pair", invite, library=True)
        self.assertEqual(status, 200)
        self.assertTrue(paired["similarity"])
        token = paired["token"]
        source = {"number": 1, "key": session.library_key(reference), "mode": "tags"}
        self.assertEqual(request("similarity", token, **(source | {"key": "é"}))[0], 400)
        self.assertEqual(request("similarity", token, **(source | {"limit": 21}))[0], 400)
        self.assertEqual(request("similarity", token, occurrence="previous")[0], 409)
        status, result = request("similarity", token, **source)
        self.assertEqual(status, 200)
        self.assertNotIn(str(self.directory), json.dumps(result))
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual((row["number"], row["title"], row["reasons"]), (2, "Related recording", ["same artist"]))
        self.assertEqual(request("similarity", token, occurrence="current", mode="tags"), (200, result))
        paths.reverse()
        self.assertEqual(request("similarity", token, **source)[0], 409)
        self.assertEqual(request("command", token, command="queue add 2", libraryKey=row["key"])[0], 409)
        paths.reverse()
        self.assertEqual(request("command", token, command="queue add 2", libraryKey=row["key"])[0], 202)

        other = NativeSession()
        other.library = session.library
        other.similarity = session.similarity
        _, paired = other.request("pair", other.invite, {"library": False}, [])
        self.assertFalse(paired["similarity"])
        self.assertEqual(other.request("similarity", paired["token"], source, [])[0], 403)

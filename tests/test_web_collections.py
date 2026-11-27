import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mariana.albums import AlbumCatalog
from mariana.database import MarianaDatabase
from mariana.models import AlbumRef, AlbumTrack, AlbumTrackStatus, MediaRef, MediaSource
from mariana.preferences import MediaPreferences, PreferenceState
from mariana.queueing import PersistentQueue
from mariana.radio import RadioCatalog
from mariana.web_collections import PAGE_SIZE, WebCollections


class WebCollectionTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = MarianaDatabase(Path(directory.name) / "state.db")
        self.addCleanup(self.db.close)
        self.queue = PersistentQueue(self.db)
        self.albums = AlbumCatalog(self.db)
        self.preferences = MediaPreferences(self.db)
        self.radio = RadioCatalog(self.db)
        self.client = WebCollections(queue=self.queue, albums=self.albums,
                                     favorites=lambda: self.preferences.list(PreferenceState.FAVORITE),
                                     radio=self.radio)
        self.auth = "fixture-auth"
        self.slow = MediaRef(MediaSource.LOCAL, "/private/music/slow.ogg", title="Slow Morning")
        self.fast = MediaRef(MediaSource.URL, "https://provider.example/private?secret=yes", title="Fast Night")

    def view(self, collection, **args):
        return self.client.read({"collection": collection, **args}, self.auth)

    def command(self, row, action="play", auth=None):
        return self.client.command({"key": row["key"], "action": action}, auth or self.auth)

    def test_queue_action_staleness_and_private_reference_exclusion(self):
        self.queue.add(self.slow)
        self.queue.add(self.fast)
        self.queue.jump(0)
        self.queue.set_repeat("all")
        view = self.view("queue")
        self.assertEqual(view["status"], {"repeat": "all", "consume": False, "autofill": False})
        self.assertEqual(view["total"], 2)
        first, second = view["rows"]
        self.assertTrue(first["active"])
        self.assertFalse(second["active"])
        self.assertEqual(self.command(first), "queue jump 1")
        self.assertEqual(self.command(first, "down"), "queue move 1 2")
        self.assertEqual(self.command(second, "remove"), "queue remove 2")
        self.assertEqual(self.view("queue", query="fast night")["total"], 1)
        result = json.dumps(view)
        self.assertNotIn("/private", result)
        self.assertNotIn("provider.example", result)
        with self.assertRaises(ValueError):
            self.command(first, auth="different session")
        self.queue.move(0, 1)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.command(first, "remove")

    def test_playlists_and_favorites_keep_native_index_and_revision(self):
        playlist = self.queue.playlists.create("Listening set")
        playlist = self.queue.playlists.add_media(playlist.playlist_id, self.slow)
        self.preferences.set(self.slow, PreferenceState.FAVORITE)
        self.preferences.set(self.fast, PreferenceState.FAVORITE)
        row, = self.view("playlists")["rows"]
        self.assertEqual(self.command(row, "queue"), f"playlist queue {playlist.playlist_id}")
        tracks = self.view("playlists", detail=row["key"])
        self.assertEqual(tracks["detail"]["title"], "Listening set")
        self.assertEqual([item["title"] for item in tracks["rows"]], ["Slow Morning"])
        self.queue.playlists.clear(playlist.playlist_id)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.view("playlists", detail=row["key"])
        liked, previous = self.view("favorites")["rows"]
        self.assertEqual(liked["title"], "Fast Night")
        self.assertEqual(self.command(previous), ".fav 2")
        self.preferences.set(self.fast, PreferenceState.NEUTRAL)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.command(previous)

    def test_album_details_and_radio_toggle_use_existing_ids(self):
        track = AlbumTrack("Slow Morning", disc_number=2, track_number=3,
                           resolution_status=AlbumTrackStatus.LOCAL, media=self.slow)
        album = AlbumRef("saved-album", "Evening edition", "Jessie",
                         tracks=[track], resolution_scope="hybrid")
        self.albums._persist(album)
        first, = self.view("albums")["rows"]
        details = self.view("albums", detail=first["key"])
        item, = details["rows"]
        self.assertEqual(self.command(item, "queue"), "album queue saved-album --tracks 2.3")
        station, = self.view("live", query="groove salad")["rows"]
        self.assertEqual(self.command(station), "radio play somafm-groove-salad")
        self.assertEqual(self.command(station, "favorite"), "radio favorite somafm-groove-salad")
        self.radio.favorite("somafm-groove-salad")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.command(station, "favorite")
        current, = self.view("live", query="groove salad")["rows"]
        self.assertEqual(self.command(current, "favorite"), "radio favorite somafm-groove-salad off")

    def test_paging_and_malformed_selections(self):
        for index in range(PAGE_SIZE + 3):
            self.queue.add(MediaRef(MediaSource.URL, f"https://example.media/{index}", title=f"Track {index}"))
        second = self.view("queue", offset=PAGE_SIZE)
        self.assertEqual(second["total"], PAGE_SIZE + 3)
        self.assertEqual(len(second["rows"]), 3)
        self.assertEqual(self.command(second["rows"][0]), f"queue jump {PAGE_SIZE + 1}")
        with self.assertRaises(ValueError):
            self.view("queue", offset=True)
        with self.assertRaises(ValueError):
            self.client.command({"key": "arbitrary", "action": "play"}, self.auth)
        modified = dict(second["rows"][0])
        modified["key"] += "0"
        with self.assertRaises(ValueError):
            self.command(modified)

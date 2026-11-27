import json
import tempfile
import unittest
from pathlib import Path

from mariana.database import MarianaDatabase
from mariana.music_wall import wall_command


class MusicWallTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = MarianaDatabase(self.root / "user.db")
        self.remote = MarianaDatabase(self.root / "friend.db")
        self.addCleanup(self.db.close)
        self.addCleanup(self.remote.close)

    def test_wall_exchange_follow_matching_and_refresh(self):
        def run(*args):
            return wall_command(self.db, list(args))

        def other(*args):
            return wall_command(self.remote, list(args))

        other("profile", "Guest")
        other("add", "track", "Suggahunny", "Track A")
        run("add", "album", "Suggahunny", "Record")
        path = str(self.root / "guest.json")
        other("export", path)
        run("import", path)
        profile = json.loads(Path(path).read_text())["id"]
        self.assertNotIn("Guest", run("feed"))
        run("follow", profile)
        self.assertIn("Guest", run("feed"))
        self.assertIn("100%", run("matches"))
        run("import", path)
        self.assertEqual(run("feed").count("Track A"), 1)
        run("unfollow", profile)
        self.assertNotIn("Guest", run("feed"))
        self.assertIn("Guest", run("list", profile))
        run("forget", profile)
        self.assertNotIn("Guest", run("profiles"))

    def test_invalid_refresh_preserves_posts_and_export_excludes_other_users(self):
        path = self.root / "in.json"
        wall_command(self.remote, ["take", "Artist", "Great voice"])
        wall_command(self.remote, ["export", str(path)])
        wall_command(self.db, ["import", str(path)])
        data = json.loads(path.read_text())
        data["posts"][0]["body"] = "invalid\x1b[31m"
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            wall_command(self.db, ["import", str(path)])
        self.assertIn("Great voice", wall_command(self.db, ["list", data["id"]]))
        out = self.root / "out.json"
        wall_command(self.db, ["export", str(out)])
        self.assertEqual(json.loads(out.read_text())["posts"], [])
        with self.assertRaises(FileExistsError):
            wall_command(self.db, ["export", str(out)])
        with self.assertRaises(ValueError):
            wall_command(self.db, ["import", str(out)])

    def test_daily_trivia_and_scoring(self):
        def run(*args):
            return wall_command(self.db, list(args))

        run("add", "track", "FKA twigs", "Cellophane")
        self.assertIn("Cellophane", run("quiz"))
        self.assertIn("Correct", run("answer", "fka twigs"))
        self.assertIn("complete", run("answer", "FKA twigs"))
        self.assertIn("1 quiz wins", run("badges"))
        with self.assertRaises(ValueError):
            run("review", "S", "T", "12", "Great")
        self.assertIn("No catalogued", run("stats"))

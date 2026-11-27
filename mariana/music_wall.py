"""Personal music wall and explicit exchange of bounded, portable profile snapshots."""

from __future__ import annotations

import json
import os
import random
import unicodedata
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from time import time

from mariana.database import MarianaDatabase

HELP = """wall profile [display name] | wall list [profile-id] | wall feed | wall matches
wall add track|album "Artist" "Title" | wall listen "Artist" "Track"
wall review "Artist" "Title" 1-5 "Review" | wall take "Artist" "Your hot take"
wall delete post-id | wall export "new-file.json" | wall import "friend.json"
wall listen current | wall history | wall stats
wall profiles | wall follow profile-id | wall unfollow profile-id | wall forget profile-id
wall quiz | wall answer "Artist" | wall badges"""
FIELDS = ("id", "kind", "artist", "title", "body", "stars", "created")
COLUMNS = ", ".join(FIELDS)
INSERT = f"INSERT INTO wall_posts(profile, {COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
MAX_POSTS = 2000
MAX_BYTES = 8 * 1024 * 1024


def _text(value, limit, optional=False):
    if not isinstance(value, str):
        raise ValueError("Expected plain text")
    value = value.strip()
    if (not optional and not value) or len(value) > limit or any(unicodedata.category(c) in {"Cc", "Cs", "Cf"} for c in value):
        raise ValueError(f"Use plain text of at most {limit} characters")
    return value


def _id(value):
    return str(uuid.UUID(_text(value, 36)))


def _post(item):
    if not isinstance(item, dict) or any(key not in item for key in FIELDS):
        raise ValueError("Incomplete wall post")
    kind = item["kind"]
    if kind not in ("track", "album", "review", "take", "listen"):
        raise ValueError("Unknown post type")
    stars = item["stars"]
    valid_scores = range(1, 6) if kind == "review" else (0,)
    if type(stars) is not int or stars not in valid_scores:
        raise ValueError("Reviews use 1 to 5 stars")
    created = item["created"]
    if type(created) is not int or not 0 <= created <= 253402300799:
        raise ValueError("Invalid post time")
    return (_id(item["id"]), kind, _text(item["artist"], 160),
            _text(item["title"], 240, kind == "take"), _text(item["body"], 600, kind not in ("review", "take")),
            stars, created)


def _owner(db):
    with db.transaction() as conn:
        row = conn.execute("SELECT id FROM wall_profiles WHERE local=1").fetchone()
        if row:
            return row["id"]
        owner = str(uuid.uuid4())
        conn.execute("INSERT INTO wall_profiles VALUES (?, 'Listener', 1, 1)", (owner,))
        return owner


def _show(db, filt, params):
    rows = db.fetchall(f"""SELECT p.*, u.name FROM wall_posts AS p JOIN wall_profiles AS u ON p.profile=u.id
        WHERE {filt} ORDER BY p.created DESC, p.rowid DESC LIMIT 100""", params)
    return "\n".join(f"{r['name']} · {r['kind']} · {r['artist']} {r['title']} "
                     f"{'★' * r['stars']} {r['body']} [{r['id']}]" for r in rows) or "No posts yet."


def _export(db, profile, path):
    with db.transaction() as conn:
        name = conn.execute("SELECT name FROM wall_profiles WHERE id=?", (profile,)).fetchone()[0]
        rows = [dict(row) for row in conn.execute(
            f"SELECT {COLUMNS} FROM wall_posts WHERE profile=? ORDER BY created, rowid", (profile,))]
    payload = json.dumps({"format": "mariana.wall.v1", "id": profile, "name": name, "posts": rows},
                         ensure_ascii=False, indent=2).encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ValueError("This wall exceeds the snapshot size limit")
    with path.open("xb") as file:
        try:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        except OSError:
            file.close()
            path.unlink(missing_ok=True)
            raise
    return f"Exported {len(rows)} posts to {path}"


def _import(db, owner, path):
    with path.open("rb") as file:
        data = file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Snapshot is too large")
    try:
        obj = json.loads(data)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid snapshot encoding or nesting") from exc
    if not isinstance(obj, dict) or obj.get("format") != "mariana.wall.v1":
        raise ValueError("Expected a Mariana wall snapshot")
    profile, name = _id(obj.get("id")), _text(obj.get("name"), 80)
    posts = obj.get("posts")
    if profile == owner or not isinstance(posts, list) or len(posts) > MAX_POSTS:
        raise ValueError("Own profile or invalid snapshot size")
    rows = [_post(p) for p in posts]
    if len({r[0] for r in rows}) != len(rows):
        raise ValueError("Duplicate post ID")
    with db.transaction() as conn:
        conn.execute("""INSERT INTO wall_profiles(id,name) VALUES (?,?)
                     ON CONFLICT(id) DO UPDATE SET name=excluded.name""", (profile, name))
        conn.execute("DELETE FROM wall_posts WHERE profile=?", (profile,))
        conn.executemany(INSERT, [(profile, *r) for r in rows])
    return f"Imported {name} ({profile}) with {len(rows)} posts. Use wall list {profile} to explore."


def _matches(db, owner):
    sets: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    for row in db.fetchall("""SELECT profile,name,artist FROM wall_posts JOIN wall_profiles
                           ON profile=wall_profiles.id WHERE kind IN ('album','track','listen')"""):
        sets.setdefault(row["profile"], set()).add(row["artist"].casefold())
        names[row["profile"]] = row["name"]
    mine = sets.pop(owner, set())
    scores = sorted(((len(mine & theirs) / len(mine | theirs), names[key], key, sorted(mine & theirs))
                     for key, theirs in sets.items() if mine & theirs), reverse=True)
    return "\n".join(f"{score:.0%} · {name} [{key}] · {', '.join(overlap[:5])}"
                     for score, name, key, overlap in scores[:30]) or "Add music and import a wall with artists in common."


def _quiz(db, owner, answer=None):
    today = date.today().isoformat()
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM wall_quiz WHERE day=?", (today,)).fetchone()
        if row is None:
            if answer is not None:
                raise ValueError("Open today's question with wall quiz first")
            # Identically titled works by different artists cannot produce an unambiguous question.
            choices = conn.execute("""SELECT MIN(title), MIN(artist) FROM wall_posts WHERE profile=?
                AND kind IN ('track','album','listen') GROUP BY title COLLATE NOCASE
                HAVING COUNT(DISTINCT artist COLLATE NOCASE)=1""", (owner,)).fetchall()
            if not choices:
                return "Add a track or album to your wall to unlock daily trivia."
            title, artist = random.SystemRandom().choice(choices)
            conn.execute("INSERT INTO wall_quiz VALUES (?, ?, ?, NULL)", (today, title, artist))
            row = conn.execute("SELECT * FROM wall_quiz WHERE day=?", (today,)).fetchone()
        if row["won"] is not None:
            return f"Today's quiz is complete. The artist was {row['answer']}."
        if answer is None:
            return f"Who is the artist behind “{row['question']}” on your wall? Use wall answer."
        won = _text(answer, 160).casefold() == row["answer"].casefold()
        conn.execute("UPDATE wall_quiz SET won=? WHERE day=?", (int(won), today))
        return ("Correct! " if won else "Answer: ") + row["answer"]


def _history(db, stats):
    if stats:
        rows = db.fetchall("""SELECT m.artist, COUNT(*) AS starts, COUNT(DISTINCT e.stable_id) AS tracks
            FROM playback_events e JOIN media_items m USING(stable_id)
            WHERE e.action='play' AND e.play_kind='start' AND e.occurred_at>=?
            AND m.artist IS NOT NULL AND trim(m.artist) <> ''
            GROUP BY m.artist COLLATE NOCASE ORDER BY starts DESC, m.artist LIMIT 20""", (time() - 30 * 86400,))
        return "\n".join(f"{r['artist']} · {r['starts']} starts · {r['tracks']} tracks" for r in rows) or (
            "No catalogued artist starts in the past 30 days. Playback history uses your hotspots setting.")
    rows = db.fetchall("""SELECT e.occurred_at, m.artist, m.title FROM playback_events e
        JOIN media_items m USING(stable_id) WHERE e.action='play' AND e.play_kind='start'
        AND m.title IS NOT NULL ORDER BY e.occurred_at DESC LIMIT 50""")
    return "\n".join(f"{datetime.fromtimestamp(r['occurred_at'], UTC):%Y-%m-%d %H:%M} UTC · "
                     f"{r['artist'] or 'Unknown artist'} · {r['title']}" for r in rows) or (
        "No catalogued playback starts recorded. Use hotspots status to inspect local history settings.")


def wall_command(db: MarianaDatabase, args: list[str], current=None) -> str:
    if not args or args[0].casefold() == "help":
        return HELP
    action, values = args[0].casefold(), args[1:]
    owner = _owner(db)
    if action in {"history", "stats"} and not values:
        return _history(db, action == "stats")
    if action == "listen" and values == ["current"]:
        if current is None or not current.title or not current.artist:
            raise ValueError('This item needs an artist and title. Use wall listen "Artist" "Title".')
        values = [current.artist, current.title]
    if action == "profile":
        if values:
            name = _text(" ".join(values), 80)
            with db.transaction() as conn:
                conn.execute("UPDATE wall_profiles SET name=? WHERE id=?", (name, owner))
        row = db.fetchone("SELECT name FROM wall_profiles WHERE id=?", (owner,))
        return f"{row['name']} [{owner}]"
    if action == "profiles" and not values:
        return "\n".join(f"{r['name']} [{r['id']}] · {'following' if r['following'] else 'imported'}"
                         for r in db.fetchall("SELECT * FROM wall_profiles WHERE local=0 ORDER BY name")) or "No imported walls."
    if action == "list" and len(values) <= 1:
        return _show(db, "p.profile=?", (_id(values[0]) if values else owner,))
    if action == "feed" and not values:
        return _show(db, "u.following=1 OR u.local=1", ())
    if action == "matches" and not values:
        return _matches(db, owner)
    if action == "badges" and not values:
        posts = db.fetchone("SELECT COUNT(*) FROM wall_posts WHERE profile=?", (owner,))[0]
        wins = db.fetchone("SELECT COUNT(*) FROM wall_quiz WHERE won=1")[0]
        badges = [name for ok, name in ((posts >= 1, "Collector"), (posts >= 10, "Curator"),
                                         (wins >= 1, "Quiz fan"), (wins >= 7, "Quiz regular")) if ok]
        return f"{posts} posts · {wins} quiz wins · " + (", ".join(badges) or "Your first post earns Collector.")
    if action == "quiz" and not values:
        return _quiz(db, owner)
    if action == "answer" and values:
        return _quiz(db, owner, " ".join(values))
    if action in {"import", "export"} and len(values) == 1:
        path = Path(values[0]).expanduser()
        return _import(db, owner, path) if action == "import" else _export(db, owner, path)
    if action in {"follow", "unfollow", "forget", "delete"} and len(values) == 1:
        target = _id(values[0])
        with db.transaction() as conn:
            if action == "delete":
                result = conn.execute("DELETE FROM wall_posts WHERE id=? AND profile=?", (target, owner))
            elif action == "forget":
                result = conn.execute("DELETE FROM wall_profiles WHERE id=? AND local=0", (target,))
            else:
                result = conn.execute("UPDATE wall_profiles SET following=? WHERE id=? AND local=0",
                                      (int(action == "follow"), target))
            if result.rowcount == 0:
                raise ValueError("No matching post or imported profile")
        return "Updated."
    stars, title, body = 0, "", ""
    if action == "add" and len(values) == 3 and values[0].lower() in ("track", "album"):
        kind, artist, title = values
        kind = kind.lower()
    elif action == "listen" and len(values) == 2:
        kind, (artist, title) = action, values
    elif action == "review" and len(values) == 4:
        artist, title, score, body = values
        kind, stars = action, int(score)
    elif action == "take" and len(values) == 2:
        kind, (artist, body) = action, values
    else:
        raise ValueError(HELP)
    fields = dict(zip(FIELDS, (str(uuid.uuid4()), kind, artist, title, body, stars, int(datetime.now(UTC).timestamp())), strict=True))
    item = _post(fields)
    with db.transaction() as conn:
        if conn.execute("SELECT COUNT(*) FROM wall_posts WHERE profile=?", (owner,)).fetchone()[0] >= MAX_POSTS:
            raise ValueError("Wall is full. Delete a post before adding another.")
        conn.execute(INSERT, (owner, *item))
    return f"Added {kind} to your wall [{item[0]}]."

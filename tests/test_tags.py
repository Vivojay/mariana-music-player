from collections.abc import Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from mariana.database import SCHEMA_VERSION, MarianaDatabase
from mariana.models import MediaRef, MediaSource
from mariana.preferences import MediaPreferences, PreferenceState
from mariana.tags import TagError, TagInUseError, TagNotFoundError, TagStore


@pytest.fixture
def database_path() -> Iterator[Path]:
    with NamedTemporaryFile(suffix=".db", delete=False) as handle:
        path = Path(handle.name)
    path.unlink()
    try:
        yield path
    finally:
        for suffix in ("", "-wal", "-shm"):
            path.with_name(path.name + suffix).unlink(missing_ok=True)


def store_media(database: MarianaDatabase, stable_id: str, title: str, source=MediaSource.LOCAL) -> MediaRef:
    uri = str(Path("C:/Music") / f"{title}.flac") if source == MediaSource.LOCAL else f"https://media.test/{stable_id}"
    media = MediaRef(source, uri, stable_id=stable_id, title=title)
    MediaPreferences(database).set(media, PreferenceState.NEUTRAL)
    return media


def test_tag_schema_and_assignments_persist_by_stable_media_identity(database_path: Path):
    with MarianaDatabase(database_path) as database:
        assert database.get_state("missing") is None
        assert database.fetchone("SELECT value FROM schema_meta WHERE key='schema_version'")[0] == str(SCHEMA_VERSION)
        media = store_media(database, "track-1", "First title")
        tags = TagStore(database)

        assigned = tags.attach(media.stable_id, ["Late   Night", "AMBIENT"])
        assert [entry.tag.name for entry in assigned] == ["Late Night", "AMBIENT"]
        assert tags.attach(media.stable_id, ["late night"])[0].assigned_at == assigned[0].assigned_at
        assert [tag.name for tag in tags.list_tags(stable_id=media.stable_id)] == ["AMBIENT", "Late Night"]
        assert [
            (entry.tag.name, entry.assignment_source)
            for entry in tags.list_media_tags(media.stable_id)
        ] == [("AMBIENT", "user"), ("Late Night", "user")]

    with MarianaDatabase(database_path) as database:
        tags = TagStore(database)
        assert tags.tagged_media(all_of=["ambient", "late night"]) == ("track-1",)
        database.execute(
            "UPDATE media_items SET original_uri=?,title=? WHERE stable_id=?",
            ("C:/Moved/Renamed.flac", "Renamed title", "track-1"),
        )
        assert tags.tagged_media(all_of=["ambient"]) == ("track-1",)


def test_tag_updates_and_deletion_are_explicit_and_safe(database_path: Path):
    with MarianaDatabase(database_path) as database:
        store_media(database, "track-1", "Track")
        tags = TagStore(database)
        original = tags.ensure_tag("focus", description="Work music")
        assert tags.ensure_tag("FOCUS").tag_id == original.tag_id

        updated = tags.update_tag("focus", name="Deep Focus", description=None)
        assert updated.tag_id == original.tag_id
        assert updated.name == "Deep Focus"
        assert updated.description is None
        tags.attach("track-1", ["deep focus"])

        with pytest.raises(TagInUseError, match="1 media item"):
            tags.delete_tag("Deep Focus")
        assert tags.delete_tag("Deep Focus", detach=True).tag_id == original.tag_id
        assert tags.list_tags(stable_id="track-1") == ()
        with pytest.raises(TagNotFoundError, match="Unknown tag"):
            tags.update_tag("Deep Focus", name="Missing")


def test_tag_groups_are_reusable_views_not_tag_ownership(database_path: Path):
    with MarianaDatabase(database_path) as database:
        tags = TagStore(database)
        mood = tags.create_group("Mood", description="Listening mood")
        tags.add_to_group(mood.group_id, ["Calm", "Energetic", "Reflective"])
        tags.create_group("Activity")
        tags.add_to_group("activity", ["Calm", "Study"])

        assert [tag.name for tag in tags.list_tags(group="mood")] == ["Calm", "Energetic", "Reflective"]
        assert tags.remove_from_group("Mood", ["Energetic", "missing"]) == 1
        assert [tag.name for tag in tags.list_tags(group="Mood")] == ["Calm", "Reflective"]
        assert tags.update_group("mood", name="Feeling").group_id == mood.group_id
        tags.delete_group("Feeling")

        assert [tag.name for tag in tags.list_tags()] == ["Calm", "Energetic", "Reflective", "Study"]
        assert [group.name for group in tags.list_groups()] == ["Activity"]


def test_tag_only_queries_support_all_any_exclusion_source_and_limit(database_path: Path):
    with MarianaDatabase(database_path) as database:
        store_media(database, "alpha", "Alpha")
        store_media(database, "beta", "Beta")
        store_media(database, "online", "Online", MediaSource.YOUTUBE)
        tags = TagStore(database)
        tags.attach("alpha", ["ambient", "instrumental", "calm"])
        tags.attach("beta", ["ambient", "vocal"])
        tags.attach("online", ["ambient", "calm"])

        assert tags.tagged_media(all_of=["ambient", "calm"]) == ("alpha", "online")
        assert tags.tagged_media(any_of=["instrumental", "vocal"]) == ("alpha", "beta")
        assert tags.tagged_media(all_of=["ambient"], none_of=["vocal"]) == ("alpha", "online")
        assert tags.tagged_media(all_of=["ambient"], source="local") == ("alpha", "beta")
        assert tags.tagged_media(all_of=["ambient"], limit=1) == ("alpha",)
        assert tags.tagged_media(all_of=["unknown"]) == ()
        assert tags.tagged_media(any_of=["unknown"]) == ()


def test_invalid_tag_operations_leave_media_and_existing_assignments_unchanged(database_path: Path):
    with MarianaDatabase(database_path) as database:
        store_media(database, "track-1", "Track")
        tags = TagStore(database)
        tags.attach("track-1", ["safe"])

        for invalid in ("", "   ", "x" * 65, "bad\x00tag"):
            with pytest.raises(TagError):
                tags.ensure_tag(invalid)
        with pytest.raises(TagNotFoundError, match="Unknown media identity"):
            tags.attach("missing", ["new"])
        with pytest.raises(TagError, match="assignment source"):
            tags.attach("track-1", ["new"], assignment_source="unknown")
        with pytest.raises(TagError, match="non-negative integer"):
            tags.tagged_media(limit=-1)

        assert [tag.name for tag in tags.list_tags(stable_id="track-1")] == ["safe"]

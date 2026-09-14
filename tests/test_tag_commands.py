from pathlib import Path

import pytest

from mariana.command_parser import split_command
from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource, canonical_uri, podcast_episode_identity
from mariana.navigation import NavigationScope
from mariana.preferences import MediaPreferences
from mariana.tag_commands import TagCommandService
from mariana.tags import TagError, TagInUseError, TagNotFoundError, TagStore


def indexed_media(database: MarianaDatabase, path: Path, stable_id: str, title: str) -> MediaRef:
    path.write_bytes(b"test audio")
    with database.transaction() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO library_roots(root_id,path,path_key,kind) VALUES('root',?,?, 'folder')",
            (str(path.parent), str(path.parent).casefold()),
        )
        connection.execute(
            "INSERT INTO library_files(library_id,root_id,canonical_path,path_key,size,mtime_ns,extension,updated_at) "
            "VALUES(?, 'root', ?, ?, 10, 1, '.flac', 1)",
            (stable_id, str(path), canonical_uri(MediaSource.LOCAL, str(path))),
        )
    return MediaRef(MediaSource.LOCAL, str(path), stable_id=stable_id, title=title)


@pytest.fixture
def environment(tmp_path):
    with MarianaDatabase(tmp_path / "tags.db") as database:
        media = {
            "1": indexed_media(database, tmp_path / "alpha.flac", "alpha", "Alpha"),
            "2": indexed_media(database, tmp_path / "beta.flac", "beta", "Beta"),
            "3": indexed_media(database, tmp_path / "gamma.flac", "gamma", "Gamma"),
        }
        media["current"] = media["1"]
        service = TagCommandService(TagStore(database), resolve_target=media.get)
        yield database, media, service


def run(service, command):
    tokens = split_command(command)
    assert tokens[0] == "tag"
    return service.execute(tokens[1:])


def test_commands_persist_normalized_memberships_and_preserve_preferences(environment, tmp_path):
    database, media, service = environment
    preferences = MediaPreferences(database)
    preferences.set_rating(media["1"], 4)
    preferences.set_blocked(media["1"], True)
    created = run(service, 'tag create "Late Night" --description "Evening music"')
    assert created.tags[0].description == "Evening music"
    assert run(service, 'tag create "LATE   NIGHT"').tags[0].tag_id == created.tags[0].tag_id
    result = run(service, 'tag attach current "late night" AMBIENT ambient')
    assert result.changed_count == 2
    assert [tag.name for tag in result.tags] == ["AMBIENT", "Late Night"]
    assert run(service, 'tag attach 1 "late night"').changed_count == 0
    assert run(service, "tag show").media.stable_id == "alpha"
    assert preferences.rating("alpha") == 4
    assert preferences.is_blocked("alpha") is True

    with MarianaDatabase(tmp_path / "tags.db") as reopened:
        recovered = TagCommandService(TagStore(reopened), resolve_target=media.get)
        assert [entry.tag.name for entry in run(recovered, "tag show 1").media_tags] == ["AMBIENT", "Late Night"]
        assert run(recovered, 'tag detach 1 AMBIENT missing').changed_count == 1
        assert run(recovered, 'tag detach 1 AMBIENT').changed_count == 0
        assert run(recovered, "tag list").tags[0].name == "AMBIENT"
        assert run(recovered, 'tag rename "Late Night" Night').tags[0].tag_id == created.tags[0].tag_id
        assert [entry.stable_id for entry in run(recovered, "tag find --all night").entries] == ["alpha"]


def test_in_use_deletion_requires_confirmation_and_keeps_other_data(environment):
    database, _, service = environment
    run(service, "tag attach 1 calm safe")
    run(service, "tag group create Mood")
    run(service, "tag group add Mood calm")
    with pytest.raises(TagInUseError, match="--yes"):
        run(service, "tag delete calm")
    prompts = []
    service.confirm = lambda message: prompts.append(message) or False
    cancelled = run(service, "tag delete calm")
    assert cancelled.cancelled
    assert prompts and "all media and tag groups" in prompts[0]
    assert [tag.name for tag in run(service, "tag show 1").tags] == ["calm", "safe"]
    assert run(service, "tag delete calm --yes").operation == "delete"
    assert run(service, "tag group show Mood").tags == ()
    assert [tag.name for tag in run(service, "tag show 1").tags] == ["safe"]
    assert database.fetchone("SELECT 1 FROM media_items WHERE stable_id='alpha'")
    run(service, "tag create unused")
    service.confirm = lambda _: pytest.fail("Unused deletion should not prompt")
    run(service, "tag delete unused")


def test_confirmed_deletion_uses_bound_tag_id_and_rejects_replacement(environment):
    _, _, service = environment
    run(service, "tag attach 1 calm")
    old_id = run(service, "tag list").tags[0].tag_id

    def replace_during_confirmation(_):
        service.store.delete_tag(old_id, detach=True)
        service.store.attach("alpha", ["calm"])
        return True

    service.confirm = replace_during_confirmation
    with pytest.raises(TagNotFoundError):
        run(service, "tag delete calm")
    assert service.store.list_tags()[0].tag_id != old_id
    assert service.store.tagged_media(all_of=["calm"]) == ("alpha",)
    service.confirm = lambda _: True
    run(service, "tag delete calm")
    assert service.store.list_tags() == ()


def test_confirmed_deletion_rejects_renamed_tag(environment):
    _, _, service = environment
    run(service, "tag attach 1 calm")

    def rename_during_confirmation(_):
        service.store.update_tag("calm", name="Relax")
        return True

    service.confirm = rename_during_confirmation
    with pytest.raises(TagError, match="changed during confirmation"):
        run(service, "tag delete calm")
    assert service.store.tagged_media(all_of=["Relax"]) == ("alpha",)


def test_reusable_groups_and_group_filter_intersect_with_explicit_filters(environment, tmp_path):
    _, media, service = environment
    run(service, "tag attach 1 calm ambient")
    run(service, "tag attach 2 vocal ambient")
    run(service, "tag attach 3 energetic")
    group = run(service, 'tag group create Mood --description "Listening mood"').groups[0]
    assert run(service, "tag group add Mood calm energetic calm").changed_count == 2
    run(service, "tag group create Work")
    run(service, "tag group add Work calm")
    assert [group.name for group in run(service, "tag group list").groups] == ["Mood", "Work"]
    assert [entry.stable_id for entry in run(service, "tag find --group Mood").entries] == ["alpha", "gamma"]
    assert [entry.stable_id for entry in run(service, "tag find --group Mood --all ambient").entries] == ["alpha"]
    assert [entry.stable_id for entry in run(service, "tag find --group Mood --any energetic").entries] == ["gamma"]
    assert [entry.stable_id for entry in run(service, "tag find --group Mood --not calm --limit 1").entries] == ["gamma"]
    assert run(service, "tag group rename Mood Feeling").groups[0].group_id == group.group_id
    with MarianaDatabase(tmp_path / "tags.db") as reopened:
        recovered = TagCommandService(TagStore(reopened), resolve_target=media.get)
        assert [tag.name for tag in run(recovered, "tag group show Feeling").tags] == ["calm", "energetic"]
    assert run(service, "tag group remove Feeling energetic missing").changed_count == 1
    with pytest.raises(TagInUseError, match="--yes"):
        run(service, "tag group delete Feeling")
    service.confirm = lambda _: False
    assert run(service, "tag group delete Feeling").cancelled
    run(service, "tag group delete Feeling --yes")
    assert [tag.name for tag in run(service, "tag group show Work").tags] == ["calm"]
    assert [tag.name for tag in run(service, "tag show 3").tags] == ["energetic"]
    run(service, "tag group create Empty")
    assert run(service, "tag find --group Empty").entries == ()


def test_group_mutation_during_delete_confirmation_is_refused(environment):
    _, _, service = environment
    run(service, "tag group create Mood")
    run(service, "tag group add Mood calm")

    def change_group(_):
        service.store.add_to_group("Mood", ["energetic"])
        return True

    service.confirm = change_group
    with pytest.raises(TagError, match="changed during confirmation"):
        run(service, "tag group delete Mood")
    assert len(run(service, "tag group show Mood").tags) == 2


def test_search_all_any_exclusion_limit_source_and_unknown_tags(environment):
    _, _, service = environment
    run(service, "tag attach 1 ambient calm instrumental")
    run(service, "tag attach 2 ambient vocal")
    run(service, "tag attach 3 energetic instrumental")

    def identities(query):
        return [entry.stable_id for entry in run(service, f"tag find {query}").entries]

    assert identities("--all ambient calm") == ["alpha"]
    assert identities("--any vocal instrumental") == ["alpha", "beta", "gamma"]
    assert identities("--all ambient --not vocal") == ["alpha"]
    assert identities("--not ambient") == ["gamma"]
    assert identities("--any unknown vocal") == ["beta"]
    assert identities("--all unknown") == []
    assert identities("--any unknown") == []
    assert identities("--any ambient --source local --limit 1") == ["alpha"]
    assert identities("--any ambient --source youtube") == []
    assert identities("--any ambient --limit 0") == []


def test_search_recovers_moved_paths_and_retains_unavailable_bound_entries(environment, tmp_path):
    database, media, service = environment
    run(service, "tag attach 1 calm")
    run(service, "tag attach 2 calm")
    original_entries = run(service, "tag find --all calm").entries
    moved = tmp_path / "moved.flac"
    Path(media["1"].original_uri).rename(moved)
    with database.transaction() as connection:
        connection.execute("UPDATE library_files SET canonical_path=? WHERE library_id='alpha'", (str(moved),))
        connection.execute("UPDATE library_files SET state='missing' WHERE library_id='beta'")
    entries = run(service, "tag find --all calm").entries
    assert entries[0].stable_id == "alpha"
    assert entries[0].media.original_uri == str(moved)
    assert entries[0].source_scope == NavigationScope.RESULTS
    assert entries[0].occurrence_id == "alpha"
    assert entries[1].stable_id == "beta"
    assert entries[1].media is None
    assert "Unavailable" in entries[1].label
    assert service.resolve_result(original_entries[0]).media.original_uri == str(moved)
    with pytest.raises(TagNotFoundError, match="missing or unavailable"):
        service.resolve_result(original_entries[1])
    with pytest.raises(TagError, match="changed"):
        run(service, "tag attach current stale")
    with pytest.raises(TagError, match="missing or unavailable"):
        run(service, "tag attach 2 stale")
    assert [tag.name for tag in service.store.list_tags()] == ["calm"]


def test_result_refresh_uses_stable_identity_not_current_library_order(environment):
    database, media, service = environment
    run(service, "tag attach 1 calm")
    entry = run(service, "tag find --all calm").entries[0]
    media["1"] = media["2"]
    service.resolve_target = lambda _: pytest.fail("Result refresh must not resolve a mutable library index")
    assert service.resolve_result(entry).stable_id == "alpha"
    with database.transaction() as connection:
        connection.execute("DELETE FROM library_files WHERE library_id='alpha'")
    with pytest.raises(TagNotFoundError, match="missing or unavailable"):
        service.resolve_result(entry)


@pytest.mark.parametrize("target", ["0", "-1", "1.5", "https://media.test/track", "C:\\Music\\a.flac"])
def test_invalid_targets_are_never_sent_to_host_resolver(environment, target):
    database, _, service = environment
    service.resolve_target = lambda _: pytest.fail("Invalid target reached the resolver")
    with pytest.raises(TagError, match="Tag target"):
        service.execute(["attach", target, "calm"])
    assert service.store.list_tags() == ()
    assert database.fetchone("SELECT COUNT(*) FROM media_items")[0] == 0


def test_target_resolution_is_once_and_arbitrary_streams_are_not_made_durable(environment, tmp_path):
    database, media, service = environment
    calls = []
    service.resolve_target = lambda target: calls.append(target) or media["current"]
    run(service, "tag attach now calm")
    assert calls == ["current"]
    for source in (MediaSource.URL, MediaSource.RADIO, MediaSource.RECOMMENDATION, MediaSource.PODCAST):
        current = MediaRef(source, "https://media.test/temporary?token=private")
        media["current"] = current
        with pytest.raises(TagError, match="durable tag identity"):
            run(service, "tag attach current unsafe")
        assert database.fetchone("SELECT 1 FROM media_items WHERE stable_id=?", (current.stable_id,)) is None
    media["current"] = MediaRef(MediaSource.LOCAL, str(tmp_path / "unindexed.flac"))
    with pytest.raises(TagError, match="Only indexed local"):
        run(service, "tag attach current unsafe")
    assert [tag.name for tag in service.store.list_tags()] == ["calm"]


def test_current_youtube_and_feed_bound_podcast_use_their_existing_identity(environment):
    database, media, service = environment
    current = MediaRef(MediaSource.YOUTUBE, "https://youtu.be/abcdefghijk", title="Video")
    media["current"] = current
    assert run(service, "tag attach current online").media.stable_id == current.stable_id
    assert MediaPreferences(database).media(current.stable_id) is not None
    for invalid_url in (
        "https://notyoutube.test/watch?v=abcdefghijk",
        "ftp://www.youtube.com/watch?v=abcdefghijk",
        "https://user:secret@www.youtube.com/watch?v=abcdefghijk",
    ):
        media["current"] = MediaRef(MediaSource.YOUTUBE, invalid_url)
        with pytest.raises(TagError, match="durable video identity"):
            run(service, "tag attach current unsafe")
    identity = podcast_episode_identity("https://media.test/feed.xml", guid="episode-1")
    assert identity is not None
    stable_id, kind = identity
    media["current"] = MediaRef(
        MediaSource.PODCAST, "https://media.test/audio.mp3?token=rotating", stable_id=stable_id,
        provenance="podcast-feed", resolver_data={"podcast_identity_kind": kind},
    )
    run(service, "tag attach current spoken")
    assert service.store.tagged_media(all_of=["spoken"]) == (stable_id,)


@pytest.mark.parametrize(
    "arguments",
    [
        ["create"], ["create", "too", "many"], ["create", "valid", "--description"],
        ["create", "valid", "--description", "one", "--description", "two"],
        ["rename", "missing"], ["delete", "missing", "--force"], ["attach", "current"],
        ["show", "1", "2"], ["find"], ["find", "calm"], ["find", "--all"],
        ["find", "--all", "calm", "--source", "invalid"],
        ["find", "--all", "missing", "--limit", "-1"],
        ["find", "--all", "calm", "--limit", "1", "--limit", "2"],
        ["group", "unknown"], ["group", "create"], ["group", "list", "extra"],
        ["group", "create", "valid", "--yes"], ["list", "--yes"],
    ],
)
def test_invalid_commands_are_read_only(environment, arguments):
    database, _, service = environment
    with pytest.raises(TagError):
        service.execute(arguments)
    assert service.store.list_tags() == ()
    assert service.store.list_groups() == ()
    assert database.fetchone("SELECT COUNT(*) FROM media_items")[0] == 0


def test_invalid_names_do_not_partially_mutate_media_or_group(environment):
    database, _, service = environment
    with pytest.raises(TagError):
        service.execute(["attach", "current", "valid", "bad\x00tag"])
    assert database.fetchone("SELECT COUNT(*) FROM media_items")[0] == 0
    run(service, "tag group create Mood")
    with pytest.raises(TagError):
        service.execute(["group", "add", "Mood", "valid", "x" * 65])
    assert service.store.list_tags() == ()
    assert service.store.list_tags(group="Mood") == ()


def test_missing_targets_and_names_fail_without_creating_data(environment):
    _, media, service = environment
    media["current"] = None
    for command in ("tag show", "tag attach 99 calm", "tag rename missing new", "tag group show missing"):
        with pytest.raises(TagNotFoundError):
            run(service, command)
    with pytest.raises(TagError, match="already-tokenized"):
        service.execute("attach current calm")


def test_quoted_values_are_data_not_commands(environment):
    _, _, service = environment
    name = 'calm; next | $(quit)'
    result = service.execute(["attach", "current", name])
    assert result.tags[0].name == name
    assert run(service, 'tag find --all "calm; next | $(quit)"').entries[0].stable_id == "alpha"
    tag = run(service, 'tag create -- --yes').tags[0]
    run(service, f"tag delete {tag.tag_id}")
    assert [tag.name for tag in run(service, "tag list").tags] == [name]


@pytest.mark.parametrize("target", ["9" * 5000], ids=["excessive-digits"])
def test_extreme_tag_index_is_rejected_before_host_resolution(environment, target):
    _, _, service = environment
    service.resolve_target = lambda _: pytest.fail("Invalid index reached host resolver")
    with pytest.raises(TagError, match="Tag target"):
        service.execute(["attach", target, "calm"])


@pytest.mark.parametrize("limit", ["9" * 5000, str(2**80)], ids=["excessive-digits", "sqlite-overflow"])
def test_extreme_query_limit_is_a_domain_error_without_mutation(environment, limit):
    _, _, service = environment
    with pytest.raises(TagError, match="limit"):
        service.execute(["find", "--not", "missing", "--limit", limit])
    assert service.store.list_tags() == ()

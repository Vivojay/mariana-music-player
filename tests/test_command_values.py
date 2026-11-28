import os
import sqlite3
from types import SimpleNamespace

from mariana.command_assist import command_suggestions
from mariana.command_parser import split_command
from mariana.command_values import make_value_provider
from mariana.strudel_projects import StrudelProjectStore


def test_existing_project_completion_and_revision_follow_the_live_store(tmp_path):
    store = StrudelProjectStore(tmp_path / "projects.json")
    project = store.create("Evening study")
    provide = make_value_provider(SimpleNamespace(STRUDEL_PROJECTS=store))
    line = 'strudel show "Even'
    choice = command_suggestions(line, len(line), value_provider=provide)[0]
    assert split_command(choice.apply(line)[0]) == ["strudel", "show", project.name]
    assert provide("revision", "", ("strudel", "import", project.name)) == ("1",)
    store.save(project_id=project.project_id, name=project.name, code=project.code,
               preview_seconds=2, expected_revision=1)
    assert provide("revision", "", ("strudel", "import", project.name)) == ("2",)
    assert not provide("project-name", "", ("strudel", "new"))
    assert not provide("revision", "", ("strudel", "import", "deleted"))


def test_local_paths_preserve_prefix_and_never_probe_a_url_or_unc(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "My Music"
    folder.mkdir()
    (folder / "Evening study.wav").write_bytes(b"")
    (folder / ".hidden.wav").write_bytes(b"")
    (folder / "notes.txt").write_text("test")
    provider = make_value_provider()
    prefix = "." + os.sep + folder.name + os.sep
    assert provider("file-or-library-index", prefix, ("dj", "load", "A")) == (prefix + "Evening study.wav",)
    assert provider("new-wav-path", ".", ("strudel", "render", "evening")) == ()
    assert provider("new-wav-path", "My", ("strudel", "render", "evening")) == ("My Music" + os.sep,)
    line = 'dj load A "' + prefix + 'Eve'
    choice = command_suggestions(line, len(line), value_provider=provider)[0]
    assert split_command(choice.apply(line)[0]) == ["dj", "load", "A", prefix + "Evening study.wav"]
    monkeypatch.setattr(os, "scandir", lambda *_: (_ for _ in ()).throw(AssertionError("must stay local")))
    for bad in ("https://example.org/media", "//server/share", r"\\server\share", "D:relative"):
        assert provider("file-or-library-index", bad, ("dj", "load", "A")) == ()


def test_native_names_indices_and_service_suggestions_match_context():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE playlists(name TEXT, name_key TEXT)")
    connection.executemany("INSERT INTO playlists VALUES (?, ?)", [("Late Rain", "late rain"), ("100% Mix", "100% mix")])
    db = SimpleNamespace(fetchall=lambda query, values: connection.execute(query, values).fetchall(),
                         get_state=lambda key, default: {"saved-show": "Saved show"})
    app = SimpleNamespace(DATABASE=db, QUEUE=SimpleNamespace(playback_position=lambda _: (None, 21)),
                          _sound_files=["a", "b"], _podbean_shelf=SimpleNamespace(slug="open-show", rows=[{}]),
                          LIBRIVOX=SimpleNamespace(results=[SimpleNamespace(catalog_id="42", section_count=3)]))
    provider = make_value_provider(app)
    assert provider("playlist-name", "late", ("playlist", "show")) == ("Late Rain",)
    assert provider("playlist-name", "100%", ("playlist", "show")) == ("100% Mix",)
    assert provider("queue-index", "2", ("queue", "jump")) == ("2", "20", "21")
    assert provider("library-index", "", ("play",)) == ("1", "2")
    for line, candidate in [('playlist play "Late', "Late Rain"), ("queue jump 2", "21"),
                            ("queue insert 22", "22"), ("queue load 100", "100% Mix")]:
        choices = command_suggestions(line, len(line), value_provider=provider)
        assert candidate in [choice.label for choice in choices]
    assert provider("show-slug-or-feed", "", ("podbean", "unfollow")) == ("saved-show",)
    assert provider("episode-number", "", ("podbean", "queue")) == ("1",)
    assert provider("book-reference", "id:", ("librivox", "show")) == ("id:42",)
    assert provider("chapter", "", ("librivox", "play", "1")) == ("1", "2", "3")
    assert provider("service", "spo", ("accounts", "open")) == ("spotify",)
    assert provider("service", "spo", ("jam", "login")) == ()
    assert not provider("username", "", ("accounts", "link", "spotify"))
    connection.close()

from concurrent.futures import ThreadPoolExecutor

from mariana.terminal_history import SessionHistory
from mariana.terminal_player import _Transcript


def test_opt_in_cross_reader_scope_and_private_inputs(tmp_path):
    path = tmp_path / "listener" / "recall.db"
    one, two = SessionHistory(path), SessionHistory(path)
    one.append_string("help")
    assert not path.exists() and two.get_strings() == []
    assert one.set_saving(True)
    for text in ("seek +15s", "artist search private name", "/yl https://media.example/?token=secret",
                 "jam login private-id", "tone sine 220 --seconds 2", "secret\nentry"):
        one.append_string(text)
    assert two.get_strings() == ["seek +15s", "tone sine 220 --seconds 2"]
    assert "private" not in path.read_bytes().decode("latin-1")
    assert all(line != "secret\nentry" for line in one.get_strings())
    two.append_string("seek +15s")
    assert two.get_strings()[-1] == "seek +15s"
    assert SessionHistory(tmp_path / "another" / "recall.db").get_strings() == []
    assert two.set_saving(False)
    one.append_string("video open")
    assert SessionHistory(path).get_strings() == []
    assert one.clear() and not one.get_strings()


def test_concurrent_recall_is_bounded(tmp_path):
    path = tmp_path / "history.sqlite3"
    assert SessionHistory(path).set_saving(True)
    def write(start):
        history = SessionHistory(path)
        for n in range(start, start + 60):
            history.append_string(f"seek {n}s")
        assert not history.error
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, (1, 61)))
    rows = SessionHistory(path).get_strings()
    assert len(set(rows)) == len(rows) == 100


def test_command_navigation_ignores_command_like_output():
    log = _Transcript()
    log.begin("first")
    log.write("› fake\nend")
    log.begin("second")
    log.write("result")
    second = log.snapshot(-1)[1].text.index("› second")
    assert log.adjacent(0, 1) == second
    assert log.adjacent(second, -1) == 0
    log.clear()
    assert log.adjacent(0, 1) == 0

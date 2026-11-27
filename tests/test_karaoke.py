import hashlib
import json
import threading
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from mariana.karaoke import KaraokeSession, Score, read_score
from mariana.karaoke_stage import sing, stage_lines
from mariana.karaoke_ttml import compare

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/karaoke-duet.json"


class MemoryDB(dict):
    get_state = dict.get
    set_state = dict.__setitem__


@pytest.fixture
def parsed():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "a song.raw"
    path.write_bytes(b"mariana duet fixture")
    return SimpleNamespace(media=SimpleNamespace(source="local", duration=4, stable_id="A", original_uri=str(path),
                                                 capabilities=SimpleNamespace(live=False)), state="paused",
                           position=1.35, duration=4)


def test_common_fixture_and_word_selection(parsed):
    score = Score(parsed)
    assert score.reason(parsed["media_sha256"], 4000) == ""
    assert score.score == .90
    assert score.singers == ["Alto", "Tenor"]
    assert not score.segment(999)["voices"] and score.segment(1000)["voices"]
    assert score.segment(4000) is None
    selected = [text for style, text in stage_lines(score, 1350, None) if style == "class:active"]
    assert selected == ["Oh", "Oo"]
    assert [text for style, text in stage_lines(score, 1600, "Alto") if style == "class:active"] == ["ah"]
    assert not [text for style, text in stage_lines(score, 2800, None) if style == "class:active"]
    assert score.seek_line(5, True) == 1000
    assert score.seek_line(1500, False) == 1000


@pytest.mark.parametrize("change", [
    lambda a: a.update(duration_ms=5000),
    lambda a: a["segments"][0].update(start_ms=200),
    lambda a: a["segments"][1].update(start_ms=900),
    lambda a: a["segments"][1]["voices"][0]["words"][1].update(start_ms=1500),
    lambda a: a["segments"][1]["voices"][0]["words"][1].update(end_ms=3500),
    lambda a: a["segments"][1]["voices"][1].update(singer="Alto"),
    lambda a: a["segments"][1]["voices"][1].update(words=[]),
    lambda a: a["segments"][1]["voices"][1]["words"][0].update(text="abc\x1bc"),
    lambda a: a.update(confidence=True),
    lambda a: a.update(confidence=float("nan")),
    lambda a: a.update(media_sha256="00"),
])
def test_malformed_or_incomplete_evidence_fails_closed(parsed, change):
    change(parsed)
    with pytest.raises(ValueError):
        Score(parsed)


def test_whole_score_uses_weakest_word_even_in_another_singer_part(parsed, media):
    parsed["segments"][1]["voices"][1]["words"][0]["confidence"] = .89999
    session = KaraokeSession(MemoryDB())
    session.install(media, Score(parsed))
    state = session.stage(media, include_sheet=True)
    assert not state["available"] and "89.99%" in state["reason"] and state["sheet"] is None


def test_identity_duration_sidecar_persistence_and_clear(media, parsed):
    db = MemoryDB()
    session = KaraokeSession(db)
    assert not session.stage(media)["available"]
    session.install(media, Score(parsed))
    assert KaraokeSession(db).stage(media)["available"]
    assert session.select(media, "Alto") == "Alto"
    media.duration = 4.4
    assert "250 ms" in session.stage(media)["reason"]
    media.duration = 4
    session.forget(media)
    assert not session.stage(media)["available"]
    path = Path(media.media.original_uri)
    path.with_name(path.name + ".karaoke.json").write_text(json.dumps(parsed))
    assert KaraokeSession(MemoryDB()).stage(media)["available"]
    path.write_bytes(b"a replacement version")
    assert "mismatch" in session.stage(media)["reason"]
    with pytest.raises(ValueError, match="different recording"):
        session.install(media, Score(parsed))
    media.media.source = "url"
    assert "local" in session.stage(media)["reason"]


def test_demo_hash_duration_and_gate():
    audio = ROOT / "res/karaoke/practice-duet.wav"
    score = read_score(audio.with_suffix(".json"))
    with wave.open(str(audio)) as recording:
        duration = round(1000 * recording.getnframes() / recording.getframerate())
    assert score.reason(hashlib.sha256(audio.read_bytes()).hexdigest(), duration) == ""
    assert score.score == 1 and len(score.singers) == 2


def test_terminal_stage_accepts_pause_and_exit(media, parsed):
    session = KaraokeSession(MemoryDB())
    session.install(media, Score(parsed))
    commands = []
    with create_pipe_input() as pipe:
        def command(text):
            commands.append(text)
            pipe.send_text("q")
        pipe.send_text(" ")
        timer = threading.Timer(3, lambda: pipe.send_text("q"))
        timer.start()
        try:
            sing(session, lambda: media, command, {}, lambda: True, input=pipe, output=DummyOutput())
        finally:
            timer.cancel()
    assert commands == ["p"]


def timed_xml(boundary, text="hey", total="4s"):
    return f'''<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttm="http://www.w3.org/ns/ttml#metadata">
    <head><metadata><ttm:agent xml:id="v1"><ttm:name>Alto</ttm:name></ttm:agent></metadata></head>
    <body dur="{total}"><div><p ttm:role="x-instrumental" begin="0s" end="1s"/><p begin="1s" end="3s" ttm:agent="v1">
    <span begin="{boundary}ms" end="1s">{text}</span>
    </p><p begin="1s" end="3s" ttm:agent="Bass">
    <span begin="100ms" end="1.25s">oh</span></p><p ttm:role="x-instrumental" begin="3s" end="4s"/></div></body></tt>'''


def test_independent_ttml_full_recording_and_grade(tmp_path, parsed):
    a, b = tmp_path / "a.ttml", tmp_path / "b.ttml"
    a.write_text(timed_xml(100))
    b.write_text(timed_xml(200))
    score = compare(a, b, parsed["media_sha256"], 4000)
    assert score.score == .9
    assert set(score.singers) == {"Alto", "Bass"}
    assert len(score.segment(1150)["voices"]) == 2
    b.write_text(timed_xml(201))
    assert "below" in compare(a, b, score.digest, 4000).reason(score.digest, 4000)
    for bad in (timed_xml(100), timed_xml(150, "oh"), timed_xml(200, total="10s"),
                timed_xml(150).replace("begin=\"150ms\" end=\"1s\"", ""),
                timed_xml(100).replace("<head>", "<head>\n "),
                timed_xml(150).replace('<p ttm:role="x-instrumental" begin="3s" end="4s"/>', ""),
                timed_xml(150).replace('begin="0s" end="1s"', 'begin="0s" end="2s"'),
                "<!DOCTYPE tt []>" + timed_xml(101)):
        b.write_text(bad)
        with pytest.raises(ValueError):
            compare(a, b, score.digest, 4000)


def test_natively_labelled_lyrics_work_without_claiming_timing_accuracy(media, tmp_path):
    from mariana.karaoke_ttml import attributed_lyrics

    path = tmp_path / "lyrics.ttml"
    path.write_text('''<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttm="http://www.w3.org/ns/ttml#metadata">
    <body><div ttm:agent="Bass"><p>Sing <span>today</span></p>
    <p><span ttm:agent="Alto">Echo</span></p></div></body></tt>''')
    session = KaraokeSession(MemoryDB())
    rows = session.lyrics(media, attributed_lyrics(path))
    assert rows == [("Bass", "Sing today"), ("Alto", "Echo")]
    assert session.lyrics(media) == rows
    assert not session.stage(media)["available"]

def test_one_running_stage_can_be_stopped_from_another_control():
    session = KaraokeSession(MemoryDB())
    first = session.begin_stage()
    with pytest.raises(ValueError, match="already open"):
        session.begin_stage()
    assert session.stop() and first.is_set()
    session.end_stage(first)
    assert not session.stop()
    second = session.begin_stage()
    assert not second.is_set()
    session.end_stage(second)


def test_duet_invitation_roundtrip_preview_and_explicit_accept(media, parsed, tmp_path):
    from mariana.karaoke_invite import KEYS
    from unittest.mock import Mock
    sender = KaraokeSession(MemoryDB())
    sender.install(media, Score(parsed))
    media.position = 1.325
    sender.select(media, "Tenor")
    path = tmp_path / "Duet invitation.json"
    invitation = sender.export_invite(media, path)
    assert json.loads((ROOT / "tests/fixtures/karaoke-invite.json").read_text()) == invitation
    assert set(invitation) == KEYS
    payload = path.read_text()
    assert all(token not in payload for token in ("lyrics", "a song.raw", "fixture producer", str(tmp_path)))
    with pytest.raises(FileExistsError):
        sender.export_invite(media, path)
    receiver = KaraokeSession(MemoryDB())
    receiver.install(media, Score(parsed))
    receiver.select(media, "Alto")
    media.position = 2
    assert receiver.open_invite(media, path)["part"] == "Tenor"
    assert media.position == 2 and receiver.part == "Alto"
    seek = Mock(side_effect=RuntimeError("cannot seek"))
    with pytest.raises(RuntimeError, match="cannot seek"):
        receiver.accept_invite(media, seek)
    assert receiver.part == "Alto"
    seek.side_effect = None
    receiver.accept_invite(media, seek)
    seek.assert_called_with(1.325)
    assert receiver.part == "Tenor"
    with pytest.raises(ValueError, match="Preview"):
        receiver.accept_invite(media, seek)


def test_invite_accept_rechecks_media_timing_confidence_and_file_shape(media, parsed, tmp_path):
    from unittest.mock import Mock
    session = KaraokeSession(MemoryDB())
    session.install(media, Score(parsed))
    path = tmp_path / "invite.json"
    session.export_invite(media, path, "Tenor")
    session.open_invite(media, path)
    sought = Mock()
    parsed["segments"][1]["voices"][0]["words"][0]["start_ms"] += 1
    session.install(media, Score(parsed))
    with pytest.raises(ValueError, match="timing"):
        session.accept_invite(media, sought)
    parsed["confidence"] = .5
    session.install(media, Score(parsed))
    with pytest.raises(ValueError, match="below"):
        session.accept_invite(media, sought)
    parsed["confidence"] = 1
    session.install(media, Score(parsed))
    data = json.loads(path.read_text())
    data["media_sha256"] = "c" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="different recording"):
        session.open_invite(media, path)
    data["private_url"] = "fixture"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="fields"):
        session.open_invite(media, path)
    sought.assert_not_called()

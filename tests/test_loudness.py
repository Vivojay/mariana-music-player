import math
from dataclasses import replace

import pytest

from mariana.database import SCHEMA_VERSION, MarianaDatabase
from mariana.loudness import (
    LoudnessError,
    LoudnessProfile,
    LoudnessRepository,
    ReplayGainMode,
    RSGainAnalyzer,
    album_identity,
    effective_gain_db,
    linear_gain,
    parse_gain_db,
    parse_peak,
    parse_r128_gain,
    parse_rsgain_output,
    profile_from_tags,
)


def test_replaygain_and_opus_r128_tag_parsing():
    profile = profile_from_tags(
        "song",
        {
            "TXXX:REPLAYGAIN_TRACK_GAIN": ["-7.25 dB"],
            "replaygain_track_peak": "0.900000",
            "----:com.apple.iTunes:replaygain_album_gain": b"-6.00 dB",
            "replaygain_album_peak": "1.10",
        },
        metadata={"album_artist": "Artist", "album": "Album", "disc": "2/2"},
    )
    assert profile.track_gain_db == -7.25
    assert profile.track_peak == 0.9
    assert profile.album_gain_db == -6
    assert profile.album_key == "tags:artist\0album\0" + "2"
    opus = profile_from_tags("opus", {"R128_TRACK_GAIN": "-256", "R128_ALBUM_GAIN": "0"})
    assert opus.track_gain_db == 4.0
    assert opus.album_gain_db == 5.0
    assert parse_r128_gain("invalid") is None


@pytest.mark.parametrize("value", [None, "", "nan", "100 dB", object()])
def test_invalid_gain_values_are_rejected(value):
    assert parse_gain_db(value) is None


def test_peak_and_album_identity_validation():
    assert parse_peak("0") is None
    assert parse_peak("1.2") == 1.2
    assert album_identity({"release_mbid": " ABC "}) == "mbid:abc"
    assert album_identity({"album": "Missing artist"}) is None


def test_effective_gain_modes_preamp_and_peak_safety():
    profile = LoudnessProfile(
        "song", track_gain_db=6, track_peak=0.5, album_gain_db=-2,
        album_peak=0.8, complete_album=True,
    )
    assert effective_gain_db(profile, ReplayGainMode.OFF) == 0
    assert effective_gain_db(profile, ReplayGainMode.TRACK) == pytest.approx(5.0206, abs=0.001)
    assert effective_gain_db(profile, ReplayGainMode.ALBUM) == -2
    assert effective_gain_db(profile, ReplayGainMode.AUTO, album_context=True) == -2
    assert effective_gain_db(profile, ReplayGainMode.TRACK, preamp_db=-2) == 4
    assert effective_gain_db(replace(profile, track_peak=None), ReplayGainMode.TRACK) == 0
    assert linear_gain(6.020599913) == pytest.approx(2.0)


def test_loudness_repository_round_trip_and_content_reuse(tmp_path):
    with MarianaDatabase(tmp_path / "loudness.db") as database:
        assert SCHEMA_VERSION >= 3
        repository = LoudnessRepository(database)
        profile = LoudnessProfile(
            "song", content_signature="content", track_gain_db=-3, track_peak=0.8,
            scanned_at=10,
        )
        repository.save(profile)
        assert repository.get("song") == profile
        assert repository.by_content("content") == profile
        assert repository.by_content(None) is None


def test_rsgain_tsv_and_text_output_parsers(tmp_path):
    song = (tmp_path / "song.flac").resolve()
    output = (
        "Filename\tTrack Gain\tTrack Peak\tAlbum Gain\tAlbum Peak\n"
        f"{song}\t-4.20 dB\t0.75\t-3.10 dB\t0.90\n"
    )
    parsed = parse_rsgain_output(output, [song])[str(song)]
    assert parsed == {
        "track_gain_db": -4.2, "track_peak": 0.75,
        "album_gain_db": -3.1, "album_peak": 0.9,
    }
    fallback = parse_rsgain_output("Track Gain: -2.0 dB\nTrack Peak: 0.5", [song])
    assert fallback[str(song)]["track_gain_db"] == -2
    assert parse_rsgain_output("nothing useful", [song]) == {}


def test_rsgain_37_real_output_shape_uses_basename_and_album_summary(tmp_path):
    first = (tmp_path / "first.wav").resolve()
    second = (tmp_path / "second.wav").resolve()
    output = (
        "Filename\tLoudness (LUFS)\tGain (dB)\tPeak\t Peak (dB)\tPeak Type\tClipping Adjustment?\n"
        "first.wav\t-21.75\t3.75\t0.125093\t-18.06\tTrue\tN\n"
        "second.wav\t-27.62\t9.62\t0.062543\t-24.08\tTrue\tN\n"
        "Album\t-23.82\t5.82\t0.125093\t-18.06\tTrue\tN\n"
    )
    parsed = parse_rsgain_output(output, [first, second])
    assert parsed[str(first)] == {
        "track_gain_db": 3.75,
        "track_peak": 0.125093,
        "album_gain_db": 5.82,
        "album_peak": 0.125093,
    }
    assert parsed[str(second)]["track_peak"] == 0.062543


def test_rsgain_analysis_is_scan_only_and_preserves_media(tmp_path, monkeypatch):
    song = tmp_path / "song.flac"
    song.write_bytes(b"unchanged")
    before = song.stat().st_mtime_ns, song.read_bytes()

    class Result:
        stdout = f"Filename\tTrack Gain\tTrack Peak\n{song.resolve()}\t-3 dB\t0.8\n"
        stderr = ""

    calls = []
    monkeypatch.setattr("mariana.loudness.find_tool_executable", lambda *_args: "rsgain")
    monkeypatch.setattr(
        "mariana.loudness.subprocess.run",
        lambda command, **kwargs: calls.append((command, kwargs)) or Result(),
    )
    result = RSGainAnalyzer().analyze([song])
    assert result[str(song.resolve())]["track_gain_db"] == -3
    command = calls[0][0]
    assert command[:4] == ["rsgain", "custom", "-s", "s"]
    assert "-a" not in command
    assert before == (song.stat().st_mtime_ns, song.read_bytes())
    assert math.isfinite(result[str(song.resolve())]["track_peak"])


def test_rsgain_analyzer_verifies_the_real_executable(monkeypatch):
    monkeypatch.setattr("mariana.loudness.find_tool_executable", lambda *_args: "C:/tools/rsgain.exe")
    monkeypatch.setattr(
        "mariana.loudness.subprocess.run",
        lambda command, **_kwargs: type("Result", (), {"stdout": "rsgain 3.7\n", "stderr": ""})(),
    )
    assert RSGainAnalyzer().verify() == ("C:/tools/rsgain.exe", "rsgain 3.7")
    monkeypatch.setattr(
        "mariana.loudness.subprocess.run",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": "", "stderr": ""})(),
    )
    with pytest.raises(LoudnessError, match="no version information"):
        RSGainAnalyzer().verify()


def test_rsgain_recovers_duplicate_basenames_without_losing_album(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    first, second = (tmp_path / disc / "01 雨.wav" for disc in ("disc 1", "disc 2"))
    header = "Filename\tLoudness (LUFS)\tGain (dB)\tPeak\n"
    quiet = "-22\t4\t0.20"
    loud = "-16\t-2\t0.40"
    together = header + f"{first.name}\t{quiet}\n{second.name}\t{loud}\nAlbum\t-19\t1\t0.40\n"
    run = Mock(side_effect=[
        SimpleNamespace(stdout=text, stderr="") for text in (
            together, header + f"{first.name}\t{quiet}\n", header + f"{second.name}\t{loud}\n",
        )
    ])
    monkeypatch.setattr("mariana.loudness.find_tool_executable", lambda *_args: "rsgain")
    monkeypatch.setattr("mariana.loudness.subprocess.run", run)
    assert parse_rsgain_output(together, [first, second]) == {}
    parsed = RSGainAnalyzer().analyze([first, second], album=True)
    assert parsed[str(first)] == {
        "track_gain_db": 4., "track_peak": .20, "album_gain_db": 1., "album_peak": .40,
    }
    assert parsed[str(second)]["track_gain_db"] == -2.
    assert parsed[str(second)]["album_gain_db"] == 1.
    grouped, one, two = [call.args[0] for call in run.call_args_list]
    assert grouped[-3:] == ["-a", str(first), str(second)]
    assert one[-1] == str(first) and two[-1] == str(second) and "-a" not in one and "-a" not in two


def test_installed_rsgain_scans_real_album_without_mutating_media(tmp_path):
    import os
    from pathlib import Path
    import shutil
    import struct
    import wave

    executable = os.environ.get("MARIANA_TEST_RSGAIN") or shutil.which("rsgain")
    if not executable:
        pytest.skip("Set MARIANA_TEST_RSGAIN to run the real rsgain test")
    analyzer = RSGainAnalyzer(executable, timeout=20)
    _, version = analyzer.verify()
    assert "rsgain" in version.casefold()
    tracks = []
    for disc, amplitude in (("Quiet disc", .10), ("Loud disc", .20)):
        path = Path(tmp_path) / disc / "01 Take.wav"
        path.parent.mkdir()
        # Two seconds of the same tone, shifted by approximately 6 dB.
        period = [round(amplitude * 32767 * math.sin(index * 2 * math.pi / 48)) for index in range(48)]
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, 48_000, 96_000, "NONE", ""))
            audio.writeframes(struct.pack("<48h", *period) * 2_000)
        tracks.append(path.resolve())
    before = [(path.stat().st_mtime_ns, path.read_bytes()) for path in tracks]
    measurements = analyzer.analyze(tracks, album=True)
    quiet, loud = [measurements[str(path)] for path in tracks]
    assert quiet["track_gain_db"] - loud["track_gain_db"] == pytest.approx(6.02, abs=.35)
    assert quiet["track_peak"] == pytest.approx(.10, abs=.006)
    assert loud["track_peak"] == pytest.approx(.20, abs=.006)
    assert quiet["album_gain_db"] is not None and quiet["album_gain_db"] == loud["album_gain_db"]
    assert before == [(path.stat().st_mtime_ns, path.read_bytes()) for path in tracks]

import threading
import time
from pathlib import Path

import pytest

from mariana.models import MediaCapabilities, MediaRef, MediaSource
from mariana.stems import StemError, StemInput, StemService, parse_stem_selection


def finite_media(path: Path, *, stable_id: str = "track-1") -> MediaRef:
    return MediaRef(
        MediaSource.LOCAL,
        str(path),
        stable_id=stable_id,
        title="Test Song",
        duration=180,
        capabilities=MediaCapabilities(finite=True, live=False, seekable=True, downloadable=False),
    )


def test_stem_selection_uses_only_names_the_model_actually_produces():
    assert parse_stem_selection(["acapella"], ("vocals", "drums", "bass", "other")) == ("vocals",)
    assert parse_stem_selection(["voice"], ("vocals", "drums", "bass", "other")) == ("vocals",)
    assert parse_stem_selection(["karaoke"], ("vocals", "drums", "bass", "other")) == (
        "drums",
        "bass",
        "other",
    )
    assert parse_stem_selection(["vocals+drums", "bass"], ("vocals", "drums", "bass", "other")) == (
        "vocals",
        "drums",
        "bass",
    )
    assert parse_stem_selection(["original"], ("vocals", "drums")) == ()
    with pytest.raises(StemError, match="Kicks are part of the drums stem"):
        parse_stem_selection(["kick"], ("vocals", "drums", "bass", "other"))
    with pytest.raises(StemError, match="Melody is not an independently produced stem"):
        parse_stem_selection(["melodies"], ("vocals", "drums", "bass", "other"))
    assert parse_stem_selection(["guitars"], ("vocals", "drums", "bass", "other", "guitar")) == (
        "guitar",
    )
    with pytest.raises(StemError, match="Choose one or more"):
        parse_stem_selection(["  "], ("vocals", "drums"))


def test_stem_service_prepares_selects_exports_and_reuses_cache(tmp_path: Path):
    source = tmp_path / "song.flac"
    source.write_bytes(b"source")
    calls = []

    def runner(input_path, output, model, expected, cancel):
        calls.append((input_path, model, cancel.is_set()))
        output.mkdir(parents=True)
        result = {}
        for name in expected:
            path = output / f"{name}.wav"
            path.write_bytes((name * 4).encode())
            result[name] = path
        return result

    service = StemService(tmp_path / "cache", runner=runner, max_cache_bytes=1024**3)
    media = finite_media(source)
    service.prepare(media, StemInput(str(source), {}))
    manifest = service.wait(2)
    for _ in range(100):
        if service.status().state == "ready":
            break
        time.sleep(0.001)

    assert tuple(manifest.stems) == ("vocals", "drums", "bass", "other")
    assert service.status().public()["available_stems"] == tuple(manifest.stems)
    assert not any(str(tmp_path) in str(value) for value in service.status().public().values())
    assert service.selection(media.stable_id, ["vocals"]) == (manifest.stems["vocals"],)
    assert service.selection(media.stable_id, ["karaoke"]) == tuple(
        manifest.stems[name] for name in ("drums", "bass", "other")
    )
    exported = service.export(media.stable_id, tmp_path / "exports")
    assert {path.name for path in exported} == {f"{name}.wav" for name in manifest.stems}
    assert all(path.read_bytes() for path in exported)
    with pytest.raises(StemError, match="already exists"):
        service.export(media.stable_id, tmp_path / "exports")

    service.prepare(media, StemInput(str(source), {}))
    assert service.wait(2).media_id == media.stable_id
    assert len(calls) == 1

    source.write_bytes(b"changed source")
    service.prepare(media, StemInput(str(source), {}))
    assert service.wait(2).media_id == media.stable_id
    assert len(calls) == 2
    service.shutdown()


@pytest.mark.parametrize("started", [False, True], ids=["before-initialization", "during-separation"])
def test_stem_service_rejects_live_unknown_and_overlapping_jobs(tmp_path: Path, monkeypatch, started):
    source = tmp_path / "song.wav"
    source.write_bytes(b"source")
    release = threading.Event()
    entered = threading.Event()
    begin = threading.Event()
    separating = threading.Event()

    def runner(_input, output, _model, expected, cancel):
        separating.set()
        while not release.wait(0.01):
            if cancel.is_set():
                raise StemError("Stem preparation cancelled")
        output.mkdir(parents=True)
        result = {}
        for name in expected:
            path = output / f"{name}.wav"
            path.write_bytes(b"stem")
            result[name] = path
        return result

    service = StemService(tmp_path / "cache", runner=runner)
    prepare_job = service._prepare_job

    def controlled_start(*args):
        entered.set()
        if not begin.wait(5):
            raise AssertionError("Preparation was not released")
        return prepare_job(*args)

    monkeypatch.setattr(service, "_prepare_job", controlled_start)
    if started:
        begin.set()
    media = finite_media(source)
    service.prepare(media, StemInput(str(source), {}))
    assert entered.wait(5)
    if started:
        assert separating.wait(5)
    with pytest.raises(StemError, match="already running"):
        service.prepare(media, StemInput(str(source), {}))
    assert service.cancel()
    begin.set()
    with pytest.raises(StemError, match="cancelled"):
        service.wait(2)
    assert not service.results.exists() or not any(service.results.iterdir())
    assert service.manifest() is None
    if started:
        assert service.results.is_dir()
    else:
        assert not service.cache_dir.exists()

    live = MediaRef(
        MediaSource.RADIO,
        "https://radio.test/live",
        duration=None,
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False, downloadable=False),
    )
    with pytest.raises(StemError, match="finite media"):
        service.prepare(live, StemInput(live.original_uri, {}))
    service.shutdown()


def test_stem_service_rejects_work_larger_than_its_cache_and_cleans_partial_results(tmp_path: Path):
    source = tmp_path / "song.wav"
    source.write_bytes(b"source")
    service = StemService(tmp_path / "cache", runner=lambda *_args: {}, max_cache_bytes=1)

    service.prepare(finite_media(source), StemInput(str(source), {}))
    with pytest.raises(StemError, match="cache limit"):
        service.wait(2)

    assert not any(service.results.iterdir())
    service.shutdown()


def test_stem_service_clear_is_identity_bound(tmp_path: Path):
    source = tmp_path / "song.wav"
    source.write_bytes(b"source")

    def runner(_input, output, _model, expected, _cancel):
        output.mkdir(parents=True)
        result = {}
        for name in expected:
            result[name] = output / f"{name}.wav"
            result[name].write_bytes(b"stem")
        return result

    service = StemService(tmp_path / "cache", runner=runner)
    media = finite_media(source)
    service.prepare(media, StemInput(str(source), {}))
    service.wait(2)
    assert not service.clear("different-media")
    assert service.clear(media.stable_id)
    assert service.manifest(media.stable_id) is None
    service.shutdown()

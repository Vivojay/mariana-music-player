from __future__ import annotations

import base64
import io
import os
import re
import threading
from pathlib import Path

import pytest
import requests
from PIL import Image

from mariana import artwork
from mariana.artwork import (
    ArtworkFetchError,
    ArtworkManager,
    ArtworkOrigin,
    ArtworkState,
    FetchedArtwork,
    SafeArtworkFetcher,
)


def _image_bytes(image_format: str = "PNG", *, size: tuple[int, int] = (8, 8), color: str = "blue") -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format=image_format)
    return stream.getvalue()


class _RecordingFetcher:
    def __init__(self, data: bytes, content_type: str | None = "image/png") -> None:
        self.data = data
        self.content_type = content_type
        self.calls: list[str] = []

    def fetch(self, url: str, *, cancel: threading.Event, max_bytes: int) -> FetchedArtwork:
        assert not cancel.is_set()
        assert max_bytes > 0
        self.calls.append(url)
        return FetchedArtwork(self.data, self.content_type)


def test_adjacent_artwork_loads_offline_with_sanitized_projection(tmp_path: Path, monkeypatch) -> None:
    media_path = tmp_path / "recording.mp3"
    media_path.touch()
    expected = _image_bytes(color="green")
    (tmp_path / "Cover.png").write_bytes(expected)
    monkeypatch.setattr(artwork, "MutagenFile", lambda *_args, **_kwargs: None)
    secret_identity = "private-library-identity"

    with ArtworkManager(tmp_path / "cache", automatic_online=False) as manager:
        manager.activate(secret_identity, projection_media_id="media-42", local_path=media_path)
        projection = manager.wait_for_idle()

        assert projection.state == ArtworkState.READY
        assert projection.source == ArtworkOrigin.ADJACENT
        assert projection.automatic_online is False
        payload = projection.to_dict()
        assert payload == {
            "schema_version": 1,
            "media_id": "media-42",
            "state": "ready",
            "available": True,
            "automatic_online": False,
            "cache_key": projection.cache_key,
            "mime_type": "image/png",
            "source": "adjacent",
            "unavailable_reason": None,
        }
        assert re.fullmatch(r"[0-9a-f]{64}\.png", str(projection.cache_key))
        assert secret_identity not in repr(payload)
        assert str(tmp_path) not in repr(payload)

        current = manager.current_image(projection.cache_key)
        assert current is not None
        assert current.path.read_bytes() == expected
        assert manager.current_image("0" * 64 + ".png") is None


def test_adjacent_artwork_allowlist_is_case_insensitive_and_deterministic(tmp_path: Path, monkeypatch) -> None:
    media_path = tmp_path / "recording.mp3"
    media_path.touch()
    expected = _image_bytes("JPEG", color="purple")
    (tmp_path / "Cover.JPG").write_bytes(expected)
    (tmp_path / "recording.jpg").write_bytes(_image_bytes("JPEG", color="red"))
    (tmp_path / "cover.gif").write_bytes(b"not accepted")
    monkeypatch.setattr(artwork, "MutagenFile", lambda *_args, **_kwargs: None)

    with ArtworkManager(tmp_path / "cache") as manager:
        manager.activate("track", local_path=media_path)
        projection = manager.wait_for_idle()
        current = manager.current_image()

    assert projection.state == ArtworkState.READY
    assert projection.source == ArtworkOrigin.ADJACENT
    assert projection.mime_type == "image/jpeg"
    assert current is not None
    assert current.path.read_bytes() == expected


def test_embedded_artwork_precedes_adjacent_artwork(tmp_path: Path, monkeypatch) -> None:
    embedded = _image_bytes(color="red")
    adjacent = _image_bytes(color="green")
    media_path = tmp_path / "recording.flac"
    media_path.touch()
    (tmp_path / "cover.png").write_bytes(adjacent)

    class Picture:
        data = embedded
        mime = "image/png"

    class TaggedMedia:
        def __init__(self) -> None:
            self.pictures = [Picture()]
            self.tags = {}

    monkeypatch.setattr(artwork, "MutagenFile", lambda *_args, **_kwargs: TaggedMedia())

    with ArtworkManager(tmp_path / "cache") as manager:
        manager.activate("track", local_path=media_path)
        projection = manager.wait_for_idle()
        current = manager.current_image()

    assert projection.source == ArtworkOrigin.EMBEDDED
    assert current is not None
    assert current.path.read_bytes() == embedded


def test_changed_local_artwork_replaces_identity_cache(tmp_path: Path, monkeypatch) -> None:
    media_path = tmp_path / "recording.mp3"
    media_path.touch()
    cover_path = tmp_path / "cover.png"
    cover_path.write_bytes(_image_bytes(color="red"))
    monkeypatch.setattr(artwork, "MutagenFile", lambda *_args, **_kwargs: None)
    cache = tmp_path / "cache"

    with ArtworkManager(cache) as manager:
        manager.activate("stable-local-identity", local_path=media_path)
        original = manager.wait_for_idle()
        assert original.source == ArtworkOrigin.ADJACENT

    cover_path.write_bytes(_image_bytes(color="green"))
    with ArtworkManager(cache) as manager:
        manager.activate("stable-local-identity", local_path=media_path)
        refreshed = manager.wait_for_idle()
        current = manager.current_image()

    assert refreshed.source == ArtworkOrigin.ADJACENT
    assert refreshed.cache_key == original.cache_key
    assert current is not None
    with Image.open(current.path) as image:
        assert image.getpixel((0, 0)) == (0, 128, 0)


def test_online_artwork_requires_preference_or_explicit_one_shot(tmp_path: Path) -> None:
    image = _image_bytes()
    fetcher = _RecordingFetcher(image)
    provider_url = "https://media.example/artwork.png?signature=private"

    with ArtworkManager(tmp_path / "cache", automatic_online=False, fetcher=fetcher) as manager:
        manager.activate(
            "episode-guid",
            projection_media_id="episode-7",
            trusted_provider_url=provider_url,
        )
        disabled = manager.wait_for_idle()

        assert disabled.state == ArtworkState.DISABLED
        assert disabled.available is False
        assert disabled.automatic_online is False
        assert fetcher.calls == []
        assert provider_url not in repr(disabled.to_dict())

        assert manager.fetch_current() is not None
        ready = manager.wait_for_idle()

        assert ready.state == ArtworkState.READY
        assert ready.source == ArtworkOrigin.PROVIDER
        assert ready.automatic_online is False
        assert fetcher.calls == [provider_url]


def test_explicit_fetch_is_bound_to_expected_projected_media(tmp_path: Path) -> None:
    fetcher = _RecordingFetcher(_image_bytes())
    with ArtworkManager(tmp_path / "cache", automatic_online=False, fetcher=fetcher) as manager:
        manager.activate(
            "old-identity",
            projection_media_id="old-media",
            trusted_provider_url="https://media.example/old.png",
        )
        assert manager.wait_for_idle().state == ArtworkState.DISABLED
        manager.activate(
            "new-identity",
            projection_media_id="new-media",
            trusted_provider_url="https://media.example/new.png",
        )
        assert manager.wait_for_idle().state == ArtworkState.DISABLED

        assert manager.fetch_current("old-media") is None
        assert manager.fetch_current("https://private.example/id") is None
        assert manager.projection().media_id == "new-media"
        assert fetcher.calls == []

        assert manager.fetch_current("new-media") is not None
        ready = manager.wait_for_idle()

    assert ready.state == ArtworkState.READY
    assert ready.media_id == "new-media"
    assert fetcher.calls == ["https://media.example/new.png"]


def test_explicit_fetch_holds_target_binding_during_start(tmp_path: Path, monkeypatch) -> None:
    fetcher = _RecordingFetcher(_image_bytes())
    with ArtworkManager(tmp_path / "cache", automatic_online=False, fetcher=fetcher) as manager:
        manager.activate(
            "old-identity",
            projection_media_id="old-media",
            trusted_provider_url="https://media.example/old.png",
        )
        assert manager.wait_for_idle().state == ArtworkState.DISABLED

        entered_start = threading.Event()
        release_start = threading.Event()
        activation_finished = threading.Event()
        original_start = manager._start

        def delayed_start(request, *, explicit_online):
            entered_start.set()
            assert release_start.wait(2)
            return original_start(request, explicit_online=explicit_online)

        monkeypatch.setattr(manager, "_start", delayed_start)
        fetch_thread = threading.Thread(target=lambda: manager.fetch_current("old-media"))
        fetch_thread.start()
        assert entered_start.wait(1)

        def activate_new() -> None:
            manager.activate(
                "new-identity",
                projection_media_id="new-media",
                trusted_provider_url="https://media.example/new.png",
            )
            activation_finished.set()

        activation_thread = threading.Thread(target=activate_new)
        activation_thread.start()
        assert not activation_finished.wait(0.05)
        release_start.set()
        fetch_thread.join(2)
        activation_thread.join(2)
        assert activation_finished.is_set()
        assert manager.wait_for_idle().media_id == "new-media"


def test_update_callback_reports_loading_completion_configuration_clear_and_close(tmp_path: Path) -> None:
    updates: list[dict[str, object]] = []
    manager = ArtworkManager(tmp_path / "cache", on_update=updates.append)

    manager.activate("media", projection_media_id="public-media")
    manager.wait_for_idle()
    manager.clear()
    manager.set_automatic_online(True)
    manager.close()

    assert [update["state"] for update in updates] == ["loading", "unavailable", "idle", "idle", "unavailable"]
    assert updates[0]["media_id"] == "public-media"
    assert updates[1]["unavailable_reason"] == "No artwork is available for this media"
    assert updates[3]["automatic_online"] is True
    assert updates[-1]["media_id"] is None
    assert all(set(update) == set(updates[0]) for update in updates)


def test_update_callback_failure_does_not_break_artwork_resolution(tmp_path: Path, monkeypatch) -> None:
    media_path = tmp_path / "recording.mp3"
    media_path.touch()
    (tmp_path / "cover.png").write_bytes(_image_bytes())
    monkeypatch.setattr(artwork, "MutagenFile", lambda *_args, **_kwargs: None)

    def fail_update(_projection: dict[str, object]) -> None:
        raise RuntimeError("consumer failed")

    with ArtworkManager(tmp_path / "cache", on_update=fail_update) as manager:
        manager.activate("media", local_path=media_path)
        projection = manager.wait_for_idle()

    assert projection.state == ArtworkState.READY


def test_cache_survives_manager_restart_and_provider_url_change(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    first_url = "https://media.example/old.png?token=old"
    next_url = "https://cdn.example/new.png?token=new"
    first_fetcher = _RecordingFetcher(_image_bytes(color="purple"))
    with ArtworkManager(cache, automatic_online=True, fetcher=first_fetcher) as manager:
        manager.activate("stable-episode-guid", trusted_provider_url=first_url)
        first = manager.wait_for_idle()
        assert first.state == ArtworkState.READY

    offline_fetcher = _RecordingFetcher(_image_bytes(color="orange"))
    with ArtworkManager(cache, automatic_online=False, fetcher=offline_fetcher) as manager:
        manager.activate("stable-episode-guid", trusted_provider_url=next_url)
        cached = manager.wait_for_idle()

        assert cached.state == ArtworkState.READY
        assert cached.source == ArtworkOrigin.CACHE
        assert cached.cache_key == first.cache_key
        assert offline_fetcher.calls == []
        assert first_url not in repr(cached.to_dict())
        assert next_url not in repr(cached.to_dict())


def test_stale_remote_completion_cannot_replace_new_media(tmp_path: Path) -> None:
    old_started = threading.Event()
    release_old = threading.Event()

    class OutOfOrderFetcher:
        def fetch(self, url: str, *, cancel: threading.Event, max_bytes: int) -> FetchedArtwork:
            del cancel, max_bytes
            if url.endswith("old.png"):
                old_started.set()
                assert release_old.wait(2)
                return FetchedArtwork(_image_bytes(color="red"), "image/png")
            return FetchedArtwork(_image_bytes(color="blue"), "image/png")

    with ArtworkManager(
        tmp_path / "cache",
        automatic_online=True,
        fetcher=OutOfOrderFetcher(),
        max_workers=2,
    ) as manager:
        manager.activate("old-id", projection_media_id="old", trusted_provider_url="https://x.example/old.png")
        assert old_started.wait(1)
        manager.activate("new-id", projection_media_id="new", trusted_provider_url="https://x.example/new.png")
        current_projection = manager.wait_for_idle()
        assert current_projection.media_id == "new"
        assert current_projection.state == ArtworkState.READY
        expected_key = current_projection.cache_key
        release_old.set()
        assert manager.wait_for_idle().cache_key == expected_key

        current = manager.current_image(expected_key)
        assert current is not None
        with Image.open(current.path) as image:
            assert image.getpixel((0, 0)) == (0, 0, 255)


def test_rapid_activation_discards_queued_stale_work(tmp_path: Path) -> None:
    first_started = threading.Event()
    release_first = threading.Event()

    class BlockingFetcher:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def fetch(self, url: str, *, cancel: threading.Event, max_bytes: int) -> FetchedArtwork:
            del cancel, max_bytes
            self.calls.append(url)
            if url.endswith("first.png"):
                first_started.set()
                assert release_first.wait(2)
            return FetchedArtwork(_image_bytes(), "image/png")

    fetcher = BlockingFetcher()
    with ArtworkManager(
        tmp_path / "cache",
        automatic_online=True,
        fetcher=fetcher,
        max_workers=1,
    ) as manager:
        manager.activate("first", trusted_provider_url="https://public.example/first.png")
        assert first_started.wait(1)
        for index in range(20):
            manager.activate(
                f"stale-{index}",
                trusted_provider_url=f"https://public.example/stale-{index}.png",
            )
        manager.activate("latest", trusted_provider_url="https://public.example/latest.png")
        release_first.set()
        projection = manager.wait_for_idle()

    assert projection.state == ArtworkState.READY
    assert fetcher.calls == [
        "https://public.example/first.png",
        "https://public.example/latest.png",
    ]


def test_cache_replace_and_eviction_are_atomic_across_track_changes(tmp_path: Path, monkeypatch) -> None:
    first_cleanup_entered = threading.Event()
    release_first_cleanup = threading.Event()

    class ColorFetcher:
        def fetch(self, url: str, *, cancel: threading.Event, max_bytes: int) -> FetchedArtwork:
            del cancel, max_bytes
            color = "red" if url.endswith("first.png") else "blue"
            return FetchedArtwork(_image_bytes(color=color), "image/png")

    with ArtworkManager(
        tmp_path / "cache",
        automatic_online=True,
        fetcher=ColorFetcher(),
        max_cache_entries=1,
        max_workers=2,
    ) as manager:
        original_cleanup = manager._cleanup_cache
        first_key = manager._cache_key("first")

        def controlled_cleanup(preserve=None, *, remove_temporary=False):
            if preserve is not None and preserve.name.startswith(first_key):
                first_cleanup_entered.set()
                assert release_first_cleanup.wait(2)
            return original_cleanup(preserve, remove_temporary=remove_temporary)

        monkeypatch.setattr(manager, "_cleanup_cache", controlled_cleanup)
        manager.activate("first", trusted_provider_url="https://media.example/first.png")
        assert first_cleanup_entered.wait(1)

        # The replacement and its size/count eviction pass must hold one lock;
        # otherwise a newer worker can publish between them and be deleted by
        # this stale cleanup pass.
        lock_was_available = manager._lock.acquire(blocking=False)
        if lock_was_available:
            manager._lock.release()

        second_start_entered = threading.Event()
        original_start = manager._start

        def observed_start(request, *, explicit_online):
            second_start_entered.set()
            return original_start(request, explicit_online=explicit_online)

        monkeypatch.setattr(manager, "_start", observed_start)
        activation = threading.Thread(
            target=lambda: manager.activate(
                "second",
                projection_media_id="second",
                trusted_provider_url="https://media.example/second.png",
            )
        )
        activation.start()
        assert second_start_entered.wait(1)
        release_first_cleanup.set()
        activation.join(2)

        assert lock_was_available is False
        assert not activation.is_alive()
        projection = manager.wait_for_idle()
        current = manager.current_image()

    assert projection.state == ArtworkState.READY
    assert projection.media_id == "second"
    assert current is not None
    assert current.path.exists()
    assert [path.name for path in (tmp_path / "cache").iterdir()] == [current.cache_key]


def test_disabling_online_cancels_pending_fetch(tmp_path: Path) -> None:
    started = threading.Event()
    cancelled = threading.Event()

    class CooperativeFetcher:
        def fetch(self, url: str, *, cancel: threading.Event, max_bytes: int) -> FetchedArtwork:
            del url, max_bytes
            started.set()
            assert cancel.wait(2)
            cancelled.set()
            raise artwork.ArtworkCancelled("cancelled")

    with ArtworkManager(tmp_path / "cache", automatic_online=True, fetcher=CooperativeFetcher()) as manager:
        manager.activate("remote-id", trusted_provider_url="https://media.example/cover.png")
        assert started.wait(1)
        manager.set_automatic_online(False)
        projection = manager.wait_for_idle()

        assert cancelled.wait(1)
        assert projection.state == ArtworkState.DISABLED
        assert projection.automatic_online is False


@pytest.mark.parametrize(
    ("data", "content_type", "max_encoded_bytes", "max_pixels"),
    [
        (b"not an image", "image/png", 1024, 10_000),
        (_image_bytes(), "image/jpeg", 1024, 10_000),
        (_image_bytes(size=(20, 20)), "image/png", 1024, 100),
        (b"x" * 101, "image/png", 100, 10_000),
    ],
)
def test_invalid_or_oversized_provider_artwork_is_refused(
    tmp_path: Path,
    data: bytes,
    content_type: str,
    max_encoded_bytes: int,
    max_pixels: int,
) -> None:
    fetcher = _RecordingFetcher(data, content_type)
    with ArtworkManager(
        tmp_path / content_type.replace("/", "-"),
        automatic_online=True,
        fetcher=fetcher,
        max_encoded_bytes=max_encoded_bytes,
        max_pixels=max_pixels,
    ) as manager:
        manager.activate("media", trusted_provider_url="https://media.example/cover")
        projection = manager.wait_for_idle()

        assert projection.state == ArtworkState.ERROR
        assert projection.available is False
        assert projection.cache_key is None
        assert manager.current_image() is None


@pytest.mark.parametrize(
    ("image_format", "content_type", "extension"),
    [("JPEG", "image/jpeg", "jpg"), ("PNG", "image/png", "png"), ("WEBP", "image/webp", "webp")],
)
def test_supported_still_image_types_are_detected_from_bytes(
    tmp_path: Path,
    image_format: str,
    content_type: str,
    extension: str,
) -> None:
    with ArtworkManager(
        tmp_path / image_format,
        automatic_online=True,
        fetcher=_RecordingFetcher(_image_bytes(image_format), content_type),
    ) as manager:
        manager.activate(image_format, trusted_provider_url="https://media.example/cover")
        projection = manager.wait_for_idle()

    assert projection.state == ArtworkState.READY
    assert projection.mime_type == content_type
    assert str(projection.cache_key).endswith(f".{extension}")


@pytest.mark.parametrize("tag_kind", ["apic", "covr", "metadata_block_picture"])
def test_common_embedded_tag_formats_are_supported(tmp_path: Path, monkeypatch, tag_kind: str) -> None:
    expected = _image_bytes()

    class TaggedValue:
        data = expected
        mime = "image/png"

    if tag_kind == "apic":
        tags = {"APIC:front": TaggedValue()}
    elif tag_kind == "covr":
        tags = {"covr": [expected]}
    else:
        picture = artwork.Picture()
        picture.data = expected
        picture.mime = "image/png"
        tags = {"metadata_block_picture": base64.b64encode(picture.write()).decode("ascii")}

    tagged_media = type("TaggedMedia", (), {"pictures": [], "tags": tags})()
    monkeypatch.setattr(artwork, "MutagenFile", lambda *_args, **_kwargs: tagged_media)
    media_path = tmp_path / f"{tag_kind}.audio"
    media_path.touch()

    with ArtworkManager(tmp_path / f"cache-{tag_kind}") as manager:
        manager.activate(tag_kind, local_path=media_path)
        projection = manager.wait_for_idle()
        current = manager.current_image()

    assert projection.state == ArtworkState.READY
    assert projection.source == ArtworkOrigin.EMBEDDED
    assert current is not None
    assert current.path.read_bytes() == expected


def test_invalid_embedded_candidates_fall_through_to_valid_adjacent_artwork(tmp_path: Path, monkeypatch) -> None:
    expected = _image_bytes(color="green")
    media_path = tmp_path / "recording.mp3"
    media_path.touch()
    (tmp_path / "folder.png").write_bytes(expected)
    tagged_media = type(
        "TaggedMedia",
        (),
        {
            "pictures": [type("Picture", (), {"data": b"malformed", "mime": "image/png"})()],
            "tags": {
                "metadata_block_picture": ["not base64", object()],
                "unrelated": "ignored",
            },
        },
    )()
    monkeypatch.setattr(artwork, "MutagenFile", lambda *_args, **_kwargs: tagged_media)

    with ArtworkManager(tmp_path / "cache") as manager:
        manager.activate("track", local_path=media_path)
        projection = manager.wait_for_idle()
        current = manager.current_image()

    assert projection.state == ArtworkState.READY
    assert projection.source == ArtworkOrigin.ADJACENT
    assert current is not None
    assert current.path.read_bytes() == expected


def test_invalid_local_artwork_reports_unavailable_without_leaking_details(tmp_path: Path, monkeypatch) -> None:
    media_path = tmp_path / "private-name.mp3"
    media_path.touch()
    tagged_media = type(
        "TaggedMedia",
        (),
        {"pictures": [type("Picture", (), {"data": b"bad", "mime": "image/png"})()], "tags": {}},
    )()
    monkeypatch.setattr(artwork, "MutagenFile", lambda *_args, **_kwargs: tagged_media)

    with ArtworkManager(tmp_path / "cache") as manager:
        manager.activate("private-id", projection_media_id="media", local_path=media_path)
        projection = manager.wait_for_idle()

    assert projection.state == ArtworkState.UNAVAILABLE
    assert projection.unavailable_reason == "Artwork is invalid or unsupported"
    assert "private-name" not in repr(projection.to_dict())


def test_metadata_reader_failure_does_not_prevent_adjacent_artwork(tmp_path: Path, monkeypatch) -> None:
    media_path = tmp_path / "recording.mp3"
    media_path.touch()
    expected = _image_bytes()
    (tmp_path / "front.png").write_bytes(expected)

    def fail_metadata(*_args, **_kwargs):
        raise artwork.MutagenError("broken tags")

    monkeypatch.setattr(artwork, "MutagenFile", fail_metadata)
    with ArtworkManager(tmp_path / "cache") as manager:
        manager.activate("track", local_path=media_path)
        projection = manager.wait_for_idle()

    assert projection.state == ArtworkState.READY
    assert projection.source == ArtworkOrigin.ADJACENT


def test_corrupt_or_mislabeled_cache_is_replaced_from_provider(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    with ArtworkManager(
        cache,
        automatic_online=True,
        fetcher=_RecordingFetcher(_image_bytes(color="red")),
    ) as manager:
        manager.activate("stable", trusted_provider_url="https://media.example/old.png")
        original = manager.wait_for_idle()
        original_image = manager.current_image()
        assert original_image is not None

    original_image.path.write_bytes(b"corrupt")
    replacement_fetcher = _RecordingFetcher(_image_bytes(color="green"))
    with ArtworkManager(cache, automatic_online=True, fetcher=replacement_fetcher) as manager:
        manager.activate("stable", trusted_provider_url="https://media.example/new.png")
        replacement = manager.wait_for_idle()

    assert replacement.state == ArtworkState.READY
    assert replacement.source == ArtworkOrigin.PROVIDER
    assert replacement.cache_key == original.cache_key
    assert replacement_fetcher.calls == ["https://media.example/new.png"]

    replacement_path = cache / str(replacement.cache_key)
    mislabeled = replacement_path.with_suffix(".jpg")
    replacement_path.replace(mislabeled)
    final_fetcher = _RecordingFetcher(_image_bytes("JPEG", color="blue"), "image/jpeg")
    with ArtworkManager(cache, automatic_online=True, fetcher=final_fetcher) as manager:
        manager.activate("stable", trusted_provider_url="https://media.example/final.jpg")
        final = manager.wait_for_idle()

    assert final.state == ArtworkState.READY
    assert final.mime_type == "image/jpeg"
    assert final_fetcher.calls == ["https://media.example/final.jpg"]
    assert mislabeled.read_bytes() == final_fetcher.data


def test_cache_startup_removes_partial_files_but_preserves_unrelated_files(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    partial = cache / ".interrupted.tmp"
    unrelated = cache / "README.txt"
    partial.write_bytes(b"partial")
    unrelated.write_text("owned by another cache user", encoding="utf-8")

    with ArtworkManager(cache):
        pass

    assert not partial.exists()
    assert unrelated.read_text(encoding="utf-8") == "owned by another cache user"


def test_current_image_refuses_a_missing_cache_file(tmp_path: Path) -> None:
    with ArtworkManager(
        tmp_path / "cache",
        automatic_online=True,
        fetcher=_RecordingFetcher(_image_bytes()),
    ) as manager:
        manager.activate("media", trusted_provider_url="https://media.example/cover.png")
        projection = manager.wait_for_idle()
        image = manager.current_image()
        assert image is not None
        image.path.unlink()
        assert manager.current_image(projection.cache_key) is None


def test_manager_validates_configuration_and_activation_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="validation limits"):
        ArtworkManager(tmp_path / "invalid-validation", max_dimension=0)
    with pytest.raises(ValueError, match="cache limits"):
        ArtworkManager(tmp_path / "invalid-cache", cache_ttl_seconds=0)

    with ArtworkManager(tmp_path / "cache") as manager:
        assert manager.fetch_current() is None
        assert manager.set_automatic_online(False) is None
        manager.clear()
        with pytest.raises(ValueError, match="stable current-media identity"):
            manager.activate("  ")


def test_wait_timeout_and_unexpected_fetch_failure_are_nonfatal(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    class FailingFetcher:
        def fetch(self, url: str, *, cancel: threading.Event, max_bytes: int) -> FetchedArtwork:
            del url, cancel, max_bytes
            started.set()
            assert release.wait(2)
            raise RuntimeError("private provider failure")

    with ArtworkManager(
        tmp_path / "cache",
        automatic_online=True,
        fetcher=FailingFetcher(),
    ) as manager:
        manager.activate("media", projection_media_id="public", trusted_provider_url="https://example.test")
        assert started.wait(1)
        assert manager.wait_for_idle(timeout=0).state == ArtworkState.LOADING
        release.set()
        projection = manager.wait_for_idle()

    assert projection.state == ArtworkState.ERROR
    assert projection.unavailable_reason == "Artwork could not be loaded safely"
    assert "private provider failure" not in repr(projection.to_dict())


def test_cache_cleanup_removes_expired_and_excess_entries(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    fetcher = _RecordingFetcher(_image_bytes())
    with ArtworkManager(cache, automatic_online=True, fetcher=fetcher, max_cache_entries=1) as manager:
        manager.activate("first", trusted_provider_url="https://media.example/first.png")
        first = manager.wait_for_idle()
        first_path = manager.current_image(first.cache_key)
        assert first_path is not None
        manager.activate("second", trusted_provider_url="https://media.example/second.png")
        second = manager.wait_for_idle()
        assert second.state == ArtworkState.READY
        assert len(list(cache.glob("[0-9a-f]*.*"))) == 1

    only_entry = next(cache.iterdir())
    os.utime(only_entry, (1, 1))
    with ArtworkManager(cache, cache_ttl_seconds=1):
        assert list(cache.iterdir()) == []


class _Response:
    def __init__(
        self,
        status: int,
        *,
        headers: dict[str, str] | None = None,
        data: bytes = b"",
        peer_address: str = "93.184.216.34",
    ) -> None:
        self.status_code = status
        self.headers = headers or {}
        self.data = data
        self.peer_address = peer_address
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size: int):
        assert chunk_size > 0
        yield self.data

    def close(self) -> None:
        self.closed = True


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.urls: list[str] = []
        self.closed = False

    def get(self, url: str, **kwargs) -> _Response:
        assert kwargs["allow_redirects"] is False
        self.urls.append(url)
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def _address_resolver(host: str, _port: int, **_kwargs):
    address = "93.184.216.34" if host == "public.example" else "127.0.0.1"
    return [(2, 1, 6, "", (address, 443))]


def test_safe_fetcher_refuses_private_targets_before_request() -> None:
    session = _Session([])
    fetcher = SafeArtworkFetcher(
        session=session,
        address_resolver=_address_resolver,
        peer_address=lambda response: response.peer_address,
    )

    with pytest.raises(ArtworkFetchError, match="not public"):
        fetcher.fetch("http://127.0.0.1/cover.png", cancel=threading.Event(), max_bytes=1000)

    assert session.urls == []


def test_safe_fetcher_revalidates_redirect_target() -> None:
    redirect = _Response(302, headers={"Location": "http://private.example/secret.png"})
    session = _Session([redirect])
    fetcher = SafeArtworkFetcher(
        session=session,
        address_resolver=_address_resolver,
        peer_address=lambda response: response.peer_address,
    )

    with pytest.raises(ArtworkFetchError, match="not public"):
        fetcher.fetch("https://public.example/cover.png", cancel=threading.Event(), max_bytes=1000)

    assert session.urls == ["https://public.example/cover.png"]
    assert redirect.closed is True


def test_safe_fetcher_rejects_private_connected_peer_after_public_dns_answer() -> None:
    response = _Response(200, data=_image_bytes(), peer_address="127.0.0.1")
    session = _Session([response])
    fetcher = SafeArtworkFetcher(
        session=session,
        address_resolver=_address_resolver,
        peer_address=lambda result: result.peer_address,
    )

    with pytest.raises(ArtworkFetchError, match="not public"):
        fetcher.fetch(
            "https://public.example/cover.png",
            cancel=threading.Event(),
            max_bytes=1000,
        )

    assert session.urls == ["https://public.example/cover.png"]
    assert response.closed is True


def test_safe_fetcher_enforces_an_overall_request_deadline() -> None:
    response = _Response(200, data=_image_bytes())
    session = _Session([response])
    times = iter((0.0, 0.0, 2.0))
    fetcher = SafeArtworkFetcher(
        session=session,
        address_resolver=_address_resolver,
        peer_address=lambda result: result.peer_address,
        total_timeout=1,
        monotonic=lambda: next(times),
    )

    with pytest.raises(ArtworkFetchError, match="time limit"):
        fetcher.fetch(
            "https://public.example/cover.png",
            cancel=threading.Event(),
            max_bytes=1000,
        )

    assert response.closed is True


def test_safe_fetcher_follows_a_public_redirect_and_streams_bounded_image() -> None:
    redirect = _Response(302, headers={"Location": "/final.png"})
    image = _image_bytes()
    result = _Response(
        200,
        headers={"Content-Length": str(len(image)), "Content-Type": "image/png; charset=binary"},
        data=image,
    )
    session = _Session([redirect, result])
    fetcher = SafeArtworkFetcher(
        session=session,
        address_resolver=_address_resolver,
        peer_address=lambda response: response.peer_address,
    )

    fetched = fetcher.fetch(
        "https://public.example/start.png",
        cancel=threading.Event(),
        max_bytes=len(image),
    )

    assert fetched == FetchedArtwork(image, "image/png")
    assert session.urls == [
        "https://public.example/start.png",
        "https://public.example/final.png",
    ]
    assert redirect.closed is True
    assert result.closed is True


@pytest.mark.parametrize(
    ("response", "error_type", "message"),
    [
        (_Response(302), ArtworkFetchError, "redirect"),
        (_Response(302, headers={"Location": "/next.png"}), ArtworkFetchError, "redirect"),
        (_Response(404), ArtworkFetchError, "rejected"),
        (_Response(200, headers={"Content-Length": "11"}), artwork.ArtworkValidationError, "size limit"),
        (_Response(200, headers={"Content-Length": "invalid"}), artwork.ArtworkValidationError, "invalid encoded"),
        (_Response(200, data=b"x" * 11), artwork.ArtworkValidationError, "size limit"),
    ],
)
def test_safe_fetcher_refuses_bad_responses(
    response: _Response,
    error_type: type[Exception],
    message: str,
) -> None:
    session = _Session([response])
    fetcher = SafeArtworkFetcher(
        session=session,
        max_redirects=0,
        address_resolver=_address_resolver,
        peer_address=lambda result: result.peer_address,
    )

    with pytest.raises(error_type, match=message):
        fetcher.fetch(
            "https://public.example/cover.png",
            cancel=threading.Event(),
            max_bytes=10,
        )

    assert response.closed is True


def test_safe_fetcher_handles_cancellation_and_transport_failure() -> None:
    cancelled = threading.Event()
    cancelled.set()
    session = _Session([])
    fetcher = SafeArtworkFetcher(
        session=session,
        address_resolver=_address_resolver,
        peer_address=lambda response: response.peer_address,
    )
    with pytest.raises(artwork.ArtworkCancelled):
        fetcher.fetch("https://public.example/cover.png", cancel=cancelled, max_bytes=100)
    assert session.urls == []

    class FailingSession(_Session):
        def get(self, url: str, **kwargs) -> _Response:
            del url, kwargs
            raise requests.ConnectionError("offline")

    with pytest.raises(ArtworkFetchError, match="request failed"):
        SafeArtworkFetcher(
            session=FailingSession([]),
            address_resolver=_address_resolver,
        ).fetch("https://public.example/cover.png", cancel=threading.Event(), max_bytes=100)


def test_safe_fetcher_checks_cancellation_and_deadline_while_streaming() -> None:
    cancel = threading.Event()

    class CancellingResponse(_Response):
        def iter_content(self, chunk_size: int):
            assert chunk_size > 0
            yield b""
            cancel.set()
            yield b"payload"

    response = CancellingResponse(200)
    with pytest.raises(artwork.ArtworkCancelled):
        SafeArtworkFetcher(
            session=_Session([response]),
            address_resolver=_address_resolver,
            peer_address=lambda result: result.peer_address,
        ).fetch("https://public.example/cover.png", cancel=cancel, max_bytes=100)
    assert response.closed is True

    deadline_response = _Response(200, data=b"payload")
    times = iter((0.0, 0.0, 0.0, 2.0))
    with pytest.raises(ArtworkFetchError, match="time limit"):
        SafeArtworkFetcher(
            session=_Session([deadline_response]),
            address_resolver=_address_resolver,
            peer_address=lambda result: result.peer_address,
            total_timeout=1,
            monotonic=lambda: next(times),
        ).fetch("https://public.example/cover.png", cancel=threading.Event(), max_bytes=100)
    assert deadline_response.closed is True


@pytest.mark.parametrize(
    "url",
    [
        "file:///private/cover.png",
        "https://user:secret@public.example/cover.png",
        "https://public.example:invalid/cover.png",
    ],
)
def test_safe_fetcher_rejects_invalid_or_credentialed_references(url: str) -> None:
    session = _Session([])
    fetcher = SafeArtworkFetcher(
        session=session,
        address_resolver=_address_resolver,
        peer_address=lambda response: response.peer_address,
    )
    with pytest.raises(ArtworkFetchError):
        fetcher.fetch(url, cancel=threading.Event(), max_bytes=100)
    assert session.urls == []


@pytest.mark.parametrize(
    ("resolver", "message"),
    [
        (lambda *_args, **_kwargs: (), "could not be resolved"),
        (lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("dns failed")), "could not be resolved"),
        (lambda *_args, **_kwargs: ((2, 1, 6, "", ()),), "invalid address"),
        (lambda *_args, **_kwargs: ((2, 1, 6, "", ("not-an-ip", 443)),), "invalid address"),
    ],
)
def test_safe_fetcher_rejects_unverifiable_dns_answers(resolver, message: str) -> None:
    session = _Session([])
    fetcher = SafeArtworkFetcher(
        session=session,
        address_resolver=resolver,
        peer_address=lambda response: response.peer_address,
    )
    with pytest.raises(ArtworkFetchError, match=message):
        fetcher.fetch("https://public.example/cover.png", cancel=threading.Event(), max_bytes=100)
    assert session.urls == []


def test_safe_fetcher_extracts_and_requires_connected_peer_address() -> None:
    class Sock:
        def getpeername(self):
            return ("93.184.216.34", 443)

    class Connection:
        sock = Sock()

    class Raw:
        connection = Connection()

    class Response:
        raw = Raw()

    assert SafeArtworkFetcher._response_peer_address(Response()) == "93.184.216.34"

    class MissingResponse:
        raw = object()

    with pytest.raises(ArtworkFetchError, match="could not be verified"):
        SafeArtworkFetcher._response_peer_address(MissingResponse())

    class BrokenSock:
        def getpeername(self):
            raise OSError("disconnected")

    class BrokenRaw:
        connection = type("BrokenConnection", (), {"sock": BrokenSock()})()

    class BrokenResponse:
        raw = BrokenRaw()

    with pytest.raises(ArtworkFetchError, match="could not be verified"):
        SafeArtworkFetcher._response_peer_address(BrokenResponse())


def test_safe_fetcher_closes_only_its_own_session(monkeypatch) -> None:
    owned = _Session([])
    monkeypatch.setattr(artwork.requests, "Session", lambda: owned)
    fetcher = SafeArtworkFetcher()
    fetcher.close()
    fetcher.close()
    assert owned.closed is True

    injected = _Session([])
    SafeArtworkFetcher(session=injected).close()
    assert injected.closed is False


def test_manager_close_interrupts_an_owned_fetchers_blocked_response(tmp_path: Path, monkeypatch) -> None:
    reading = threading.Event()
    released = threading.Event()

    class BlockingResponse(_Response):
        def iter_content(self, chunk_size: int):
            assert chunk_size > 0
            reading.set()
            assert released.wait(5)
            if self.closed:
                return
            yield self.data

        def close(self) -> None:
            self.closed = True
            released.set()

    response = BlockingResponse(200, data=_image_bytes())
    session = _Session([response])
    monkeypatch.setattr(artwork.requests, "Session", lambda: session)
    fetcher = SafeArtworkFetcher(
        address_resolver=_address_resolver,
        peer_address=lambda result: result.peer_address,
    )
    monkeypatch.setattr(artwork, "SafeArtworkFetcher", lambda: fetcher)
    manager = ArtworkManager(tmp_path / "cache", automatic_online=True)
    manager.activate("media", trusted_provider_url="https://public.example/cover.png")
    assert reading.wait(1)

    close_finished = threading.Event()
    close_thread = threading.Thread(target=lambda: (manager.close(), close_finished.set()))
    close_thread.start()
    try:
        assert close_finished.wait(1)
    finally:
        released.set()
        close_thread.join(5)

    assert not close_thread.is_alive()
    assert response.closed is True
    assert session.closed is True
    assert manager.projection().state == ArtworkState.UNAVAILABLE
    assert manager.current_image() is None
    manager.close()


def test_manager_closes_only_its_owned_fetcher(tmp_path: Path, monkeypatch) -> None:
    class CloseableFetcher:
        def __init__(self) -> None:
            self.closed = False

        def fetch(self, url: str, *, cancel: threading.Event, max_bytes: int) -> FetchedArtwork:
            raise AssertionError((url, cancel, max_bytes))

        def close(self) -> None:
            self.closed = True

    owned = CloseableFetcher()
    monkeypatch.setattr(artwork, "SafeArtworkFetcher", lambda: owned)
    ArtworkManager(tmp_path / "owned-cache").close()
    assert owned.closed is True

    injected = CloseableFetcher()
    ArtworkManager(tmp_path / "injected-cache", fetcher=injected).close()
    assert injected.closed is False


def test_close_cancels_worker_clears_projection_and_rejects_new_work(tmp_path: Path) -> None:
    started = threading.Event()
    observed_cancel = threading.Event()

    class BlockingFetcher:
        def fetch(self, url: str, *, cancel: threading.Event, max_bytes: int) -> FetchedArtwork:
            del url, max_bytes
            started.set()
            assert cancel.wait(2)
            observed_cancel.set()
            raise artwork.ArtworkCancelled("cancelled")

    manager = ArtworkManager(tmp_path / "cache", automatic_online=True, fetcher=BlockingFetcher())
    manager.activate("current", trusted_provider_url="https://public.example/cover.png")
    assert started.wait(1)
    manager.close()

    assert observed_cancel.is_set()
    assert manager.projection().state == ArtworkState.UNAVAILABLE
    assert manager.current_image() is None
    with pytest.raises(RuntimeError, match="closed"):
        manager.activate("later")


def test_untrusted_projection_media_identifier_is_dropped(tmp_path: Path) -> None:
    with ArtworkManager(tmp_path / "cache") as manager:
        manager.activate("internal-secret", projection_media_id="https://private.example/media")
        projection = manager.wait_for_idle()

    assert projection.media_id is None
    assert "internal-secret" not in repr(projection.to_dict())


def test_factory_degrades_to_a_private_nonfatal_service(tmp_path: Path, monkeypatch) -> None:
    updates: list[dict[str, object]] = []

    class BrokenManager:
        def __init__(self, *_args, **_kwargs) -> None:
            raise OSError("private cache location")

    monkeypatch.setattr(artwork, "ArtworkManager", BrokenManager)
    service = artwork.create_artwork_manager(
        tmp_path / "cache",
        automatic_online=True,
        on_update=updates.append,
    )

    assert isinstance(service, artwork.ArtworkUnavailableService)
    assert service.projection().state == ArtworkState.ERROR
    assert "private cache location" not in repr(service.projection().to_dict())
    revision = service.activate(
        "secret-identity",
        projection_media_id="public-media",
        local_path=tmp_path / "private.mp3",
        trusted_provider_url="https://private.example/signed",
    )
    assert revision == 1
    assert service.wait_for_idle().media_id == "public-media"
    assert service.current_image("anything") is None
    assert service.fetch_current("public-media") is None
    assert service.set_automatic_online(False) == 2
    assert service.set_automatic_online(False) is None
    assert service.clear() == 3
    assert service.projection().media_id is None
    assert service.projection().automatic_online is False
    assert all("secret-identity" not in repr(update) for update in updates)
    service.close()
    service.close()
    with pytest.raises(RuntimeError, match="closed"):
        service.clear()


def test_factory_returns_working_manager_when_initialization_succeeds(tmp_path: Path) -> None:
    service = artwork.create_artwork_manager(tmp_path / "cache")
    assert isinstance(service, ArtworkManager)
    service.close()

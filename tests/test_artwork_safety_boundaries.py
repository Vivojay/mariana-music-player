"""Safety and cancellation regressions for optional current-media artwork."""

import base64
import io
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from mariana import artwork
from tests.test_artwork import _image_bytes


@pytest.mark.parametrize('mime', ['text/html', 'image/svg+xml', 'application/octet-stream'])
def test_untrusted_mime_is_not_promoted_to_valid_image(mime):
    with pytest.raises(artwork.ArtworkValidationError, match='MIME'):
        artwork.validate_artwork_image(_image_bytes(), mime)


def test_unsupported_and_animated_images_are_not_cached():
    output = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(output, format='BMP')
    with pytest.raises(artwork.ArtworkValidationError, match='image type'):
        artwork.validate_artwork_image(output.getvalue(), None)
    output = io.BytesIO()
    first, second = Image.new('RGB', (2, 2), 'red'), Image.new('RGB', (2, 2), 'blue')
    first.save(output, format='PNG', save_all=True, append_images=[second], duration=20, loop=0)
    with pytest.raises(artwork.ArtworkValidationError, match='Animated'):
        artwork.validate_artwork_image(output.getvalue(), 'image/png')


def test_closed_fetcher_never_reopens_network():
    class Session:
        def get(self, *_args, **_kwargs):
            pytest.fail('closed artwork service must not fetch')

    fetcher = artwork.SafeArtworkFetcher(session=Session())
    fetcher.close()
    with pytest.raises(artwork.ArtworkCancelled):
        fetcher.fetch('https://public.example/image.png', cancel=threading.Event(), max_bytes=100)


@pytest.mark.parametrize('cancel_in_get', [False, True])
def test_shutdown_or_cancel_during_request_creation_closes_response(cancel_in_get):
    cancel = threading.Event()
    closed = []
    response = SimpleNamespace(close=lambda: closed.append(True))

    class Session:
        def get(self, *_args, **_kwargs):
            if cancel_in_get:
                cancel.set()
            else:
                fetcher.close()
            return response

    fetcher = artwork.SafeArtworkFetcher(
        session=Session(), address_resolver=lambda *_args, **_kwargs: [(2, 1, 6, '', ('93.184.216.34', 443))],
    )
    with pytest.raises(artwork.ArtworkCancelled):
        fetcher.fetch('https://public.example/image.png', cancel=cancel, max_bytes=100)
    assert closed == [True]


def test_expired_fetch_budget_is_rejected_before_network():
    times = iter([0.0, 100.0])
    fetcher = artwork.SafeArtworkFetcher(monotonic=lambda: next(times))
    try:
        with pytest.raises(artwork.ArtworkFetchError, match='time limit'):
            fetcher.fetch('https://public.example/private?signature=hidden', cancel=threading.Event(), max_bytes=100)
    finally:
        fetcher.close()


def test_stale_cache_is_discarded_without_using_online_permission(tmp_path):
    with artwork.ArtworkManager(tmp_path / 'cache', automatic_online=False) as manager:
        key = manager._cache_key('episode')
        path = manager.cache_dir / f'{key}.png'
        path.write_bytes(_image_bytes())
        os.utime(path, (1, 1))
        assert manager._read_cached(key, threading.Event()) is None
        assert not path.exists()


def test_cancel_during_cache_fsync_cleans_temporary_and_preserves_existing_image(tmp_path, monkeypatch):
    with artwork.ArtworkManager(tmp_path / 'cache') as manager:
        key = manager._cache_key('episode')
        destination = manager.cache_dir / f'{key}.png'
        old = _image_bytes(color='red')
        destination.write_bytes(old)
        cancel = threading.Event()
        validated = artwork.validate_artwork_image(_image_bytes(color='blue'), 'image/png')
        monkeypatch.setattr(artwork.os, 'fsync', lambda _fd: cancel.set())
        with pytest.raises(artwork.ArtworkCancelled):
            manager._store(key, validated, artwork.ArtworkOrigin.PROVIDER, cancel)
        assert destination.read_bytes() == old
        assert not list(manager.cache_dir.glob('*.tmp'))


def test_embedded_tag_variants_ignore_invalid_entries_and_keep_valid_picture(tmp_path, monkeypatch):
    picture = artwork.Picture()
    picture.data, picture.mime = _image_bytes(), 'image/png'
    encoded = base64.b64encode(picture.write())
    media = SimpleNamespace(pictures=[SimpleNamespace(data=None)], tags={
        'APIC:invalid': [SimpleNamespace(data=None)], 'covr': [None],
        'METADATA_BLOCK_PICTURE': [None, encoded],
    })
    monkeypatch.setattr(artwork, 'MutagenFile', lambda *_args, **_kwargs: media)
    with artwork.ArtworkManager(tmp_path / 'cache') as manager:
        result = list(manager._embedded_candidates(tmp_path / 'song.ogg', threading.Event()))
    assert result == [(picture.data, 'image/png')]


def test_embedded_picture_base64_budget_is_enforced_before_decoding(tmp_path, monkeypatch):
    media = SimpleNamespace(tags={'METADATA_BLOCK_PICTURE': ['a' * 100]})
    monkeypatch.setattr(artwork, 'MutagenFile', lambda *_args, **_kwargs: media)
    with artwork.ArtworkManager(tmp_path / 'cache', max_encoded_bytes=8) as manager:
        assert list(manager._embedded_candidates(tmp_path / 'song.ogg', threading.Event())) == []


def test_embedded_read_cancelled_between_tag_entries_stops_iteration(tmp_path, monkeypatch):
    cancel = threading.Event()

    class Tags:
        def items(self):
            cancel.set()
            return [('APIC', SimpleNamespace(data=_image_bytes()))]

    monkeypatch.setattr(artwork, 'MutagenFile', lambda *_args, **_kwargs: SimpleNamespace(tags=Tags()))
    with artwork.ArtworkManager(tmp_path / 'cache') as manager, pytest.raises(artwork.ArtworkCancelled):
        list(manager._embedded_candidates(tmp_path / 'song.mp3', cancel))


@pytest.mark.parametrize('mode', ['cancel', 'oversize', 'grow'])
def test_adjacent_image_read_is_bounded_across_size_check(tmp_path, monkeypatch, mode):
    path = tmp_path / 'cover.png'
    path.write_bytes(b'1234')
    cancel = threading.Event()
    with artwork.ArtworkManager(tmp_path / 'cache', max_encoded_bytes=4) as manager:
        if mode == 'cancel':
            cancel.set()
        elif mode == 'oversize':
            path.write_bytes(b'12345')
        else:
            real_open = Path.open
            monkeypatch.setattr(Path, 'open', lambda selected, *args, **kwargs: (
                io.BytesIO(b'12345') if selected == path and args == ('rb',) else real_open(selected, *args, **kwargs)
            ))
        with pytest.raises(artwork.ArtworkError):
            manager._read_bounded(path, cancel)


def test_unreadable_adjacent_folder_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'iterdir', lambda _path: (_ for _ in ()).throw(PermissionError()))
    assert list(artwork.ArtworkManager._adjacent_paths(tmp_path / 'song.mp3')) == []

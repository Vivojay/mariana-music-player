"""Cancellation and untrusted-range boundaries for the private picture cache."""

import io
import threading
from types import SimpleNamespace

import pytest

from mariana import video_cache as cache
from mariana import video_window_cache as windows
from mariana.video_sources import VideoSourceError
from tests.test_youtube_video_switching import Response, origin, track


@pytest.mark.parametrize('status', [401, 403, 410])
def test_expired_cache_metadata_is_sanitized(status):
    with pytest.raises(VideoSourceError, match='expired') as error:
        cache.VideoByteCache._descriptor(Response(b'', {}, status), 0, 0)
    assert 'signature' not in str(error.value)


def test_encoded_ranges_cannot_be_mixed_with_original_representation():
    headers = {'Content-Range': 'bytes 0-0/8', 'Content-Length': '1',
               'Content-Type': 'video/mp4', 'Content-Encoding': 'gzip'}
    with pytest.raises(VideoSourceError, match='Compressed'):
        cache.VideoByteCache._descriptor(Response(b'x', headers), 0, 0)


def test_incomplete_or_cancelled_initial_byte_never_binds_cache(monkeypatch):
    for cancelled in (False, True):
        closed = []
        cancel = threading.Event()
        if cancelled:
            cancel.set()
        response = Response(b'x' if cancelled else b'', {
            'Content-Range': 'bytes 0-0/8', 'Content-Length': '1', 'Content-Type': 'video/mp4',
        })
        def opened(*_args, closed=closed, response=response, **_kwargs):
            return SimpleNamespace(close=lambda: closed.append(True)), response

        monkeypatch.setattr(cache, '_open_response', opened)
        store = cache.VideoByteCache()
        with pytest.raises(VideoSourceError, match='incomplete or cancelled'):
            store.bind(track(), cancel)
        assert closed == [True] and store.track is None and not store.blocks


def test_cancel_during_contended_miss_does_not_wait_for_current_request(monkeypatch):
    origin(monkeypatch)
    store, cancel = cache.VideoByteCache(), threading.Event()
    store.bind(track(), cancel)
    store._miss.acquire()
    cancel.set()
    try:
        with pytest.raises(VideoSourceError, match='cancelled'):
            store.block(0, cancel)
    finally:
        store._miss.release()
    assert store.downloaded == 1 and not store.blocks


@pytest.mark.parametrize('index', [-1, 1])
def test_cache_refuses_out_of_bounds_blocks_without_new_provider_request(monkeypatch, index):
    calls, _ = origin(monkeypatch)
    store, cancel = cache.VideoByteCache(), threading.Event()
    store.bind(track(), cancel)
    with pytest.raises(VideoSourceError, match='unavailable'):
        store.block(index, cancel)
    assert calls == [(0, 0)]


def test_cache_refuses_transfer_budget_before_fetch(monkeypatch):
    calls, _ = origin(monkeypatch)
    store, cancel = cache.VideoByteCache(), threading.Event()
    store.bind(track(), cancel)
    monkeypatch.setattr(cache, 'MAX_PROXY_BYTES', 16)
    with pytest.raises(VideoSourceError, match='budget'):
        store.block(0, cancel)
    assert calls == [(0, 0)] and not store.blocks


@pytest.mark.parametrize('mode', ['source-change', 'truncated', 'cancel', 'clear'])
def test_inflight_block_failure_never_publishes_partial_or_stale_bytes(monkeypatch, mode):
    origin(monkeypatch)
    store, cancel = cache.VideoByteCache(), threading.Event()
    store.bind(track(), cancel)
    closed = []
    response = Response(b'0123456789abcdef', {
        'Content-Range': 'bytes 0-15/16', 'Content-Length': '16',
        'Content-Type': 'video/mp4', 'ETag': '"other"' if mode == 'source-change' else '"version1"',
    })
    original_read = response.read1

    def read(size):
        if mode == 'truncated':
            return b''
        if mode == 'cancel':
            cancel.set()
        if mode == 'clear':
            store.clear()
        return original_read(size)

    response.read1 = read
    monkeypatch.setattr(cache, '_open_response', lambda *_args, **_kwargs: (
        SimpleNamespace(close=lambda: closed.append(True)), response,
    ))
    with pytest.raises(VideoSourceError):
        store.block(0, cancel)
    assert not store.blocks and store.size == 0 and closed == [True]
    assert store._miss.acquire(blocking=False)
    store._miss.release()


class Handler:
    def __init__(self, token, raw=None):
        self.path = f'/{token}/media'
        self.headers = {'Range': raw} if raw is not None else {}
        self.wfile = io.BytesIO()
        self.status = None
        self.response_headers = {}
        self.close_connection = False

    def send_error(self, status):
        self.status = status

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers[name] = value

    def end_headers(self):
        pass


def proxy_without_listener(monkeypatch):
    def init(self, _track, cancel):
        self.token, self.cancel = 'opaque', cancel

    monkeypatch.setattr(cache._TrackProxy, '__init__', init)
    store = cache.VideoByteCache()
    store.track, store.total = track(), 16
    store.blocks[0], store.size = b'0123456789abcdef', 16
    return cache.CachedVideoProxy(store, threading.Event())


@pytest.mark.parametrize('raw', ['bytes=-', 'bytes=wrong', 'bytes=20-30', 'bytes=7-2'])
def test_invalid_renderer_ranges_are_rejected_before_body(monkeypatch, raw):
    proxy = proxy_without_listener(monkeypatch)
    handler = Handler(proxy.token, raw)
    proxy.handle(handler, include_body=True)
    assert handler.status == 416 and handler.wfile.getvalue() == b''


def test_head_and_full_body_preserve_safe_cache_headers(monkeypatch):
    proxy = proxy_without_listener(monkeypatch)
    head = Handler(proxy.token)
    proxy.handle(head, include_body=False)
    assert head.status == 200 and head.response_headers['Content-Length'] == '16'
    assert head.wfile.getvalue() == b'' and head.response_headers['Cache-Control'] == 'no-store'
    body = Handler(proxy.token)
    proxy.handle(body, include_body=True)
    assert body.status == 200 and body.wfile.getvalue() == b'0123456789abcdef'


def test_client_limit_and_io_failure_release_private_proxy_resources(monkeypatch):
    proxy = proxy_without_listener(monkeypatch)
    for _ in range(4):
        assert proxy._clients.acquire(blocking=False)
    handler = Handler(proxy.token)
    proxy.handle(handler, include_body=True)
    assert handler.status == 503
    for _ in range(4):
        proxy._clients.release()
    monkeypatch.setattr(proxy.cache, 'block', lambda *_args: (_ for _ in ()).throw(OSError('private detail')))
    proxy.handle(handler, include_body=True)
    assert handler.status == 502 and handler.close_connection
    assert proxy._clients.acquire(blocking=False)
    proxy._clients.release()


def test_disposable_window_lease_failure_never_exposes_writer(tmp_path, monkeypatch):
    store = windows.VideoWindowCache(tmp_path)
    monkeypatch.setattr(windows, '_lock', lambda _fd: False)
    with pytest.raises(OSError, match='lease'):
        store.allocate()
    assert store._fd is None and not list(tmp_path.glob('*.mp4'))
    store.close()


def test_manifest_storage_failures_do_not_publish_windows(tmp_path, monkeypatch):
    store = windows.VideoWindowCache(tmp_path)
    store._ensure()
    with monkeypatch.context() as patch:
        patch.setattr(windows, 'MAX_RECORD_BYTES', 1)
        with pytest.raises(OSError, match='limit'):
            store._write_record()
    with monkeypatch.context() as patch:
        patch.setattr(windows.os, 'write', lambda *_args: 0)
        with pytest.raises(OSError, match='could not be written'):
            store._write_record()
    assert not list(tmp_path.glob('*.mp4'))
    store.close()


def test_foreign_and_already_absent_windows_do_not_delete_unrelated_files(tmp_path):
    store = windows.VideoWindowCache(tmp_path)
    owned = store.allocate()
    foreign = tmp_path / 'foreign.mp4'
    foreign.write_bytes(b'keep')
    assert not store.remove(foreign)
    owned.unlink()
    assert store.remove(owned)
    store.close()
    assert foreign.read_bytes() == b'keep'

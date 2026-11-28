"""Bounded video presentation; audio and the media timeline remain backend-owned."""

from __future__ import annotations

import contextlib
import json
import math
import secrets
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from pathlib import Path

from .captions import (
    CaptionCandidate,
    CaptionError,
    CaptionPreferences,
    CaptionTrack,
    autodetect_embedded_captions,
    caption_source_signature,
    discover_caption_tracks,
    load_caption_candidate,
    load_captions,
    rank_caption_tracks,
)
from .models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from .playback import CREATE_NO_WINDOW, find_executable
from .playback_status import project_playback_status
from .provider_captions import ProviderCaptionCandidate, load_provider_caption
from .sources import ResolvedMedia
from .video_cache import CachedVideoProxy, VideoByteCache
from .video_filters import DEFAULT as DEFAULT_FILTER
from .video_filters import parse_filter
from .video_filters import projection as filter_projection
from .video_sources import VideoAccessExpired, VideoSourceError, VideoTracks, video_track_proxy
from .video_window_cache import VideoWindowCache

MAX_DURATION_SECONDS = 2 * 60 * 60
RESOLVE_TIMEOUT = 30.0
FIRST_WINDOW_SECONDS = 6.0
WINDOW_SECONDS = 20.0
WINDOW_OVERLAP_SECONDS = 2.0
WINDOW_HANDOFF_SECONDS = 0.4
CATCH_UP_TIMEOUT = 18.0
CATCH_UP_STAGE = "Preparing a lighter picture preview"
MAX_WINDOW_BYTES = 32 * 1024 * 1024
MAX_AUDIO_OFFSET_MS = 5_000
MAX_CAPTION_OFFSET_MS = 60_000
_CAPTION_WORKER_START_ERROR = (
    "Caption worker could not start; previous captions retained. Select a track or Automatic to retry"
)
_REMOTE_FORMATS = "mov,matroska,webm,avi,mpegts,mpegvideo,ogg,mp3,aac,wav,flac"
_LOCAL_FORMATS = _REMOTE_FORMATS + ",asf,flv,nut,ivf,rm"


class VideoUnavailable(ValueError):
    pass


class NoVideoTrack(VideoUnavailable):
    pass


class WindowSuperseded(Exception):
    """An authoritative seek invalidated work; reschedule without a user error."""


def default_presentation(media: MediaRef) -> str:
    """YouTube is audio-first; actual local/direct-file streams decide otherwise."""
    if media.source in {MediaSource.YOUTUBE, MediaSource.RADIO} or media.capabilities.live:
        return "audio"
    if media.source == MediaSource.LOCAL and media.resolver_data.get("has_video_track") is False:
        return "audio"
    return "auto"


def presentation_arguments(arguments: Sequence[str]) -> tuple[list[str], str | None]:
    """Remove only explicit presentation flags, preserving ordinary arguments."""
    modes = [value[2:] for value in arguments if value in {"--audio", "--video", "--auto"}]
    if len(modes) > 1:
        raise VideoUnavailable("Choose exactly one of --audio, --video or --auto")
    return [value for value in arguments if value not in {"--audio", "--video", "--auto"}], modes[0] if modes else None


def _local_source(media: MediaRef) -> Path:
    if media.source != MediaSource.LOCAL or media.capabilities.live or not media.capabilities.finite:
        raise VideoUnavailable("Video mode currently supports finite local media only")
    source = Path(media.original_uri).resolve(strict=True)
    if not source.is_file():
        raise VideoUnavailable("Local video is unavailable")
    return source


def _probe(source: Path | str, *, require_audio: bool = True, ffprobe: str | None = None) -> tuple[str, float]:
    local = isinstance(source, Path)
    try:
        result = subprocess.run(
            [ffprobe or find_executable("ffprobe"), "-v", "error", "-protocol_whitelist", "file" if local else "http,tcp",
             "-format_whitelist", _LOCAL_FORMATS if local else _REMOTE_FORMATS,
             "-show_entries", "stream=codec_type,codec_name,width,height,duration:stream_disposition=attached_pic:format=duration",
             "-of", "json", str(source)],
            capture_output=True, timeout=10, check=True, creationflags=CREATE_NO_WINDOW,
        )
        if len(result.stdout) > 64_000:
            raise ValueError("oversized probe")
        value = json.loads(result.stdout)
        streams = value.get("streams", [])
        video = next((item for item in streams if item.get("codec_type") == "video"
                      and not item.get("disposition", {}).get("attached_pic")), None)
        if not video:
            raise NoVideoTrack("This media has no video track")
        if require_audio and not any(item.get("codec_type") == "audio" for item in streams):
            raise VideoUnavailable("Silent video needs a backend video clock; it is not supported yet")
        duration = float(value.get("format", {}).get("duration") or video.get("duration") or 0)
        if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION_SECONDS:
            raise VideoUnavailable("Video must have a finite duration of at most two hours")
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        if not 0 < width <= 7680 or not 0 < height <= 4320:
            raise VideoUnavailable("Video dimensions exceed the supported preparation limit")
        return str(video["codec_name"]), duration
    except VideoUnavailable:
        raise
    except Exception:
        raise VideoUnavailable("Could not inspect video") from None


class LocalVideo:
    """One worker and one replaceable pending request, with generation-bound results."""

    def __init__(
        self, cache: Path, snapshot: Callable[[], PlaybackSnapshot],
        publish: Callable[[dict[str, object]], None],
        *, resolve_video: Callable[[MediaRef, ResolvedMedia | None], VideoTracks] | None = None,
        enabled: Callable[[], bool] = lambda: False,
        default_mode: Callable[[], str] = lambda: "auto",
        executable: Callable[[str], str] | None = None,
        youtube_cache_settings: dict[str, object] | None = None,
        caption_preferences: CaptionPreferences | None = None,
    ) -> None:
        self.cache = cache
        self.snapshot = snapshot
        self.publish = publish
        self.resolve_video = resolve_video
        self.enabled = enabled
        self.default_mode = default_mode
        self._executable = executable
        options = youtube_cache_settings or {}
        limit = options.get("memory mib", 64)
        idle = options.get("idle seconds", 600)
        self._cache_options = {
            "limit_mib": limit if type(limit) is int else 64,
            "idle_seconds": idle if type(idle) is int else 600,
        }
        self._lookup_slot = threading.BoundedSemaphore(1)
        self._youtube_cache: VideoByteCache | None = None
        self._youtube_identity: str | None = None
        self._youtube_tracks: VideoTracks | None = None
        self._youtube_resolved_at = 0.0
        self._youtube_duration: float | None = None
        self._resource: tuple[int, str] | None = None
        self._intent: tuple[MediaRef, str] | None = None
        self._resolved: ResolvedMedia | None = None
        self._observed: MediaRef | None = None
        self._condition = threading.Condition()
        self._generation = 0
        self._request: tuple[int, MediaRef, str, ResolvedMedia | None] | None = None
        self._media: MediaRef | None = None
        self._cancel = threading.Event()
        self._closed = False
        self._worker: threading.Thread | None = None
        self._owned: set[Path] = set()
        self._window_cache = VideoWindowCache(cache)
        self._captions: CaptionTrack | None = None
        self._captions_enabled = True
        self._caption_offset_ms = 0
        self._caption_discovery = "idle"
        self._caption_choice_revision = 0
        self._caption_workers: set[threading.Thread] = set()
        self.caption_preferences = caption_preferences or CaptionPreferences()
        self._caption_tracks: tuple[CaptionCandidate | ProviderCaptionCandidate, ...] = ()
        self._caption_selected: str | None = None
        self._caption_signature: str | None = None
        self._caption_source: Path | None = None
        self._caption_message: str | None = None
        self._caption_cancel = threading.Event()
        self._caption_pending: Callable[[], None] | None = None
        self._audio_offset_ms = 0
        self._filter = DEFAULT_FILTER
        self._prepare_started = 0.0
        self._picture_duration: float | None = None
        self._state: dict[str, object] = {"revision": 0, "state": "off", "handle": None, "error": None}

    def _tool(self, name: str) -> str:
        return (self._executable or find_executable)(name)

    def _inspect(self, source: Path | str, **kwargs) -> tuple[str, float]:
        if self._executable:
            kwargs["ffprobe"] = self._executable("ffprobe")
        return _probe(source, **kwargs)

    def expect(self, media: MediaRef, mode: str | None) -> None:
        """Bind an explicit presentation intent before the controller starts media."""
        with self._condition:
            self._intent = (media, mode) if mode else None

    def auto_open_local(self, media: MediaRef) -> bool:
        """Check for a confirmed local picture track in automatic presentation mode."""
        with self._condition:
            choice = self._intent[1] if self._intent and self._intent[0] is media else None
        return (media.source == MediaSource.LOCAL and media.resolver_data.get("has_video_track") is True
                and choice in {None, "auto"})

    def activate(self, media: MediaRef | None, resolved: ResolvedMedia | None) -> str | None:
        """Apply and return the presentation mode for a newly committed recording."""
        with self._condition:
            if media is not None and media is self._observed:
                self._resolved = resolved
                return
            self._observed = media
            self._resolved = resolved
            self._captions = None
            self._captions_enabled = True
            self._caption_offset_ms = 0
            self._caption_discovery = "idle"
            self._caption_choice_revision += 1
            self._caption_cancel.set()
            self._caption_pending = None
            self._caption_tracks = ()
            self._caption_selected = None
            self._caption_signature = None
            self._caption_source = None
            self._caption_message = None
            self._audio_offset_ms = 0
            # Track the committed input even when the terminal has no window.
            # An explicit open later can reuse its exact resolver binding.
            if not self.enabled():
                return
            mode = self._intent[1] if self._intent and self._intent[0] is media else self.default_mode()
        self.request(mode if media is not None else "audio", expected_media=media, _remember=False)
        self._emit()
        return mode if media is not None else None

    def request(
        self, mode: str, *, expected_media: MediaRef | None = None, _remember: bool = True,
    ) -> dict[str, object]:
        if mode not in {"audio", "video", "auto"}:
            raise VideoUnavailable("Invalid presentation mode")
        snapshot = self.snapshot()
        media = snapshot.media
        if expected_media is not None and media is not expected_media:
            raise VideoUnavailable("Current media changed; try again")
        requested_mode = mode
        if mode == "auto" and media is not None and default_presentation(media) == "audio":
            mode = "audio"
        if mode != "audio":
            if media is None or snapshot.state not in {PlaybackState.PLAYING, PlaybackState.PAUSED, PlaybackState.BUFFERING,
                                                       PlaybackState.CROSSFADING, PlaybackState.SEEKING}:
                raise VideoUnavailable("Start media before opening video")
            if media.capabilities.live or not media.capabilities.finite or media.source == MediaSource.RADIO:
                raise VideoUnavailable("Live video is not supported yet")
            if media.source == MediaSource.LOCAL:
                try:
                    _local_source(media)
                except (OSError, RuntimeError):
                    raise VideoUnavailable("Local video is unavailable") from None
            elif self.resolve_video is None:
                raise VideoUnavailable("Video mode currently supports finite local media only")
        with self._condition:
            if self._closed:
                raise VideoUnavailable("Video service is closed")
            if (media is not None and self._media is media
                    and mode == "video" and self._state["state"] in {"preparing", "ready"}):
                return self.status()
            if _remember and media is not None:
                self._intent = (media, requested_mode)
            self._generation += 1
            self._resource = None
            self._picture_duration = None
            self._cancel.set()
            self._caption_cancel.set()
            self._caption_pending = None
            if self._caption_discovery == "loading":
                self._caption_discovery = "idle"
            self._cancel = threading.Event()
            self._media = media if mode != "audio" else None
            resolved = self._resolved if media is self._observed else None
            self._request = (self._generation, media, mode, resolved) if mode != "audio" and media is not None else None
            self._prepare_started = time.monotonic()
            self._state = {
                "revision": self._generation,
                "state": "preparing" if mode != "audio" else "off", "handle": None, "error": None,
            }
            if self._request is not None and self._worker is None:
                self._worker = threading.Thread(target=self._run, name="mariana-local-video", daemon=True)
                self._worker.start()
            self._condition.notify_all()
        return self.status()

    def status(self) -> dict[str, object]:
        snapshot = self.snapshot()
        with self._condition:
            if self._media is not None and (
                snapshot.media is not self._media or snapshot.state in {PlaybackState.IDLE, PlaybackState.FAILED}
            ):
                self._cancel.set()
                self._generation += 1
                self._request = None
                self._media = None
                self._picture_duration = None
                self._state = {"revision": self._generation, "state": "off", "handle": None, "error": None}
            result = dict(self._state)
            result["media_id"] = project_playback_status(snapshot).media_id if self._media is not None else None
            visual_position = self._video_position(snapshot.position)
            if self._picture_duration is not None:
                visual_position = min(self._picture_duration, visual_position)
            result["position_seconds"] = visual_position
            result["playing"] = snapshot.state in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}
            result["audio_offset_ms"] = self._audio_offset_ms
            result["filter"] = filter_projection(self._filter)
            result["playback_rate"] = getattr(snapshot, "playback_rate", 1.0)
            caption_position = max(0.0, visual_position - self._caption_offset_ms / 1000)
            result["captions"] = {
                "available": self._captions is not None,
                "enabled": self._captions_enabled,
                "label": self._captions.label if self._captions is not None else None,
                "source": self._captions.source if self._captions is not None else None,
                "auto_status": self._caption_discovery,
                "offset_ms": self._caption_offset_ms,
                "text": self._captions.cue_at(caption_position)
                if self._captions is not None and self._captions_enabled else None,
                "revision": self._caption_choice_revision,
                "tracks": [track.projection() for track in self._caption_tracks],
                "selected_id": self._caption_selected,
                "preferred_languages": list(self.caption_preferences.languages),
                "message": self._caption_message,
            }
            start = result.get("window_start_seconds")
            end = result.get("window_end_seconds")
            if (result["state"] == "ready" and isinstance(start, (int, float)) and isinstance(end, (int, float))
                    and not start <= visual_position <= end):
                # Never present a stale picture while a seek window is being prepared.
                result.update(state="preparing", handle=None, elapsed_seconds=0,
                              stage="Preparing a picture at the current position")
            if result["state"] == "preparing":
                result.setdefault("elapsed_seconds", int(max(0, time.monotonic() - self._prepare_started)))
            return result

    def host_status(self) -> dict[str, object]:
        """Private desktop-host envelope. Its capability is stripped before renderer projection."""
        with self._condition:
            result = self.status()
            if result["state"] == "ready" and self._resource and self._resource[0] == self._generation:
                result["resource"] = self._resource[1]
            return result

    def cache_status(self, *, clear: bool = False) -> dict[str, int]:
        # Cache mutation is a short memory-only operation, never a network wait.
        with self._condition:
            cache = self._youtube_cache
            if clear and cache is not None:
                cache.clear()
            return cache.statistics() if cache else {
                "cached_bytes": 0, "downloaded_bytes": 0, "reused_bytes": 0,
                "limit_bytes": max(16, min(256, self._cache_options["limit_mib"])) * 1024 * 1024,
                "idle_seconds": max(30, min(1800, self._cache_options["idle_seconds"])),
            }

    def _expire_youtube_cache(self) -> None:
        with self._condition:
            active = self.snapshot().media
            if self._youtube_cache and (self._youtube_cache.expired()
                    or active is None or active.stable_id != self._youtube_identity):
                self._youtube_cache.clear()
                self._youtube_cache = None
                self._youtube_tracks = None
                self._youtube_duration = None
                self._youtube_identity = None

    def _preparing(self, generation: int, stage: str) -> None:
        with self._condition:
            if generation == self._generation and self._state["state"] == "preparing":
                self._state["stage"] = stage

    def _resolve_picture(self, media: MediaRef, resolved: ResolvedMedia | None,
                         cancel: threading.Event) -> VideoTracks:
        """Network libraries may block on DNS or browser keyrings beyond socket timeouts."""
        assert self.resolve_video is not None
        resolver = self.resolve_video
        deadline = time.monotonic() + RESOLVE_TIMEOUT
        pending: Future[VideoTracks] = Future()

        def check() -> None:
            if cancel.is_set():
                raise VideoUnavailable("Video lookup was cancelled")
            if time.monotonic() >= deadline:
                raise VideoUnavailable("Video lookup timed out. Check the network and youtube auth status, "
                                       "then use video open to retry.")

        def lookup() -> None:
            try:
                pending.set_result(resolver(media, resolved))
            except Exception as error:
                pending.set_exception(error)
            finally:
                self._lookup_slot.release()

        # Only one provider lookup can outlive its presentation. Its result is
        # private to this request, so a late completion cannot restore stale video.
        while not self._lookup_slot.acquire(timeout=.05):
            check()
        try:
            check()
            threading.Thread(target=lookup, name="mariana-video-lookup", daemon=True).start()
        except BaseException:
            self._lookup_slot.release()
            raise
        while not pending.done():
            check()
            cancel.wait(.025)
        check()
        return pending.result()

    def _youtube_source(self, media: MediaRef, resolved: ResolvedMedia | None,
                        generation: int, cancel: threading.Event, *, refresh: bool = True) -> None:
        """Serve original picture bytes; never restart, seek, or decode authoritative audio."""
        assert self.resolve_video is not None
        self._expire_youtube_cache()
        tracks = self._youtube_tracks
        fresh = (tracks is not None and self._youtube_identity == media.stable_id
                 and time.monotonic() - self._youtube_resolved_at < 120
                 and (tracks.expires_at is None or time.time() + 30 < tracks.expires_at))
        if not fresh:
            self._preparing(generation, "Resolving the video format")
            tracks = self._resolve_picture(media, resolved, cancel)
        assert tracks is not None
        if tracks.duration is not None and (not math.isfinite(tracks.duration)
                                           or not 0 < tracks.duration <= MAX_DURATION_SECONDS):
            raise VideoUnavailable("Video must have a finite duration of at most two hours")
        track = tracks.video
        if (track.container not in {"mp4", "webm"} or not track.codec
                or not track.codec.startswith(("avc1", "h264", "av01", "av1", "vp9", "vp09"))):
            raise VideoUnavailable("No source-quality video format is supported; audio is unchanged")
        if cancel.is_set():
            return
        self._publish_provider_captions(tracks, media, generation, cancel)
        cache = self._youtube_cache
        if cache is None:
            cache = VideoByteCache(limit_mib=self._cache_options["limit_mib"],
                                   idle_seconds=self._cache_options["idle_seconds"])
        if not fresh or cache.track is None:
            self._preparing(generation, "Checking provider byte ranges")
            try:
                cache.bind(track, cancel)
            except VideoAccessExpired:
                if not refresh or not tracks.from_audio_selection or cancel.is_set():
                    raise
                # Audio hints are single-use. Ordinary resolution now selects a
                # fresh signed URL for the same recording and account.
                return self._youtube_source(media, resolved, generation, cancel, refresh=False)
        if cancel.is_set():
            return
        def transport_error(message: str) -> None:
            with self._condition:
                if generation != self._generation or cancel.is_set():
                    return
                self._youtube_tracks = None
                self._resource = None
                self._state = {"revision": generation, "state": "error", "handle": None, "error": message}
                cancel.set()
            self._emit()

        proxy = CachedVideoProxy(cache, cancel, transport_error)
        proxy.start()
        try:
            duration = self._youtube_duration if fresh else None
            if duration is None:
                self._preparing(generation, "Reading the video index")
                _codec, duration = self._inspect(proxy.url, require_audio=False)
            if media.duration is not None and abs(duration - media.duration) > max(2.0, media.duration * 0.005):
                raise VideoUnavailable("Video duration differs from the active recording; audio playback is unchanged")
            with self._condition:
                if cancel.is_set() or generation != self._generation or self.snapshot().media is not media:
                    return
                self._youtube_cache, self._youtube_tracks = cache, tracks
                self._youtube_identity, self._youtube_duration = media.stable_id, duration
                if not fresh:
                    self._youtube_resolved_at = time.monotonic()
                self._resource = (generation, proxy.url)
                self._state = {
                    "revision": generation, "state": "ready", "handle": secrets.token_hex(16),
                    "error": None, "transport": "source",
                }
            self._emit()
            while not cancel.wait(0.1):
                snapshot = self.snapshot()
                if snapshot.media is not media or snapshot.state in {PlaybackState.IDLE, PlaybackState.FAILED}:
                    break
                if cache.expired():
                    cache.clear()
                    cache.last_used = cache.clock()
        finally:
            cancel.set()
            proxy.close()

    def _video_position(self, audio_position: float) -> float:
        """Map backend audio time to picture time; positive offset means audio is later."""
        return max(0.0, audio_position + self._audio_offset_ms / 1000)

    def _require_current(self, expected_media: MediaRef | None = None) -> MediaRef:
        snapshot = self.snapshot()
        if snapshot.media is None or snapshot.state in {PlaybackState.IDLE, PlaybackState.FAILED}:
            raise VideoUnavailable("Start media before configuring video")
        if expected_media is not None and snapshot.media is not expected_media:
            raise VideoUnavailable("Current media changed; try again")
        return snapshot.media

    def load_captions(
        self, path: str | Path, *, replace: bool = False, expected_media: MediaRef | None = None,
    ) -> dict[str, object]:
        media = self._require_current(expected_media)
        track = load_captions(path)
        with self._condition:
            if self.snapshot().media is not media:
                raise VideoUnavailable("Current media changed; try again")
            if self._captions is not None and not replace:
                raise CaptionError("Captions are already loaded; use captions replace")
            self._captions = track
            self._captions_enabled = True
            self._caption_offset_ms = 0
            self._caption_discovery = "manual"
            self._caption_choice_revision += 1
            self._caption_cancel.set()
            self._caption_pending = None
            self._caption_selected = None
            self._caption_message = None
        self._emit()
        return self.status()

    def configure_captions(
        self, action: str, value: int | None = None, *, expected_media: MediaRef | None = None,
    ) -> dict[str, object]:
        media = self._require_current(expected_media)
        with self._condition:
            self._require_current(media)
            if self._caption_discovery == "loading" and action != "clear":
                raise CaptionError("Caption selection is still loading; try again when ready")
            enabled, offset = self._captions_enabled, self._caption_offset_ms
            if action in {"on", "off"}:
                if self._captions is None:
                    raise CaptionError("No captions are loaded")
                enabled = action == "on"
            elif action == "clear":
                self._captions = None
                enabled, offset = True, 0
                self._caption_discovery = "cleared"
                self._caption_choice_revision += 1
                self._caption_cancel.set()
                self._caption_pending = None
                self._caption_selected = None
            elif action in {"set-offset", "shift"}:
                if self._captions is None:
                    raise CaptionError("No captions are loaded")
                if type(value) is not int:
                    raise CaptionError("Caption offset must be a whole number of milliseconds")
                next_value = value if action == "set-offset" else self._caption_offset_ms + value
                if not -MAX_CAPTION_OFFSET_MS <= next_value <= MAX_CAPTION_OFFSET_MS:
                    raise CaptionError("Caption offset must stay between -60000 and 60000 milliseconds")
                offset = next_value
            else:
                raise CaptionError("Invalid caption action")
            if self._caption_selected and self._caption_signature:
                self.caption_preferences.remember(media.stable_id, self._caption_signature, self._caption_selected,
                                                  enabled, offset)
            self._captions_enabled, self._caption_offset_ms = enabled, offset
        self._emit()
        return self.status()

    def _queue_caption_work(self, work: Callable[[threading.Event, int], None]) -> bool:
        """One worker and one latest pending job; rapid choices cannot grow a queue."""
        self._caption_cancel.set()
        cancel = self._caption_cancel = threading.Event()
        self._caption_choice_revision += 1
        revision = self._caption_choice_revision
        self._caption_discovery = "loading"
        self._caption_message = None
        self._caption_pending = lambda: work(cancel, revision)
        if not self._caption_workers:
            try:
                worker = threading.Thread(target=self._caption_loop, name="mariana-caption-selection", daemon=True)
                # The condition is held, so a started worker cannot consume its
                # pending job until it has been registered successfully.
                worker.start()
            except RuntimeError:
                cancel.set()
                self._caption_pending = None
                self._caption_discovery = "error"
                self._caption_message = _CAPTION_WORKER_START_ERROR
                return False
            self._caption_workers.add(worker)
        self._condition.notify_all()
        return True

    def _caption_loop(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._caption_pending is not None)
                if self._closed:
                    return
                work, self._caption_pending = self._caption_pending, None
                revision = self._caption_choice_revision
            try:
                assert work is not None
                work()
            except Exception:
                with self._condition:
                    if not self._closed and not self._caption_cancel.is_set() and revision == self._caption_choice_revision:
                        self._caption_discovery = "error"
                        self._caption_message = "Caption operation failed; playback is unchanged"
                self._emit()

    def _caption_current(self, media: MediaRef, generation: int, cancel: threading.Event, revision: int) -> bool:
        return (not self._closed and not cancel.is_set() and generation == self._generation
                and self._media is media and self.snapshot().media is media
                and revision == self._caption_choice_revision)

    def select_caption(self, track_id: str, revision: int, *, expected_media: MediaRef | None = None) -> dict[str, object]:
        media = self._require_current(expected_media)
        with self._condition:
            self._require_current(media)
            if type(revision) is not int or revision != self._caption_choice_revision:
                raise CaptionError("Caption list changed; choose again")
            candidate = next((track for track in self._caption_tracks if track.key == track_id), None)
            if candidate is None or (isinstance(candidate, CaptionCandidate) and self._caption_signature is None):
                raise CaptionError("Caption track is unavailable; choose a listed track")
            if isinstance(candidate, ProviderCaptionCandidate) and (self._media is not media or self._cancel.is_set()):
                raise CaptionError("Open the current video before fetching provider captions")
            generation = self._generation
            signature = self._caption_signature
            source = self._caption_source

            def select(cancel: threading.Event, choice_revision: int) -> None:
                if isinstance(candidate, ProviderCaptionCandidate):
                    try:
                        track = load_provider_caption(candidate, cancel)
                    except CaptionError:
                        track = None
                else:
                    track = load_caption_candidate(candidate, self.cache, self._tool("ffmpeg"), cancel)
                    if source is None or caption_source_signature(source) != signature:
                        track = None
                with self._condition:
                    if not self._caption_current(media, generation, cancel, choice_revision):
                        return
                    if track is None:
                        self._caption_discovery = "error"
                        if isinstance(candidate, ProviderCaptionCandidate):
                            self._youtube_tracks = None
                            self._caption_message = (
                                "Provider captions unavailable; choose Audio only, then Video, and select again. "
                                "Previous captions retained"
                            )
                        else:
                            self._caption_message = "Selected caption track is unavailable; previous captions retained"
                    else:
                        if isinstance(candidate, CaptionCandidate) and signature is not None:
                            self.caption_preferences.remember(media.stable_id, signature, candidate.key, True, 0)
                        self._captions, self._caption_selected = track, candidate.key
                        self._captions_enabled, self._caption_offset_ms = True, 0
                        self._caption_discovery = "loaded"
                self._emit()

            queued = self._queue_caption_work(select)
        self._emit()
        if not queued:
            raise CaptionError(_CAPTION_WORKER_START_ERROR)
        return self.status()

    def caption_automatic(self, *, expected_media: MediaRef | None = None) -> dict[str, object]:
        media = self._require_current(expected_media)
        with self._condition:
            self._require_current(media)
            source = self._caption_source
            if source is None:
                raise CaptionError("Open a local video before choosing automatic captions")
            self.caption_preferences.forget(media.stable_id)
            self._caption_discovery = "idle"
            if self._start_caption_discovery(source, media, self._generation, self._cancel, sidecars=True):
                self._captions = None
                self._caption_selected = None
                self._captions_enabled, self._caption_offset_ms = True, 0
        self._emit()
        return self.status()

    def set_caption_languages(self, languages: list[str]) -> dict[str, object]:
        self.caption_preferences.set_languages(languages)
        with self._condition:
            media = self._media
            source = self._caption_source
            if (media and source and not self.caption_preferences.get(media.stable_id)
                    and self._caption_discovery != "manual"):
                self._caption_discovery = "idle"
                self._start_caption_discovery(source, media, self._generation, self._cancel, sidecars=True)
        self._emit()
        return self.status()

    def configure_audio_offset(
        self, value: int, *, relative: bool = False, expected_media: MediaRef | None = None,
    ) -> dict[str, object]:
        media = self._require_current(expected_media)
        if type(value) is not int:
            raise VideoUnavailable("Audio offset must be a whole number of milliseconds")
        with self._condition:
            self._require_current(media)
            next_value = self._audio_offset_ms + value if relative else value
            if not -MAX_AUDIO_OFFSET_MS <= next_value <= MAX_AUDIO_OFFSET_MS:
                raise VideoUnavailable("Audio offset must stay between -5000 and 5000 milliseconds")
            self._audio_offset_ms = next_value
            self._condition.notify_all()
        self._emit()
        return self.status()

    def configure_filter(
        self, preset: str, threshold: int | str | None = None, *, expected_media: MediaRef | None = None,
    ) -> dict[str, object]:
        try:
            selection = parse_filter(preset, threshold)
        except ValueError as error:
            raise VideoUnavailable(str(error)) from None
        with self._condition:
            if expected_media is not None and self.snapshot().media is not expected_media:
                raise VideoUnavailable("Current media changed; try again")
            self._filter = selection
        self._emit()
        return self.status()

    def _encode_window(
        self, source: Path | str, output: Path, start: float, length: float,
        cancel: threading.Event, still_needed: Callable[[], bool], *, lighter: bool = False,
    ) -> None:
        """Accurate input seek and a short, zero-based silent picture window."""
        width, height, fps = (640, 360, 18) if lighter else (1280, 720, 30)
        filters = (
            f"setpts=PTS-STARTPTS,scale='min(iw,{width})':'min(ih,{height})':"
            f"force_original_aspect_ratio=decrease:force_divisible_by=2,fps={fps}"
        )
        command = [
            self._tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-protocol_whitelist", "file" if isinstance(source, Path) else "http,tcp",
            "-format_whitelist", _LOCAL_FORMATS if isinstance(source, Path) else _REMOTE_FORMATS,
            "-ss", str(start), "-threads", "2", "-i", str(source),
            "-map", "0:V:0", "-an", "-sn", "-dn", "-map_metadata", "-1",
            "-vf", filters,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-tune", "zerolatency",
            "-crf", "24", "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-threads", "2", "-t", str(length), "-fs", str(MAX_WINDOW_BYTES),
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", "pipe:1",
        ]
        # FFmpeg receives an already-owned output descriptor, not a pathname it
        # could reopen after replacement. Fragmented MP4 supports pipe output.
        with self._window_cache.writer(output) as destination:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=destination,
                                       stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        deadline = time.monotonic() + 30
        try:
            while process.poll() is None:
                if cancel.wait(0.05) or not still_needed():
                    raise WindowSuperseded()
                if time.monotonic() > deadline:
                    raise VideoUnavailable("A short video window could not be prepared in time; audio is unchanged")
            if process.returncode != 0:
                raise VideoUnavailable("The video window could not be decoded; audio is unchanged")
            self._window_cache.validate(output)
            if not 0 < output.stat().st_size < MAX_WINDOW_BYTES:
                raise VideoUnavailable("Video window exceeds its 32 MiB cache limit")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def _windows(
        self,
        source: Path | str,
        media: MediaRef,
        duration: float,
        generation: int,
        cancel: threading.Event,
        unchanged: Callable[[], bool],
    ) -> None:
        """Keep only current/next windows, prefetching independently of the audio clock."""
        current: tuple[Path, float, float] | None = None
        following: tuple[Path, float, float] | None = None
        lighter = False
        catch_up_deadline: float | None = None
        with self._condition:
            if generation != self._generation:
                return
            self._picture_duration = duration

        def position(snapshot: PlaybackSnapshot) -> float:
            return min(duration, self._video_position(snapshot.position))

        def valid(snapshot: PlaybackSnapshot) -> bool:
            return (not cancel.is_set() and snapshot.media is media
                    and snapshot.state not in {PlaybackState.IDLE, PlaybackState.FAILED})

        def contains(window: tuple[Path, float, float] | None, point: float) -> bool:
            return window is not None and window[1] <= point <= window[2]

        def prepare(start: float, length: float, existing: tuple[Path, float, float] | None):
            output = self._window_cache.allocate()
            self._owned.add(output)
            end = min(duration, start + length)

            def still_needed() -> bool:
                snapshot = self.snapshot()
                if not valid(snapshot):
                    return False
                point = position(snapshot)
                needed = start <= point <= end or contains(existing, point)
                if needed and catch_up_deadline is not None and time.monotonic() >= catch_up_deadline:
                    raise VideoUnavailable("Picture could not catch up in time; audio is unchanged")
                return needed

            try:
                self._encode_window(source, output, start, end - start, cancel, still_needed, lighter=lighter)
                self._window_cache.validate(output)
                if not unchanged():
                    raise VideoUnavailable("Local media changed during video preparation")
                if not still_needed():
                    raise WindowSuperseded()
                return output, start, end
            except BaseException:
                self._remove(output)
                raise

        try:
            while valid(snapshot := self.snapshot()):
                point = position(snapshot)
                advancing = snapshot.state in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}
                near_end = current is not None and advancing and point >= current[2] - WINDOW_HANDOFF_SECONDS
                if following is not None and contains(following, point) and (near_end or not contains(current, point)):
                    current, following = following, None
                elif not contains(current, point):
                    current, following = None, None
                    started = time.monotonic()
                    with self._condition:
                        if generation != self._generation or not valid(self.snapshot()):
                            return
                        announce = self._state["state"] == "ready"
                        if announce:
                            self._prepare_started = started
                            self._state = {
                                "revision": generation, "state": "preparing", "handle": None, "error": None,
                                "stage": CATCH_UP_STAGE if lighter else "Preparing a picture at the current position",
                            }
                    if announce:
                        self._emit()
                    self._cleanup()
                    if catch_up_deadline is None:
                        catch_up_deadline = started + CATCH_UP_TIMEOUT
                    elif started >= catch_up_deadline:
                        raise VideoUnavailable("Picture could not catch up in time; audio is unchanged")
                    start = max(0.0, min(point - 1.0, duration - 1.0))
                    try:
                        current = prepare(start, FIRST_WINDOW_SECONDS, None)
                    except WindowSuperseded:
                        latest = self.snapshot()
                        if not valid(latest):
                            return
                        latest_point = position(latest)
                        # Compare against elapsed wall time and the maximum playback rate.
                        # Large/reverse jumps are new seek targets. A normal clock must
                        # not restart the deadline on every missed window.
                        if (advancing and latest.state in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}
                                and latest_point > start + FIRST_WINDOW_SECONDS
                                and latest_point <= point + 2 * (time.monotonic() - started) + 1):
                            if not lighter:
                                lighter = True
                                self._preparing(generation, CATCH_UP_STAGE)
                                self._emit()
                        else:
                            catch_up_deadline = None
                        continue
                    catch_up_deadline = None
                assert current is not None
                with self._condition:
                    if generation != self._generation or not valid(self.snapshot()):
                        return
                    changed = self._state.get("handle") != current[0].stem
                    self._state = {
                        "revision": generation, "state": "ready", "handle": current[0].stem, "error": None,
                        "window_start_seconds": current[1], "window_end_seconds": current[2],
                    }
                if changed:
                    self._emit()
                keep = {current[0]} | ({following[0]} if following else set())
                for path in tuple(self._owned - keep):
                    self._remove(path)
                if len(self._owned) > 6:
                    raise VideoUnavailable("Video cache files remain in use; reopen video to retry")
                if following is None and current[2] < duration:
                    try:
                        following = prepare(max(current[1], current[2] - WINDOW_OVERLAP_SECONDS), WINDOW_SECONDS, current)
                    except WindowSuperseded:
                        continue
                cancel.wait(0.05)
        finally:
            self._cleanup()

    def _local_windows(
        self, source: Path, media: MediaRef, duration: float, generation: int, cancel: threading.Event,
    ) -> None:
        original = source.stat()
        identity = (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns)

        def unchanged() -> bool:
            try:
                current = source.stat()
            except OSError:
                return False
            return (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) == identity

        self._windows(source, media, duration, generation, cancel, unchanged)

    def _publish_provider_captions(
        self, tracks: VideoTracks, media: MediaRef, generation: int, cancel: threading.Event,
    ) -> None:
        """Expose safe alternatives from existing resolution; never fetch by default."""
        with self._condition:
            if (self._closed or cancel.is_set() or generation != self._generation
                    or self._media is not media or self.snapshot().media is not media):
                return
            if self._caption_tracks == tracks.captions and self._caption_discovery != "idle":
                return
            self._caption_cancel.set()
            self._caption_pending = None
            self._caption_choice_revision += 1
            self._caption_tracks = tracks.captions
            self._caption_source = None
            self._caption_signature = None
            self._caption_selected = None
            if self._caption_discovery not in {"manual", "cleared"}:
                self._captions = None
                self._captions_enabled, self._caption_offset_ms = True, 0
                self._caption_discovery = "none"
            self._caption_message = (
                "Choose a provider track to fetch captions for this session"
                if tracks.captions else "No supported provider caption tracks were supplied"
            )
        self._emit()

    def _start_caption_discovery(
        self, source: Path | str, media: MediaRef, generation: int, cancel: threading.Event,
        *, sidecars: bool,
    ) -> bool:
        """Catalogue local alternatives; decode only the chosen/default text track."""
        with self._condition:
            if self._closed or generation != self._generation or self._caption_discovery != "idle":
                return False
            if sidecars:
                self._caption_source = Path(source)

            def discover(caption_cancel: threading.Event, choice_revision: int) -> None:
                tracks: tuple[CaptionCandidate, ...] = ()
                selected = None
                signature = None
                saved = self.caption_preferences.get(media.stable_id) if sidecars else None
                message = None
                if sidecars:
                    local = Path(source)
                    signature = caption_source_signature(local)
                    tracks = discover_caption_tracks(local, self._tool("ffprobe"), caption_cancel)
                    ranked = rank_caption_tracks(tracks, self.caption_preferences.languages)
                    if saved:
                        ranked = tuple(item for item in tracks if item.key == saved["track"]) \
                            if saved["signature"] == signature else ()
                        if not ranked:
                            message = "Saved caption choice is unavailable; choose a track or Automatic"
                    track = None
                    for candidate in ranked:
                        track = load_caption_candidate(candidate, self.cache, self._tool("ffmpeg"), caption_cancel)
                        if track is not None:
                            selected = candidate.key
                            break
                    if saved and track is None:
                        message = "Saved caption choice is unavailable; choose a track or Automatic"
                    if caption_source_signature(local) != signature:
                        raise CaptionError("Media changed during caption discovery")
                else:
                    track = autodetect_embedded_captions(
                        source, self.cache, ffprobe_bin=self._tool("ffprobe"),
                        ffmpeg_bin=self._tool("ffmpeg"), cancel=caption_cancel,
                    )
                with self._condition:
                    if cancel.is_set() or not self._caption_current(media, generation, caption_cancel, choice_revision):
                        return
                    self._caption_tracks = tracks
                    self._caption_selected, self._caption_signature = selected, signature
                    self._captions = track
                    self._captions_enabled = saved["enabled"] if saved else True
                    self._caption_offset_ms = saved["offset_ms"] if saved else 0
                    self._caption_message = message
                    self._caption_discovery = "loaded" if track is not None else "none"
                self._emit()
            queued = self._queue_caption_work(discover)
        self._emit()
        return queued

    def _run(self) -> None:
        try:
            self._run_requests()
        finally:
            self._cleanup()
            self._window_cache.close()

    def _run_requests(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._request is not None, timeout=5)
                if self._closed:
                    return
                if self._request is None:
                    self._expire_youtube_cache()
                    continue
                request, self._request = self._request, None
                cancel = self._cancel
            assert request is not None
            generation, media, mode, resolved = request
            try:
                self._cleanup()
                if media.source == MediaSource.YOUTUBE:
                    self._youtube_source(media, resolved, generation, cancel)
                elif media.source == MediaSource.LOCAL:
                    source = _local_source(media)
                    self._preparing(generation, "Reading the video index")
                    _codec, duration = self._inspect(source, require_audio=False)
                    if cancel.is_set():
                        continue
                    self._start_caption_discovery(source, media, generation, cancel, sidecars=True)
                    self._preparing(generation, "Preparing the first picture")
                    self._local_windows(source, media, duration, generation, cancel)
                else:
                    if self.resolve_video is None:
                        raise VideoUnavailable("Online video is unavailable")
                    tracks = self.resolve_video(media, resolved)
                    if cancel.is_set():
                        continue
                    if tracks.duration is not None and not 0 < tracks.duration <= MAX_DURATION_SECONDS:
                        raise VideoUnavailable("Video must have a finite duration of at most two hours")
                    if tracks.captions:
                        self._publish_provider_captions(tracks, media, generation, cancel)
                    with video_track_proxy(tracks.video, cancel) as source:
                        _codec, duration = self._inspect(source, require_audio=False)
                        if media.duration is not None and (
                            abs(duration - media.duration) > max(2.0, media.duration * 0.005)
                        ):
                            raise VideoUnavailable(
                                "Video duration differs from the active recording; audio playback is unchanged"
                            )
                        if cancel.is_set():
                            continue
                        if not tracks.captions:
                            self._start_caption_discovery(source, media, generation, cancel, sidecars=False)
                        self._windows(source, media, duration, generation, cancel, lambda: True)
            except NoVideoTrack as error:
                with self._condition:
                    if generation == self._generation and not cancel.is_set():
                        self._state = {
                            "revision": generation, "state": "off" if mode == "auto" else "error",
                            "handle": None, "error": None if mode == "auto" else str(error),
                        }
                self._emit()
            except Exception as error:
                with self._condition:
                    if generation == self._generation and not cancel.is_set():
                        if media.source == MediaSource.YOUTUBE:
                            self._youtube_tracks = None
                        self._state = {
                            "revision": generation, "state": "error", "handle": None,
                            "error": str(error) if isinstance(error, (VideoUnavailable, VideoSourceError)) else "Video is unavailable",
                        }
                self._emit()
    def _emit(self) -> None:
        with contextlib.suppress(Exception):
            self.publish(self.host_status())

    def _remove(self, path: Path) -> None:
        with contextlib.suppress(OSError):
            if self._window_cache.remove(path):
                self._owned.discard(path)

    def _cleanup(self) -> None:
        for path in tuple(self._owned):
            self._remove(path)

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._cancel.set()
            self._caption_cancel.set()
            self._caption_pending = None
            self._generation += 1
            self._media = None
            self._request = None
            self._picture_duration = None
            self._state = {"revision": self._generation, "state": "off", "handle": None, "error": None}
            self._condition.notify_all()
        if self._worker is not None and self._worker is not threading.current_thread():
            self._worker.join(timeout=15)
        deadline = time.monotonic() + 15
        for worker in tuple(self._caption_workers):
            if worker is not threading.current_thread():
                worker.join(timeout=max(0.0, deadline - time.monotonic()))
        # A worker exceeding the join budget retains its lease until it exits;
        # shutdown must not delete an output still being produced.
        if self._worker is None or not self._worker.is_alive():
            self._cleanup()
            self._window_cache.close()
        if self._youtube_cache:
            self._youtube_cache.clear()
            self._youtube_cache = None
        self._youtube_tracks = None
        self._resource = None

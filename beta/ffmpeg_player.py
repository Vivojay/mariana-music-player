"""Compatibility facade over Mariana's FFmpeg playback controller."""

from __future__ import annotations

from pathlib import Path
import time

from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackState
from mariana.playback import PlaybackController, PlaybackError, UnsupportedAction
from mariana.sources import ResolverRegistry
from mariana.supervisor import PlaybackSupervisor


controller = PlaybackController()
supervisor = PlaybackSupervisor(controller)
current_media: MediaRef | None = None
radio_catalog = None
RADIO_STREAMS: dict[str, str] = {
    "coffee": "https://somafm.com/m3u/groovesalad.m3u",
    "chillout": "https://somafm.com/m3u/groovesalad.m3u",
    "lounge": "https://somafm.com/m3u/illstreet.m3u",
    "antenne": "https://stream.antenne.de/antenne/stream/mp3",
}


def configure(
    *,
    ffmpeg_bin=None,
    ffprobe_bin=None,
    crossfade_seconds=0,
    catalog=None,
    browser_profile=None,
    replaygain=None,
    live_leveling=None,
):
    global controller, supervisor, radio_catalog
    supervisor.close()
    radio_catalog = catalog
    def radio_endpoints(media):
        endpoints = list(media.resolver_data.get("endpoints") or [])
        station_id = media.resolver_data.get("station_id")
        if not endpoints and radio_catalog is not None and station_id:
            try:
                endpoints = radio_catalog.endpoints(radio_catalog.get(station_id))
            except Exception:
                endpoints = []
        return endpoints or [media.original_uri]

    resolvers = ResolverRegistry(browser_profile=browser_profile, radio_endpoints=radio_endpoints)
    replaygain = replaygain or {}
    live_leveling = live_leveling or {}
    controller = PlaybackController(
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin or ffmpeg_bin,
        crossfade_seconds=crossfade_seconds,
        resolvers=resolvers,
        replaygain_enabled=replaygain.get("enabled", False),
        replaygain_mode=replaygain.get("mode", "track"),
        replaygain_preamp_db=replaygain.get("preamp db", 0),
        replaygain_prevent_clipping=replaygain.get("prevent clipping", True),
        replaygain_headroom_dbtp=replaygain.get("headroom dbtp", -1),
        live_leveling=live_leveling.get("enabled", False),
        live_target_lufs=live_leveling.get("target lufs", -18),
        live_true_peak_dbtp=live_leveling.get("true peak dbtp", -1),
        live_lra=live_leveling.get("lra", 11),
    )
    supervisor = PlaybackSupervisor(controller, resolvers=resolvers)


class PlayerAdapter:
    def get_length(self) -> int:
        duration = controller.snapshot().duration
        return int(duration * 1000) if duration is not None else 0

    def get_time(self) -> int:
        return int(controller.snapshot().position * 1000)

    def set_time(self, value: int) -> None:
        controller.seek(value / 1000)

    def audio_set_volume(self, value: float) -> None:
        controller.set_volume(value)

    def audio_set_mute(self, value: int | bool) -> None:
        controller.set_muted(bool(value))

    def is_playing(self) -> bool:
        return controller.snapshot().state in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}


player = PlayerAdapter()


def radio_stream_url(name: str) -> str:
    try:
        return RADIO_STREAMS[name]
    except KeyError as error:
        raise ValueError(f"Unknown radio station: {name}") from error


def set_media(_type=None, vidurl=None, audurl=None, localpath=None):
    global current_media
    if _type and _type.startswith("radio"):
        station = _type.split("/", 1)[1]
        radio_url = None
        station_title = station
        if radio_catalog is not None:
            aliases = {
                "coffee": "groove-salad",
                "chillout": "groove-salad",
                "lounge": "secret-agent",
                "antenne": "antenne-bayern",
            }
            catalog_station = radio_catalog.get(aliases.get(station, station))
            radio_url = radio_catalog.endpoints(catalog_station)[0]
            station_title = catalog_station.name
        else:
            radio_url = radio_stream_url(station)
        current_media = MediaRef(
            MediaSource.RADIO,
            radio_url,
            title=station_title,
            resolver_data={
                "station_id": getattr(catalog_station, "station_id", station) if radio_catalog is not None else station,
                "endpoints": radio_catalog.endpoints(catalog_station) if radio_catalog is not None else [radio_url],
            },
            capabilities=MediaCapabilities(finite=False, live=True, seekable=False, downloadable=False),
        )
    elif _type == "yt_video":
        current_media = MediaRef(MediaSource.YOUTUBE, vidurl, resolver_data={"youtube": True})
    elif _type == "audio":
        current_media = MediaRef(MediaSource.URL, audurl)
    elif _type == "local":
        path = localpath[0] if isinstance(localpath, list) else localpath
        current_media = MediaRef(MediaSource.LOCAL, str(Path(path).resolve()))
        if isinstance(localpath, list) and len(localpath) > 1:
            current_media.resolver_data["legacy_playlist"] = list(localpath)
    else:
        raise ValueError("Media type not provided")
    return current_media.original_uri


def media_player(action=None, playing_time=None):
    del playing_time
    if action == "play":
        if current_media is None:
            raise PlaybackError("No media has been prepared")
        supervisor.play(current_media)
    elif action == "pausetoggle":
        controller.toggle_pause()
    elif action == "stop":
        supervisor.stop()
    elif action == "resync":
        controller.restart_live()
    else:
        raise UnsupportedAction(f"Unknown playback action: {action}")


def wait_until_playing(timeout=15, poll_interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = controller.snapshot().state
        if state in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}:
            return True
        if state == PlaybackState.FAILED:
            raise PlaybackError(controller.snapshot().error or "Playback failed")
        time.sleep(poll_interval)
    raise TimeoutError(f"FFmpeg did not start playback within {timeout} seconds")


def close() -> None:
    supervisor.close()

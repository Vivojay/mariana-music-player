import ctypes
import importlib
import os
import time
from pathlib import Path

from ruamel.yaml import YAML

from beta.youtube_media import stream_url
from runtime_check import find_vlc_directory, inspect_vlc_installation
from url_validate import id_if_url_is_of_yt_format


yaml = YAML(typ="safe")

PY_ARCH = 8 * ctypes.sizeof(ctypes.c_void_p)
VLC_ARCH = None
VLC_PATH = None
SETTINGS = None
VLC_AVAILABLE = False
VLC_ERROR = "VLC 3.x is unavailable; install 64-bit VLC to use online playback."
vlc = None
vlc_media_player = None
vlc_media_list = None

RADIO_STREAMS = {
    "coffee": "https://somafm.com/m3u/gsclassic.m3u",
    "chillout": "https://somafm.com/m3u/groovesalad.m3u",
    "lounge": "https://somafm.com/m3u/illstreet.m3u",
}


def require_vlc():
    if not VLC_AVAILABLE or vlc is None:
        raise RuntimeError(VLC_ERROR)


def wait_until_playing(timeout=15, poll_interval=0.05):
    require_vlc()
    deadline = time.monotonic() + timeout
    player = vlc_media_player.get_media_player()
    while time.monotonic() < deadline:
        if player.is_playing():
            return True
        time.sleep(poll_interval)
    raise TimeoutError(f"VLC did not start playback within {timeout} seconds")


def radio_stream_url(name):
    try:
        return RADIO_STREAMS[name]
    except KeyError as error:
        raise ValueError(f"Unknown radio station: {name}") from error


def set_media(_type=None, vidurl=None, audurl=None, localpath=None):
    """Create VLC media while keeping the historical command interface."""
    require_vlc()
    try:
        media_player(action="stop")
    except Exception:
        pass

    player = vlc.Instance()
    player.log_unset()

    if _type.startswith("radio"):
        radio_type = _type.split("/")[1]
        load_media_object(player=player, mrls_list=[radio_stream_url(radio_type)])
    elif _type == "yt_video":
        if vidurl:
            audurl = stream_url(vidurl, audio_only=True)
        if not audurl:
            raise ValueError("YouTube media did not provide a playable audio stream")
        load_media_object(player=player, mrls_list=[audurl])
    elif _type == "audio":
        if audurl:
            if id_if_url_is_of_yt_format(audurl):
                audurl = f"https://www.youtube.com/watch?v={id_if_url_is_of_yt_format(audurl)}"
                audurl = stream_url(audurl, audio_only=True)
            load_media_object(player=player, mrls_list=[audurl])
    elif _type == "local":
        if not isinstance(localpath, list):
            localpath = [localpath]
        load_media_object(player=player, mrls_list=localpath)
    else:
        print("Media type not provided")

    return audurl


def load_media_object(player, mrls_list):
    global vlc_media_list, vlc_media_player

    media_list = player.media_list_new()
    for mrl in mrls_list:
        media = player.media_new(mrl)
        media_list.add_media(media)

    vlc_media_player = player.media_list_player_new()
    vlc_media_player.set_media_list(media_list)
    vlc_media_list = media_list


def vlc_import():
    global VLC_ARCH, VLC_PATH, SETTINGS, VLC_AVAILABLE, VLC_ERROR, vlc

    settings_path = Path(__file__).resolve().parents[1] / "settings" / "settings.yml"
    with settings_path.open("r", encoding="utf-8") as stream:
        SETTINGS = yaml.load(stream)

    VLC_PATH = SETTINGS.get("vlc path")
    directory = find_vlc_directory(VLC_PATH)
    if directory is None:
        VLC_ERROR = "VLC 3.x was not found; install 64-bit VLC or configure 'vlc path' in settings/settings.yml."
        return False

    VLC_ARCH, version = inspect_vlc_installation(directory)
    if VLC_ARCH != PY_ARCH:
        VLC_ERROR = f"VLC must be {PY_ARCH}-bit to match this Python installation."
        return False
    if version is None or version[0] != 3:
        detected = "unknown" if version is None else ".".join(map(str, version))
        VLC_ERROR = f"VLC 3.x is required for online playback; detected version {detected}."
        return False

    try:
        os.add_dll_directory(str(directory))
        vlc = importlib.import_module("vlc")
    except (ImportError, OSError) as error:
        VLC_ERROR = f"VLC could not be loaded from {directory}: {error}"
        return False

    VLC_AVAILABLE = True
    temp_directory = Path(__file__).resolve().parents[1] / "temp"
    temp_directory.mkdir(exist_ok=True)
    (temp_directory / "hasvlc.tmp").touch()
    return True


def media_player(action=None, playing_time=None):
    del playing_time
    require_vlc()

    if action == "pausetoggle":
        if bool(vlc_media_player.get_state()):
            vlc_media_player.pause()
        else:
            vlc_media_player.play()
    elif action == "play":
        vlc_media_player.play()
    elif action == "stop":
        vlc_media_player.stop()
    elif action == "resync":
        was_playing = bool(vlc_media_player.get_media_player().is_playing())
        vlc_media_player.stop()
        vlc_media_player.play()
        if was_playing:
            wait_until_playing()
        else:
            vlc_media_player.pause()


def main():
    pass


vlc_import()

if __name__ == "__main__":
    main()

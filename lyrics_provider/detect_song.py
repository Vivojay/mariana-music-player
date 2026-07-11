import os
import sys
import asyncio
import requests
import subprocess as sp
from pathlib import Path

from ruamel.yaml import YAML
from shazamio import Shazam

from beta.youtube_media import stream_url

# import nest_asyncio
# nest_asyncio.apply()

HTTP_TIMEOUT = (5, 30)

APP_DIR = Path(__file__).resolve().parents[1]
TEMP_DIR = APP_DIR / 'temp'
RELATED_SONGS_PATH = APP_DIR / 'data' / 'related_songs.yml'

yaml = YAML(typ='safe')

RELATED_SONGS_PATH.parent.mkdir(parents=True, exist_ok=True)
if not RELATED_SONGS_PATH.is_file():
    RELATED_SONGS_PATH.touch()

def get_weblink_audio_info(max_wait_lim, weblink, isYT=False):

    headers = {"Range": "bytes=0-25000"}
    if isYT:
        try:
            audio_url = stream_url(weblink, audio_only=True)
            r = requests.get(audio_url, headers=headers, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
        except Exception:
            return {} # TODO - write to log: couldn't clean temp dir
    else:
        # Old way -> Downloads whole mka file
        # r = requests.get(weblink)

        # New way -> Tries to download first 25000 bytes of mka file only
        try:
            r = requests.get(weblink, headers=headers, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
        except Exception:
            try:
                r = requests.get(weblink, timeout=HTTP_TIMEOUT)
                r.raise_for_status()
            except requests.RequestException:
                return {}

    bytecontent = r.content

    try:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        src_path = TEMP_DIR / "song_detect.mka"
        dest_path = TEMP_DIR / "song_detect.mp3"
        with src_path.open('wb') as soundfile:
            soundfile.write(bytecontent)

        try:
            sp.run(["ffmpeg",
                    "-loglevel", "quiet",
                    "-hide_banner", "-y",
                    "-i",
                    str(src_path),
                    str(dest_path)],
                    stderr = sp.DEVNULL,
                    stdout = sp.DEVNULL,
                    stdin = sp.PIPE)
        except FileNotFoundError:
            return {} # TODO - write to log: "ffmpeg not recognised globally"

        if src_path.is_file():
            try: src_path.unlink()
            except OSError:
                pass # TODO - write to log: couldn't clean temp dir

        if dest_path.is_file():
            out = get_song_info(str(dest_path))
            try: dest_path.unlink()
            except OSError:
                pass # TODO - write to log: couldn't clean temp dir
        else:
            return {} # TODO - write to log: File coversion to mp3 unsuccessful

    except Exception:
        return {} # TODO - write to log: couldn't clean temp dir
    return out


async def shazam_detect_song(songfile):
    shazam = Shazam()
    shazam_song_detection_result = await shazam.recognize(songfile)
    return shazam_song_detection_result


def _section(track, section_type):
    for section in track.get('sections') or []:
        if section.get('type') == section_type:
            return section
    return {}


def normalize_song_info(shazam_song_detection_result):
    track = shazam_song_detection_result.get('track') or {}
    if not track or not shazam_song_detection_result.get('matches'):
        return {}

    lyrics_section = _section(track, 'LYRICS')
    metadata_section = _section(track, 'SONG')
    return {
        "display_name": (track.get('share') or {}).get('subject') or track.get('title'),
        "is_explicit": (track.get('hub') or {}).get('explicit'),
        "shazam_id": track.get('key'),
        "metadata": metadata_section.get('metadata') or [],
        "lyrics": lyrics_section.get('text') or [],
        "genres": track.get('genres') or {},
    }


def get_song_info(songfile, display_shazam_id=False, get_related=False, get_title_only=False):
    """
    songfile: Takes a file path and returns its shazam
    display_shazam_id param: If true, displays unique shazam key of the shazamed song
    get_related param: If true, gets a list of information of related song
    """
    if os.path.isfile(songfile):
        shazam_song_detection_result = asyncio.run(shazam_detect_song(songfile))

        if display_shazam_id:
            print(f"Shazam ID: {(shazam_song_detection_result.get('track') or {}).get('key')}")

        song_info = normalize_song_info(shazam_song_detection_result)
        if get_related:
            if song_info != {}:
                sp.Popen(
                    [sys.executable, str(APP_DIR / 'lyrics_provider' / 'get_related_music.py'), str(song_info['shazam_id'])],
                    shell=False,
                    cwd=APP_DIR,
                )
            return song_info
        elif get_title_only:
            if song_info == {}:
                return None
            else:
                return song_info['display_name']
        else:
            return song_info

    else:
        raise OSError

if __name__ == '__main__':
    ARGS = sys.argv[1:]


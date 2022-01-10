import os
import sys
import asyncio
import requests
import subprocess as sp

from pafy import new
from ruamel.yaml import YAML
import yaml as pyyaml
from shazamio import Shazam, serialize_track

# import nest_asyncio
# nest_asyncio.apply()

CURDIR = os.path.dirname(os.path.realpath(__file__))
os.chdir(CURDIR)
os.chdir('..')

yaml = YAML(typ='safe')

if not os.path.isfile('data/related_songs.yml'):
    with open('data/related_songs.yml', 'w') as f: pass

def get_weblink_audio_info(weblink, isYT=False):
    os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

    headers = {"Range": "bytes=0-5000"}
    if isYT:
        try:
            vid = new(weblink)
            audio_url = vid.getworstaudio().url
            try:
                r = requests.get(audio_url, headers=headers)
            except Exception:
                r = requests.get(audio_url)
        except Exception:
            return {} # TODO - write to log: couldn't clean temp dir
    else:
        # Old way -> Downloads whole mka file
        # r = requests.get(weblink)

        # New way -> Try to download first 5000 bytes of mka file only
        try:
            r = requests.get(weblink, headers=headers)
        except Exception:
            r = requests.get(weblink)

    bytecontent = r.content

    try:
        if not os.path.isdir("temp"): os.mkdir("temp")
        with open("temp/song_detect.mka", 'wb') as soundfile:
            soundfile.write(bytecontent)

        src_path = "temp/song_detect.mka"
        dest_path = "temp/song_detect.mp3"

        try:
            sp.run(["ffmpeg",
                    "-loglevel", "quiet",
                    "-hide_banner", "-y",
                    "-i",
                    src_path,
                    dest_path],
                    stderr = sp.DEVNULL,
                    stdout = sp.DEVNULL,
                    stdin = sp.PIPE)
        except FileNotFoundError:
            return {} # TODO - write to log: "ffmpeg not recognised globally"

        if os.path.isfile("temp/song_detect.mka"):
            try: os.remove("temp/song_detect.mka")
            except OSError:
                pass # TODO - write to log: couldn't clean temp dir

        if os.path.isfile("temp/song_detect.mp3"):
            out = get_song_info("temp/song_detect.mp3")
            try: os.remove("temp/song_detect.mp3")
            except OSError:
                pass # TODO - write to log: couldn't clean temp dir
        else:
            return {} # TODO - write to log: File coversion to mp3 unsuccessful

    except Exception:
        return {} # TODO - write to log: couldn't clean temp dir
    return out


async def shazam_detect_song(songfile):
    shazam = Shazam()
    shazam_song_detection_result = await shazam.recognize_song(songfile)
    return shazam_song_detection_result

async def shazam_get_song_info(shazam_id):
    shazam = Shazam()
    about_track = await shazam.track_about(track_id=shazam_id)

    # serialized = serialize_track(data=about_track)
    # print(serialized)  # serialized from dataclass factory

    return(about_track)  # dict


def get_song_info(songfile, display_shazam_id=False, get_related=False):
    """
    songfile: Takes a file path and returns its shazam
    display_shazam_id param: If true, displays unique shazam key of the shazamed song
    get_related param: If true, gets a list of information of related song
    """
    if os.path.isfile(songfile):
        loop1 = asyncio.get_event_loop()
        shazam_song_detection_result = loop1.run_until_complete(shazam_detect_song(songfile))

        if display_shazam_id:
            print(f"Shazam ID: {shazam_song_detection_result.get('track')['key']}")

        if shazam_song_detection_result['matches'] == []:
            # print(shazam_song_detection_result)
            song_info = {}

        else:
            song_info = {
                "display_name": shazam_song_detection_result.get('track').get('share').get('subject'),
                "is_explicit": shazam_song_detection_result.get('track').get('hub').get('explicit'),
                "shazam_id": shazam_song_detection_result.get('track').get('key'), # Stored as a string and converted to int when needed...
                "metadata": shazam_song_detection_result.get('track').get('sections')[0].get('metadata'),
                "lyrics": shazam_song_detection_result.get('track').get('sections')[1].get('text'),
                "genres": shazam_song_detection_result.get('track').get('genres'),
            }

        if get_related and song_info != {}:
            loop2 = asyncio.get_event_loop()
            related_tracks_data_raw=loop2.run_until_complete(shazam_get_song_info(45612815))
            related_tracks_data_url=related_tracks_data_raw.get('sections')[4].get('url')
            related_tracks_data=requests.get(related_tracks_data_url).json()
            related_track_objects=related_tracks_data.get('tracks')

            related_track_ids = [int(track.get('key')) for track in related_track_objects]

            related_songs_info = []

            for track_id in related_track_ids:
                loop2 = asyncio.get_event_loop()
                shazam_song_detection_result = loop2.run_until_complete(shazam_get_song_info(track_id))

                related_song_info = {
                    "display_name": shazam_song_detection_result.get('share').get('subject'),
                    "youtube_url": shazam_song_detection_result.get('sections')[2].get('youtubeurl'),
                    "is_explicit": shazam_song_detection_result.get('hub').get('explicit'),
                    "shazam_id": shazam_song_detection_result.get('key'), # Stored as a string and converted to int when needed...
                    "metadata": shazam_song_detection_result.get('sections')[0].get('metadata'),
                    "lyrics": shazam_song_detection_result.get('sections')[1].get('text'),
                    "genres": shazam_song_detection_result.get('genres'),
                }

                related_songs_info.append(related_song_info)

            if related_songs_info: # BETA
                with open('data/related_songs.yml', 'a', encoding='utf-8') as fp:
                    pyyaml.dump(related_songs_info,
                                stream=fp,
                                allow_unicode=True,
                                sort_keys=False)

        return song_info

    else:
        raise OSError

if __name__ == '__main__':
    ARGS = sys.argv[1:]
    # if len(ARGS) == 2:
    # if ARGS[0] == ''

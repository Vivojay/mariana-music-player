import os
import sys
import asyncio
import requests
import subprocess as sp

from pafy import new
from ruamel.yaml import YAML
from shazamio import Shazam, serialize_track

# import nest_asyncio
# nest_asyncio.apply()

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

CURDIR = os.path.dirname(os.path.realpath(__file__))
os.chdir(CURDIR)
os.chdir('..')

yaml = YAML(typ='safe')

if not os.path.isfile('data/related_songs.yml'):
    with open('data/related_songs.yml', 'w') as f: pass

def get_weblink_audio_info(max_wait_lim, weblink, isYT=False):

    headers = {"Range": "bytes=0-25000"}
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

        # New way -> Tries to download first 25000 bytes of mka file only
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


def get_song_info(songfile, display_shazam_id=False, get_related=False, get_title_only=False):
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

        if get_related:
            if song_info != {}:
                sp.Popen(['..\.virtenv\Scripts\python.exe', 'lyrics_provider/get_related_music.py', song_info['shazam_id']], shell=True)
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


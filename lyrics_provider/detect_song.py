import asyncio
# import nest_asyncio
import sys
import os

from pafy import new
from ruamel.yaml import YAML
from shazamio import Shazam, serialize_track
# nest_asyncio.apply()
yaml = YAML(typ='safe')


def get_weblink_audio_info(weblink, isYT=False):
    os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
    from io import BytesIO
    import requests, pygame

    if isYT:
        try:
            vid = new(weblink)
            audio_url = vid.getbestaudio().url
            r = requests.get(audio_url)
        except Exception: return None # TODO - write to log: couldn't clean temp dir
    else:
        r = requests.get(weblink)

    bytecontent = r.content
    try:
        if not os.path.isdir("temp"): os.mkdir("temp")
        with open("temp/song_detect.wav", 'wb') as soundfile:
            soundfile.write(bytecontent)

        if not os.path.isfile("temp/song_detect.wav"): raise OSError
        else:
            out = get_song_info("temp/song_detect.wav")
            try: os.remove("temp/song_detect.wav")
            except OSError: pass # TODO - write to log: couldn't clean temp dir

    except Exception: return None # TODO - write to log: couldn't clean temp dir
    return out


async def shazam_detect_song(songfile):
    global shazam_song_detection_result
    shazam = Shazam()
    shazam_song_detection_result = await shazam.recognize_song(songfile)

async def shazam_get_song_info(shazam_id):
    shazam = Shazam()
    about_track = await shazam.track_about(track_id=shazam_id)
    serialized = serialize_track(data=about_track)

    print(about_track)  # dict
    print(serialized)  # serialized from dataclass factory


def get_song_info(songfile, display_shazam_id=False):
    if os.path.isfile(songfile):
        loop1 = asyncio.get_event_loop()
        loop1.run_until_complete(shazam_detect_song(songfile))

        loop1 = asyncio.get_event_loop()
        loop1.run_until_complete(shazam_get_song_info(songfile))

        # if sys.version_info < (3, 7):
        #     loop = asyncio.get_event_loop()
        #     loop.run_until_complete(shazam_detect_song(songfile))
        # else:
        #     asyncio.run(shazam_detect_song(songfile))

        if shazam_song_detection_result['matches'] == []:
            print(shazam_song_detection_result)
            song_info = []

        else:
            song_info = {
                "display_name": shazam_song_detection_result['track']['share']['subject'],
                "is_explicit": shazam_song_detection_result['track']['hub']['explicit'],
                "shazam_id": shazam_song_detection_result['track']['key'],
                "metadata": shazam_song_detection_result['track']['sections'][0]['metadata'],
                "lyrics": shazam_song_detection_result['track']['sections'][1]['text'],
                "genres": shazam_song_detection_result['track']['genres'],
            }

            if display_shazam_id:
                print(f"Shazam ID: {song_info['shazam_id']}")

            # Functionality for getting information bout the song does not work...
            # 
            # 
            # try:
            #     shazam_about_song_result = shazam_get_song_info(shazam_id=song_info['shazam_id'])
            #     print(shazam_about_song_result)
            #     song_info.update(shazam_about_song_result)
            # except Exception:
            #     raise

        return song_info

    else:
        raise OSError


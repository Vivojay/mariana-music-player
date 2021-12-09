import asyncio
import nest_asyncio
import sys
import os

from ruamel.yaml import YAML
from shazamio import Shazam

nest_asyncio.apply()
yaml = YAML(typ='safe')

async def shazam_detect_song(songfile):
    global shazam_detection_result
    shazam = Shazam()
    shazam_detection_result = await shazam.recognize_song(songfile)

def get_song_info(songfile):
    if os.path.isfile(songfile):
        if sys.version_info < (3, 7):
            loop = asyncio.get_event_loop()
            loop.run_until_complete(shazam_detect_song(DEMO_SONG))
        else:
            asyncio.run(shazam_detect_song(songfile))

        if shazam_detection_result['matches'] == []:
            print(shazam_detection_result)
            song_info = []

        else:
            song_info = {
                "display_name": shazam_detection_result['track']['share']['subject'],
                "is_explicit": shazam_detection_result['track']['hub']['explicit'],
                "shazam_id": shazam_detection_result['track']['key'],
                "metadata": shazam_detection_result['track']['sections'][0]['metadata'],
                "lyrics": shazam_detection_result['track']['sections'][1]['text'],
                "genres": shazam_detection_result['track']['genres'],
            }

        return song_info
    
    else:
        raise OSError


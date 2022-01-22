import sys
import asyncio
import requests
import yaml as pyyaml

from shazamio import Shazam

async def shazam_get_song_info(shazam_id):
    shazam = Shazam()
    about_track = await shazam.track_about(track_id=shazam_id)
    return(about_track)  # dict

def get_related_music(shazam_id):
    shazam_id = int(shazam_id)

    loop2 = asyncio.get_event_loop()

    related_tracks_data_raw=loop2.run_until_complete(shazam_get_song_info(shazam_id))
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

    return related_songs_info

if __name__ == '__main__':
    ARGS = sys.argv[1:]
    if len(ARGS) == 1:
        try:
            get_related_music(ARGS[0])
        except Exception:
            pass


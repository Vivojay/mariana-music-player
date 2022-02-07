'''
random song (optional repeat, no repeat by default)
log data about each song path
    timestamp of play
    list of tags
    favourited? (bool)
    corrupted? (bool)
    blacklisted? (bool)

    # Maybe
    estimated bpm
    estimated key/scale
'''

import os
import json
import requests
from datetime import datetime as dt

current_date = dt.today().date()

def refresh_podcast_data():
    from pyPodcastParser.Podcast import Podcast

    response = requests.get('https://feed.podbean.com/tracklists/feed.xml')
    podcast = Podcast(response.content)
    podcasts_raw = []

    for item in [pod.to_dict() for pod in podcast.items]:
        if item not in podcasts_raw:
            podcasts_raw.append(item)

    with open('data/podbean_radio.json', 'w', encoding='utf-8') as fp:
        json.dump({"podcasts_raw": podcasts_raw,
                   "last_write_date": current_date.strftime('%d-%m-%Y')}, fp, indent=3)

    return podcasts_raw

def get_latest_podcasts():
    global saved_podcast_data, last_podcast_data_write_date, current_date
    podcasts_raw = None
    saved_podcast_data = None
    last_podcast_data_write_date = None
    podcasts = []

    if os.path.isfile('data/podbean_radio.json'):
        with open('data/podbean_radio.json', 'r', encoding='utf-8') as fp:
            try: saved_podcast_data = json.load(fp)
            except json.decoder.JSONDecodeError: pass

            try: last_podcast_data_write_date = dt.strptime(saved_podcast_data['last_write_date'], '%d-%m-%Y').date()
            except Exception: pass

            if saved_podcast_data:
                if ((last_podcast_data_write_date is not None and last_podcast_data_write_date < current_date) or not last_podcast_data_write_date):
                    # If a write date exists and it's older than today, or if it doesn't exist, refresh the data
                    podcasts_raw = refresh_podcast_data()
                else:
                    # Load existing data, because it is already up to date
                    podcasts_raw = saved_podcast_data['podcasts_raw']
            else:
                # Data is corrupt/incomplete, refresh the data
                podcasts_raw = refresh_podcast_data()
    else:
        # No data exists, refresh the data
        podcasts_raw = refresh_podcast_data()

    for pod in podcasts_raw:
        podcasts.append({'is_explicit':  pod.get('itunes_explicit'),
                         'caption':      pod.get('itunes_subtitle'),
                         'artwork':      pod.get('itune_image'),
                         'url':          pod.get('enclosure_url'),
                         'pub_date':     pod.get('published_date'),
                         'title':        pod.get('title')})

    # podcast_urls = [pod.get('enclosure_url') for pod in podcasts_raw]
    return podcasts


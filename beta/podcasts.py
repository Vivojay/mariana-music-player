import os
import json
import requests
from datetime import datetime as dt

current_date = dt.today().date()

vendors = {
    '1001tracklists': 'https://feed.podbean.com/tracklists/feed.xml',
    'podnews': 'https://podnews.net/rss',
    'the_daily': 'https://feeds.simplecast.com/54nAGcIl',
    'crime_junkie': 'https://feeds.simplecast.com/qm_9xx0g',
    'the_trueman_show': 'https://feed.podbean.com/jornluka/feed.xml',
    'dead_eyes': 'https://www.omnycontent.com/d/playlist/77bedd50-a734-42aa-9c08-ad86013ca0f9/2d19c94e-5da0-4ea5-95b1-ad8d012c3386/3c109dc9-8fa7-4ea7-b84b-ad8d012c3390/podcast.rss',
    'overdue': 'https://www.omnycontent.com/d/playlist/77bedd50-a734-42aa-9c08-ad86013ca0f9/e7707767-fd61-4887-b6ee-ad88014933e3/b9defaac-c62e-4810-bc36-ad88014933fb/podcast.rss',
    'ezra_klein_show': 'https://feeds.simplecast.com/82FI35Px',
    'anything_for_selena': 'https://rss.wbur.org/anythingforselena/podcast',
    'midnight_miracle': 'https://feeds.megaphone.fm/LM6964003519',
    'storytime_with_seth_rogen': 'https://feeds.simplecast.com/ZK9BGVQN',
    'maintenance_phase': 'https://feeds.simplecast.com/ZK9BGVQN',
}

def refresh_podcast_data(rss_link, output_file):
    from pyPodcastParser.Podcast import Podcast

    response = requests.get(rss_link)
    podcast = Podcast(response.content)
    podcasts_raw = []

    for item in [pod.to_dict() for pod in podcast.items]:
        if item not in podcasts_raw:
            podcasts_raw.append(item)

    with open(output_file, 'w', encoding='utf-8') as fp:
        json.dump({"podcasts_raw": podcasts_raw,
                   "last_write_date": current_date.strftime('%d-%m-%Y')}, fp, indent=3)

    return podcasts_raw

def get_latest_podbean_data(vendor = '', rss_link = None):
    global saved_podcast_data, last_podcast_data_write_date, current_date
    podcasts_raw = None
    saved_podcast_data = None
    last_podcast_data_write_date = None

    if rss_link:
        output_file = 'data/podbean_custom_rss.json'
        podcasts_raw = refresh_podcast_data(rss_link=rss_link, output_file=output_file)
    else:
        rss_link = vendors.get(vendor)
        if not rss_link: return
        output_file = 'data/podbean_{}.json'.format(vendor)

        if os.path.isfile(output_file):
            with open(output_file, 'r', encoding='utf-8') as fp:
                try: saved_podcast_data = json.load(fp)
                except json.decoder.JSONDecodeError: pass

                try: last_podcast_data_write_date = dt.strptime(saved_podcast_data['last_write_date'], '%d-%m-%Y').date()
                except Exception: pass

                # Saved data exists and was successfully loaded
                if saved_podcast_data:
                    if ((last_podcast_data_write_date is not None and last_podcast_data_write_date < current_date) or not last_podcast_data_write_date):
                        # If a write date exists and it's older than today, or if it doesn't exist, refresh the data
                        podcasts_raw = refresh_podcast_data(rss_link=rss_link, output_file=output_file)
                    else:
                        # Load existing data, because it is already up to date
                        podcasts_raw = saved_podcast_data['podcasts_raw']
                else:
                    # Data is corrupt/incomplete, refresh the data
                    podcasts_raw = refresh_podcast_data(rss_link=rss_link, output_file=output_file)
        else:
            # No data exists, refresh the data
            podcasts_raw = refresh_podcast_data(rss_link=rss_link, output_file=output_file)



    # podcast_urls = [pod.get('enclosure_url') for pod in podcasts_raw]
    podcasts = [{'is_explicit':  pod.get('itunes_explicit'),
                 'caption':      pod.get('itunes_subtitle'),
                 'artwork':      pod.get('itune_image'),
                 'url':          pod.get('enclosure_url'),
                 'pub_date':     pod.get('published_date'),
                 'title':        pod.get('title')} for pod in podcasts_raw]

    return podcasts


# podnews_rss_url = 'https://podnews.net/rss'
# response = requests.get(podnews_rss_url)
# podcast = Podcast(response.content)

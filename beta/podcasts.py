import hashlib
import json
import os
from datetime import datetime as dt
from pathlib import Path

import requests

from mariana.entertainment_catalog import PODCAST_ALIASES
from mariana.models import podcast_episode_identity
from mariana.podcast_feeds import MAX_PODCAST_BYTES, PodcastFeedError, parse_podcast_feed

HTTP_TIMEOUT = (5, 30)


# TODO: Add a WHOLE LOT more.... and read from a file instead
# TODO: Better still, get podbeans API to search for urls for you...

# Some predefined podbean podcasts with corresponding links
vendors = {
  "1001tracklists": "https://feed.podbean.com/tracklists/feed.xml",
  "bravo_daily_dish": "https://rss.art19.com/the-daily-dish",
  "bravo_hot_mic": "https://rss.art19.com/bravos-hot-mic-previews",
  "vanderpump_rules_party": "https://feeds.captivate.fm/vanderpumprulesparty/",
  "podnews": "https://podnews.net/rss",
  "the_daily": "https://feeds.simplecast.com/54nAGcIl",
  "crime_junkie": "https://feeds.simplecast.com/qm_9xx0g",
  "the_trueman_show": "https://feed.podbean.com/jornluka/feed.xml",
  "dead_eyes": "https://www.omnycontent.com/d/playlist/77bedd50-a734-42aa-9c08-ad86013ca0f9/2d19c94e-5da0-4ea5-95b1-ad8d012c3386/3c109dc9-8fa7-4ea7-b84b-ad8d012c3390/podcast.rss",
  "overdue": "https://www.omnycontent.com/d/playlist/77bedd50-a734-42aa-9c08-ad86013ca0f9/e7707767-fd61-4887-b6ee-ad88014933e3/b9defaac-c62e-4810-bc36-ad88014933fb/podcast.rss",
  "ezra_klein_show": "https://feeds.simplecast.com/82FI35Px",
  "anything_for_selena": "https://rss.wbur.org/anythingforselena/podcast",
  "midnight_miracle": "https://feeds.megaphone.fm/LM6964003519",
  "storytime_with_seth_rogen": "https://feeds.simplecast.com/ZK9BGVQN",
  "maintenance_phase": "https://feeds.buzzsprout.com/1411126.rss",
  "a_date_with_dateline": "https://feeds.megaphone.fm/adatewithdateline",
  "down_the_rabbit_hole": "https://feed.podbean.com/downthetrabbitholes/feed.xml",
  "dateline_nbc": "https://podcastfeeds.nbcnews.com/dateline",
  "no_such_thing_as_a_fish": "https://audioboom.com/channels/2399216.rss",
  "friday_night_comedy_bbc_radio": "https://podcasts.files.bbci.co.uk/p02pc9pj.rss",
  "critical_role": "https://feed.podbean.com/geekandsundry/feed.xml",
  "mental_oasis": "https://feed.podbean.com/mentaloasis/feed.xml",
  "the_blemished_brain": "https://feed.podbean.com/mattiekk/feed.xml",
  "the_depression_files": "https://feed.podbean.com/allevin18/feed.xml",
  "vox_conversations": "https://feeds.megaphone.fm/theezrakleinshow",
  "the_survival_podcast": "https://www.thesurvivalpodcast.com/feed/podcast",
  "dear_hank_&_john": "https://feeds.simplecast.com/9YNI3WaL",
  "mark_levin_podcast": "https://feeds.megaphone.fm/mark-levin-podcast",
  "the_daily_show_with_trevor_noah_ears_edition": "https://feeds.megaphone.fm/the-daily-show",
  "bishop_td_jakes_full-legnth_sermons_and_interviews": "https://www.spreaker.com/show/2978578/episodes/feed",
  "rudolf_steiner_audio": "https://feed.podbean.com/rudolfsteiner/feed.xml",
  "projeto_mayhem": "https://feed.podbean.com/projetomayhem/feed.xml",
  "joshua_live_and_the_law_of_attraction": "https://feed.podbean.com/joshualive/feed.xml",
  "planet_money": "https://feeds.npr.org/510289/podcast.xml",
  "the_ramsey_show": "https://daveramsey.libsyn.com/rss",
  "jocko_podcast": "https://feeds.redcircle.com/64a89f88-a245-4098-8d8d-496325ec4f74",
  "the_grant_williams_podcast": "https://feed.podbean.com/ttmygh/feed.xml",
  "the_ken_coleman_show": "https://thekencolemanshow.libsyn.com/rss",
  "hbr_ideacast": "http://feeds.harvardbusiness.org/harvardbusiness/ideacast",
  "ted_talks_daily": "http://feeds.feedburner.com/TEDTalks_audio",
  "self_improvement_daily": "https://anchor.fm:443/s/471bee4/podcast/rss",
  "cleaning_up_the_mental_mess_with_dr._caroline_leaf": "https://anchor.fm/s/236705fc/podcast/rss",
  "overcome_depression_+_thrive": "http://overcomedepressionandthrive.com/feed/podcast",
  "the_innerfrench_podcast": "http://podcast.innerfrench.com/feed.xml"
}

# Hosting platforms do not require separate feed implementations or duplicate programmes.
vendors.update(PODCAST_ALIASES)

# Older caches for this alias may contain Storytime episodes under the wrong
# programme name. Revalidate them once; never rebind those episode identities.
_CORRECTED_FEED_VENDORS = frozenset({"maintenance_phase"})


def _feed_cache_identity(rss_link):
    """Bind cache content to its source without saving a private feed URL."""
    return hashlib.sha256(rss_link.encode("utf-8")).hexdigest()


def refresh_podcast_data(rss_link, output_file, cached=None):
    headers = {"User-Agent": "Mariana/0.7 (+https://github.com/Vivojay/mariana-music-player)"}
    if cached:
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]
    response = requests.get(rss_link, timeout=HTTP_TIMEOUT, headers=headers, stream=True)
    if getattr(response, "status_code", 200) == 304 and cached:
        if hasattr(response, 'close'):
            response.close()
        return cached.get("podcasts_raw", [])
    try:
        response.raise_for_status()
        payload = bytearray()
        chunks = response.iter_content(65536) if hasattr(response, 'iter_content') else [response.content]
        for chunk in chunks:
            payload.extend(chunk)
            if len(payload) > MAX_PODCAST_BYTES:
                raise PodcastFeedError('Podcast feed exceeds the 8 MiB limit')
        podcasts_raw = parse_podcast_feed(bytes(payload), rss_link)
    finally:
        if hasattr(response, 'close'):
            response.close()

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as fp:
        json.dump({"podcasts_raw": podcasts_raw,
                   "feed_identity": _feed_cache_identity(rss_link),
                   "last_write_date": dt.today().date().strftime('%d-%m-%Y'),
                   "etag": getattr(response, "headers", {}).get("ETag"),
                   "last_modified": getattr(response, "headers", {}).get("Last-Modified")}, fp, indent=3)

    return podcasts_raw

def get_latest_podbean_data(vendor = '', rss_link = None):
    global saved_podcast_data, last_podcast_data_write_date
    current_date = dt.today().date()
    podcasts_raw = None
    saved_podcast_data = None
    last_podcast_data_write_date = None

    if rss_link:
        output_file = 'data/podbean_custom_rss.json'
        podcasts_raw = refresh_podcast_data(rss_link=rss_link, output_file=output_file)
    else:
        rss_link = vendors.get(vendor)
        if not rss_link: return
        output_file = f'data/podbean_{vendor}.json'
        expected_feed_identity = _feed_cache_identity(rss_link)

        if os.path.isfile(output_file):
            with open(output_file, encoding='utf-8') as fp:
                try: saved_podcast_data = json.load(fp)
                except json.decoder.JSONDecodeError: pass

                if saved_podcast_data and (
                    saved_podcast_data.get("feed_identity", expected_feed_identity) != expected_feed_identity
                    or (vendor in _CORRECTED_FEED_VENDORS and not saved_podcast_data.get("feed_identity"))
                ):
                    saved_podcast_data = None

                try: last_podcast_data_write_date = dt.strptime(saved_podcast_data['last_write_date'], '%d-%m-%Y').date()
                except Exception: pass

                # Saved data exists and was successfully loaded
                if saved_podcast_data:
                    if (
                           (last_podcast_data_write_date is not None and \
                            last_podcast_data_write_date < current_date) or not \
                            last_podcast_data_write_date
                        ):
                        # If a write date exists and it's older than today, or if it doesn't exist, refresh the data
                        try:
                            podcasts_raw = refresh_podcast_data(
                                rss_link=rss_link,
                                output_file=output_file,
                                cached=saved_podcast_data,
                            )
                        except (requests.RequestException, ValueError):
                            podcasts_raw = saved_podcast_data['podcasts_raw']
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
    podcasts = []
    for pod in podcasts_raw:
        identity = podcast_episode_identity(
            rss_link,
            guid=pod.get('episode_guid'),
            episode_url=pod.get('episode_url'),
            enclosure_url=pod.get('enclosure_url'),
            title=pod.get('title'),
            published_timestamp=pod.get('published_timestamp'),
            published=pod.get('published_date'),
        )
        podcasts.append({
            'is_explicit': pod.get('itunes_explicit'),
            'caption': pod.get('itunes_subtitle'),
            'artwork': pod.get('itune_image'),
            'url': pod.get('enclosure_url'),
            'pub_date': pod.get('published_date'),
            'published_timestamp': pod.get('published_timestamp', 0),
            'title': pod.get('title'),
            'stable_id': identity[0] if identity else None,
            'identity_kind': identity[1] if identity else None,
            'programme': pod.get('programme'),
            'creator': pod.get('creator'),
            'language': pod.get('language'),
            'duration': pod.get('duration'),
            'chapters': pod.get('chapters', []),
        })

    # Sorting podcasts by date of publish (newest first)
    podcasts.sort(key=lambda x: x['published_timestamp'], reverse=True)

    return podcasts


# podnews_rss_url = 'https://podnews.net/rss'
# response = requests.get(podnews_rss_url)
# podcast = Podcast(response.content)

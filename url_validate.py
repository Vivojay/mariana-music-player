from urllib.parse import parse_qs, unquote_plus, urlparse

import requests

HTTP_TIMEOUT = (5, 15)

def id_if_url_is_of_yt_format(some_url):
    if not isinstance(some_url, str) or not some_url.strip():
        return None

    parsed = urlparse(unquote_plus(some_url.strip()))
    host = (parsed.hostname or "").lower()
    youtube_hosts = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }

    if host in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/").split("/", 1)[0] or None
    if host and host not in youtube_hosts:
        return None

    query = parse_qs(parsed.query)
    if len(query.get("v", [])) == 1:
        return query["v"][0] or None

    for key in ("url", "u"):
        if len(query.get(key, [])) == 1:
            nested = query[key][0]
            if nested.startswith("/"):
                nested = f"https://www.youtube.com{nested}"
            if video_id := id_if_url_is_of_yt_format(nested):
                return video_id

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"embed", "v", "shorts", "live"}:
        return parts[1] or None
    return None

def url_is_valid(url, yt=None): # yt param only added for compatibility with other files in codebase
                                # it is not used in this function and is entirely ignored
    """
    Checks that a given URL is reachable.
    :param url: A URL
    """

    yt = id_if_url_is_of_yt_format(url)

    try:
        if yt is not None:
            from beta.youtube_media import is_resolvable

            return is_resolvable(f'https://www.youtube.com/watch?v={yt}')
        status_code = requests.head(url, allow_redirects=True, timeout=HTTP_TIMEOUT).status_code
        return status_code < 400
    except Exception:
        return False


import requests

from urllib.parse import urlparse, unquote_plus, parse_qs

def id_if_url_is_of_yt_format(some_url):
    vid_id = None

    some_url = unquote_plus(some_url)
    url_path = urlparse(some_url).path
    url_query_p = parse_qs(urlparse(some_url).query)
    
    if url_query_p.get('v'):
        if len(url_query_p['v']) == 1:
            vid_id = url_query_p['v'][0]
    
    elif url_query_p.get('url'):
        if len(url_query_p.get('url')) == 1:
            vid_url_crude = url_query_p['url'][0]
            try:
                url_query_p = parse_qs(urlparse(vid_url_crude).query)
                if len(url_query_p['v']) == 1:
                    vid_id = url_query_p['v'][0]
            except Exception:
                pass
    
    elif url_query_p.get('u'):
        if len(url_query_p.get('u')) == 1:
            try:
                vid_id = url_query_p['u'][0].lstrip('/watch?v=')
            except Exception:
                pass
    
    elif url_path.count('/v/') == 1 or url_path.count('/embed/') == 1:
        url_path = url_path.replace('/v/', '').replace('/embed/', '')
        vid_id = url_path
    
    elif url_path.count('/') == 1 and url_path[0] == '/':
        vid_id = url_path.split('/')[1]

    return vid_id

def url_is_valid(url, yt=None): # yt param only added for compatibility with other files in codebase
                                # it is not used in this function and is entirely ignored
    """
    Checks that a given URL is reachable.
    :param url: A URL
    """

    yt = id_if_url_is_of_yt_format(url)

    try:
        status_code = requests.head(url).status_code
        if not yt: return status_code < 400
        elif yt is not None:
            # Extra steps for verification of YouTube URLs
            oEmbed_request_output = requests.get(f'https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v={yt}').text
            return oEmbed_request_output.strip().lower() != 'bad request'
        else:
            return False
    except Exception:
        return False


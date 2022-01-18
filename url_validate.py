import urllib.request

def url_is_valid(url, yt=True):
    """
    Checks that a given URL is reachable.
    :param url: A URL
    :rtype: bool
    """

    try:
        request = urllib.request.Request(url)
        request.get_method = lambda: "HEAD"
        urllib.request.urlopen(request)
        if yt:
            return url.startswith('https://www.youtube.com/watch?v=')
        else:
            return True
    except urllib.request.HTTPError:
        return False
    except urllib.error.URLError:
        return False
    except ValueError:
        return False

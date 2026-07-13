"""Compatibility facade for Mariana's existing YouTube command handlers."""

from tabulate import tabulate as tbl

import beta.IPrint
from beta.youtube_media import YouTubeError, media_info
from beta.youtube_media import search as search_media

_BROWSER_PROFILE: str | None = None


def configure(*, browser_profile: str | None = None) -> None:
    """Apply the same explicit browser reference to search and metadata calls."""
    global _BROWSER_PROFILE
    _BROWSER_PROFILE = browser_profile or None


def vid_info(vid_url: str, detailed: bool = False):
    try:
        return media_info(vid_url, detailed=detailed, browser_profile=_BROWSER_PROFILE)
    except YouTubeError as exc:
        raise OSError(str(exc)) from exc


def search_youtube(
    search: str,
    rescount: int = 1,
    display_results: bool = True,
    extra_output: bool = False,
):
    if extra_output:
        beta.IPrint.IPrint("Searching")

    try:
        results = search_media(search, limit=rescount, browser_profile=_BROWSER_PROFILE)
    except YouTubeError as exc:
        raise OSError(str(exc)) from exc

    if not results:
        raise OSError("No YouTube results found")

    if rescount == 1:
        result = (results[0]["title"], results[0]["url"])
        if extra_output:
            print(result[0])
            print(f"    @ {result[1]}")
        return result

    output = [(index + 1, item["title"], item["url"]) for index, item in enumerate(results)]
    if display_results:
        print(tbl(output, headers=("#", "NAME", "URL")))
    return output

import urllib
import re
import pafy

# import IPrint
import beta.IPrint

from tabulate import tabulate as tbl
from collections import OrderedDict


def vid_info(vid_url: str, detailed=False):
    pafyVidObj = pafy.new(vid_url)

    astreams = pafyVidObj.audiostreams
    vstreams = pafyVidObj.videostreams

    if detailed:
        vidInfoObj = {
            "dislikes": pafyVidObj.dislikes,
            "likes": pafyVidObj.likes,
            "views": pafyVidObj.viewcount,
            "thumbnail": pafyVidObj.thumb,
            "title": pafyVidObj.title,
            "duration": pafyVidObj.duration,
            "streams": {
                "bestaudurl": pafyVidObj.getbestaudio().url,
                "bestvidurl": pafyVidObj.getbestvideo().url,
                "audios": [
                    {
                        "bitrate": astream.bitrate,
                        "title": astream.title,
                        "size": astream.get_filesize(),
                        "url": astream.url,
                        "type": astream.extension,
                        "acodec": astream._info["acodec"],
                        "duration": stream_duration(astream),
                        "notes": astream.notes,
                    }
                    for astream in astreams
                ],
                "videos": [
                    {
                        "resolution": vstream.resolution,
                        "title": vstream.title,
                        "fps": vstream._info["fps"],
                        "size": vstream.get_filesize(),
                        "url": vstream.url,
                        "type": vstream.extension,
                        "vcodec": vstream._info["vcodec"],
                        "duration": stream_duration(vstream),
                        "notes": vstream.notes,
                    }
                    for vstream in vstreams
                ],
            },
        }
    else:
        vidInfoObj = {
            "title": pafyVidObj.title,
            "duration": pafyVidObj.duration,
            "streams": {
                "bestaudurl": pafyVidObj.getbestaudio().url,
                "bestvidurl": pafyVidObj.getbestvideo().url,
            },
        }

    return vidInfoObj


def stream_duration(stream):
    duration = 0
    try:
        _ = stream._info["fragments"]
    except KeyError:
        return "NA"

    for i in stream._info["fragments"]:
        try:
            duration += i["duration"]
        except Exception:
            pass

    return round(duration)


def search_youtube(search: str, rescount: int = 1, display_results: bool = True, extra_output: bool = False):
    if extra_output:
        beta.IPrint.IPrint("Searching")

    # # Check if the given search term is a valid youtube video link
    # if(search.startswith("https://www.youtube.com")):
    #     res = urllib.request.urlopen(search)

    #     if(res.getcode() == 200):
    #         return search

    search_url = "https://www.youtube.com/results?search_query={}".format(search.replace(" ", "+"))

    html = urllib.request.urlopen(search_url)
    vid_ids = list(OrderedDict.fromkeys(re.findall(r"watch\?v=(\S{11})", html.read().decode())))[:rescount]
    vid_urls = [f"https://www.youtube.com/watch?v={vid_id}" for vid_id in vid_ids]

    if rescount == 1 and display_results:
        vid_title = vid_info(vid_urls[0], detailed=not True)["title"]
        out = (vid_title, vid_urls[0])

        if extra_output:
            print(out[0])
            print(f"    @ {out[1]}")

        return out

    else:
        out = []
        for vid in vid_urls:
            try:
                out.append((vid_info(vid, detailed=not True)["title"], vid))
            except OSError:
                out.append(None)

        out = [(i, *j) for i, j in list(enumerate(out))]
        out = [(lambda x, y, z: (x + 1, y, z))(*i) for i in out]
        if display_results:
            print(tbl(out, headers=("#", "NAME", "URL")))

        return out

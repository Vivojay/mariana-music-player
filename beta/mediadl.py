# Media downloader
from __future__ import unicode_literals

import os
import sys
import json
import youtube_dl.YoutubeDL


# Relative imports
curdir = os.path.dirname(os.path.realpath(__file__))
os.chdir(curdir)
os.chdir('..')

sys.path.insert(0, os.getcwd())
from logger import SAY


"""
explicitly-specified-quality ? use_that : use quality mentioned in SETTINGS
"""

def media_DL(SETTINGS,
             SYSTEM_SETTINGS,
             media_urls,
             typ = None,
             quality = None,
             make_separate_mariana_dl_dir = None,
             dry_run=False):
    
    """
    SETTINGS: dict (settings/settings.yml) (User's personal settings)
    media_url: audio/video url for downloading...
    typ: (download_type)
        0: audio only
        1: video with audio
    quality:
        For audio-only downloads
            0: worst quality audio only
            1: best quality audio only
        For video-with-audio downloads
            {"audio": audio_quality,
            "video": video_quality}:
            Where audio_quality and video_quality may be either
            0 or 1 for worst or best quality respectively.
    """

    available_qualities = ('worst', 'best')
    dl_dir_is_valid = False
    dl_dir = None

    try:
        dl_dir = SETTINGS.get('download').get('downloads folder')
    except Exception:
        pass

    if dl_dir:
        dl_dir = os.path.expanduser(dl_dir)
        if os.path.isdir(dl_dir):
            dl_dir_is_valid = True
        else:
            returncode = 0 # Output directory does not exist
    else:
        returncode = 1 # Output directory path in SETTINGS is empty

    if not dl_dir_is_valid:
        SAY(visible = True,
            log_message=f'Invalid dl dir, defaulting to ~/Music',
            display_message='',
            log_priority=2,
        )
        return returncode

    try:
        make_separate_mariana_dl_dir = SETTINGS['download']['make a separate mariana folder within "downloads folder"']
    except Exception:
        SAY(visible = True,
            log_message=f'Invalid/non-existent setting for creating separate download directory for Mariana Player',
            display_message='',
            log_priority=2,
        )
        return 2 # SETTING for 'make a separate mariana folder within "downloads folder"'
                    # is non-existent

    if make_separate_mariana_dl_dir:
        try:
            mariana_dl_dir = SYSTEM_SETTINGS['system_settings']['mariana_dl_dir']
            dl_dir = os.path.join(dl_dir, mariana_dl_dir)
            if not os.path.isdir(dl_dir):
                os.mkdir(dl_dir)
        except Exception:
            return 3 # Could not create separate mariana directory

    ydl_outtmpl = os.path.join(dl_dir, "%(title)s.%(ext)s")

    if typ not in [0, 1]: # Invalid dl typ, revert to settings...
        typ = SETTINGS['download']['type'].lower().strip()
        typ = ['audio', 'video'].index(typ)

    if quality is None:
        if typ == 0:
            quality = SETTINGS['download']['quality']['audio only']
        elif typ == 1:
            quality = SETTINGS['download']['quality']['video with audio']

    if typ == 0: # Audio
        aud_qual = available_qualities[quality]
        ydl_vid_fmt = f'{aud_qual}audio/{aud_qual}'
    elif typ == 1: # Video
        vid_qual = available_qualities[quality["video"]]
        aud_qual = available_qualities[quality["audio"]]
        ydl_vid_fmt = f'{vid_qual}video+{aud_qual}audio/{vid_qual}'


    ydl_opts = {
        'outtmpl': ydl_outtmpl,
        'age_limit': 20,
        'format': ydl_vid_fmt, # best/worst is used when audio and video come premuxed
        # 'progress_hooks': [my_hook], # TODO - Review: Make a progress bar...???
    }

    if typ == 1:
        ydl_opts.update({
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })

    if type(media_urls) != list:
        media_urls = [media_urls]

    if not dry_run:
        try:
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                ydl.download(media_urls)
            returncode = 4 # Successfull Download
        except Exception:
            returncode = 5 # Failed Download
    else:
        return ydl_opts # Operation run as dry-run

    return returncode


if __name__ == '__main__':
    ARGS = sys.argv[1:]
    if len(ARGS) == 1:
        try:
            dl_kwargs_dict = json.loads(ARGS[0])
            media_DL_return_code = media_DL(**dl_kwargs_dict)
            sys.exit(f"EXIT CODE: {media_DL_return_code}")
        except Exception:
            sys.exit('ERROR: Invalid command')
    else:
        sys.exit('ERROR: Invalid command')

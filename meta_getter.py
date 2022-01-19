"""
Will keep running in background even if main.py closes
until meta data for all files have been extracted saved
"""

import os
import sys
import json
import subprocess as sp

from url_validate import url_is_valid

ARGS = sys.argv[1:]

cur_dir = os.path.dirname(os.path.realpath(__file__))
os.chdir(cur_dir)


def get_meta(media_list, supported_file_types):

    """
    media_list: a list of absolute file paths to all media
    supported_file_types: a list of supported file types (usually taken from "main.py")
    """

    os.chdir(cur_dir)
    valid_medias_list = []

    for media in media_list:
        if os.path.isfile(media):
            if media.endswith(supported_file_types):
                valid_medias_list.append(media)
        elif url_is_valid(media):
            valid_medias_list.append(media)

    for n, media in enumerate(valid_medias_list):
        meta_info = sp.run(['ffprobe',
                            '-v',
                            'quiet',
                            '-print_format',
                            'json',
                            '-show_format',
                            '-show_streams',
                            media],
                            capture_output=True,
                            text=True).stdout

        meta_info = json.loads(meta_info)
        meta_info['format'].update({'bpm': 120})

        with open(f'data/mediameta_{n}.json', 'w', encoding='utf-8') as fp:
            json.dump(meta_info, fp, indent=2)

    return valid_medias_list

if __name__ == "__main__":
    ARGS = sys.argv[1:]
    if len(ARGS) == 2:
        try:
            get_meta(*ARGS)
            sys.exit(0)
        except Exception:
            sys.exit(1)
    else:
        sys.exit(1)

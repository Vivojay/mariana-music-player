
#################################################################################################################################
# Mariana Player v0.4.2

# running app:
#	For very first boot (SETUP):
# 	  Make sure you have python version < 3.10 to run this file (unless compatible llvmlite wheel bins exist...)
# 	  Setup this program in a fresh virtualenv
# 	  Download and pip install unofficial binary for llvmlite wheel compatible with your python version
# 	  Setup compatible architecture of VLC media player, install FFMPEG and add to path...
# 	  Install git scm if not already installed
# 	  Install given git package directly from url using: `pip install git+https://github.com/Vivojay/pafy@develop`
# 	  run `pip install -r requirements.txt`
#
# 	  Firstly, look at help.md before running any py file
# 	  Run this file (main.py) on the very first bootup, nothing else (no flags, just to test bare minimum run)...
# 	  You are good to go...
#     *Note: If you encounter errors, look for online help as the current help file doesn't have common problem fixes yet
#
#	All successive boots (RUNNING NORMALLY):
#	  just run this file (main.py) with desired flags (discussed in help.md)
#	  and enjoy... (and possibly debug...)

# This app may take a LOT of time to load at first... (main culprit: librosa)
# Hence the loading prompt...
# Prompts like these will be made better and more
# dynamic using the IPrint (custom) and multiprocess modules

# Editor's Note: Make sure to brew a nice coffee beforehand... :)
#################################################################################################################################


# IMPORTS BEGIN #

import time
APP_BOOT_START_TIME = time.time();                  print("Loaded 1/25", end='\r')

import os;                                          print("Loaded 2/25", end='\r')
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

# import itertools;                                   print("Loaded 3/25", end='\r')

import re;                                          print("Loaded 4/25", end='\r')
import sys;                                         print("Loaded 5/25",  end='\r')
import urllib;                                      print("Loaded 6/25",  end='\r')
import pygame;                                      print("Loaded 7/25",  end='\r')
import numpy as np;                                 print("Loaded 8/25", end='\r')
import random as rand;                              print("Loaded 9/25", end='\r')
import importlib;                                   print("Loaded 10/25", end='\r')
import colored;                                     print("Loaded 11/25", end='\r')

# import concurrent.futures;                          print("Loaded 11/25", end='\r')

from tabulate import tabulate as tbl;               print("Loaded 12/25", end='\r')
from ruamel.yaml import YAML;                       print("Loaded 13/25", end='\r')
from collections.abc import Iterable;               print("Loaded 14/25", end='\r')
from logger import SAY;                             print("Loaded 15/25", end='\r')
from multiprocessing import Process;                print("Loaded 16/25", end='\r')

import subprocess as sp;                            print("Loaded 17/25", end='\r')
import restore_default;                            print("Loaded 17/25", end='\r')

online_streaming_ext_load_error = 0
lyrics_ext_load_error = 0
redditsessions = None


# try:
#     import librosa
#     print("Loaded 18/25",  end='\r') # Time taking import (Sometimes, takes ages...)
# except ImportError:
#     print("[WARN] Could not load music computation extension...")
#     print("[WARN] Skipped 18/25")

try:
    vas = importlib.import_module("beta.vlc-async-stream")
    vas = importlib.reload(vas)
    print("Loaded 19/25", end='\r')
except ImportError:
    online_streaming_ext_load_error = 1
    print("[INFO] Could not load online streaming extension...")
    print("[INFO] Skipped 19/25")

try:
    YT_query = importlib.import_module("beta.YT_query")
    print("Loaded 20/25", end='\r')
except ImportError:
    # raise
    if not online_streaming_ext_load_error:
        print("[INFO] Could not load online streaming extension...")
    print("[INFO] Skipped 20/25")

try:
    IPrint = importlib.import_module('beta.IPrint')
    print("Loaded 21/25", end='\r')
except ImportError:
    lyrics_ext_load_error = 1
    print("[INFO] Could not load coloured print extension...")
    print("[INFO] Skipped 21/25")

try:
    lvw = importlib.import_module('lyrics_provider.lyrics_view_window')
    print("Loaded 22/25", end='\r')
except ImportError:
    print("[INFO] Could not load lyrics extension...")
    if not lyrics_ext_load_error:
        print("[INFO] Could not load online streaming extension...")
    print("[INFO] Skipped 22/25")

try:
    from beta import redditsessions
    if redditsessions.WARNING:
        print("[WARN] Could not load reddit-sessions extension...")
        print(f"[WARN] {redditsessions.WARNING}")
        print("[WARN] Skipped 23/25")
        redditsessions = None
    else:
        print("Loaded 23/25", end='\r')
except ImportError:
    print("[INFO] Could not load reddit-sessions extension..., module 'praw' missing")
    print("[INFO] Skipped 23/25")

# Encountered new unexpected and unresolved error in importing comtypes...
# Syntax Error @line 375 in comtypes/__init__.py
# from beta.master_volume_control import get_master_volume, set_master_volume
# print("Loaded 24/25", end='\r')

import webbrowser;                                      print("Loaded 25/25", end='\r')

# IMPORTS END #


CURDIR = os.path.dirname(os.path.realpath(__file__))
os.chdir(CURDIR)
yaml = YAML(typ='safe')  # Allows for safe YAML loading

if not os.path.isdir('logs'): os.mkdir('logs')

def create_required_files_if_not_exist(*files):
    for file in files:
        if not os.path.isfile(file):
            with open(file, 'w', encoding="utf-8") as _:
                pass

create_required_files_if_not_exist(
    'logs/recents.log',
    'logs/general.log',
)

FIRST_BOOT = False # Assume user is using app for considerable time
                   # so you don't want to annoy him with an
                   # annoying FIRST-TIME-WELCOME

try:
    with open('about/about.info', encoding='utf-8') as file:
        ABOUT = yaml.load(file)
        FIRST_BOOT = ABOUT['first_boot']
except IOError:
    ABOUT = None

ISDEV = ABOUT['isdev'] # Useful as a test flag for new features

try:
    with open('lib.lib', encoding='utf-8') as logfile:
        paths = logfile.read().splitlines()
        paths = [path for path in paths if not path.startswith('#')]
        paths = list(set(paths))
except IOError:
    if not FIRST_BOOT:
        sys.exit("[INFO] Could not find lib.lib file, '\
                'please create one and add desired source directories. '\
                'Aborting program\n")


def first_startup_greet(is_first_boot):
    if is_first_boot:
        try:
            import first_boot_setup
            first_boot_setup.fbs(about=ABOUT)
            reload_sounds()
        except ImportError:
            sys.exit('[ERROR] Critical guide setup-file missing, please consider reinstalling this file or the entire program\nAborting Mariana Player. . .')

try:
    with open('user/user_data.yml', encoding='utf-8') as u_data_file:
        USER_DATA = yaml.load(u_data_file)
        if list(USER_DATA.keys()) == ['default_user_data']:
            if not FIRST_BOOT and not ISDEV: # TODO - remove temp ISDEV flag after user login and register feature is fully functional
                SAY(visible=visible,
                    display_message = '',
                    log_message = 'User data found to be empty, reverting to default',
                    log_priority = 3)
except IOError:
    SAY(visible=visible,
        display_message = f'Encountered missing program file @{os.path.join(CURDIR, "user/user_data.yml")}',
        log_message = 'User data file not found',
        log_priority = 1) # Log fatal crash
    sys.exit(1) # Fatal crash


try:
    with open('settings/settings.yml', encoding='utf-8') as u_data_file:
        SETTINGS = yaml.load(u_data_file)

except IOError:
    SAY(visible=visible,
        display_message = f'Encountered missing program file @{os.path.join(CURDIR, "settings/settings.yml")}',
        log_message = 'Aborting player because settings file was not found',
        log_priority = 1) # Log fatal crash
    sys.exit(1) # Fatal crash



# Variables
APP_BOOT_TIME_END = time.time()
EXIT_INFO = 0
FALLBACK_RESULT_COUNT = SETTINGS['display items count']['fallback']
FATAL_ERROR_INFO = None

isplaying = False
currentsong = None  # No song playing initially
ismuted = False
isshowinglyrics = False
currentsong_length = None

settings = None
songindex = -1

current_media_player = 0
"""
current_media_player can be either 0 or 1:
    0: default (pygame)
    1: vlc
"""

# Log levels from logger.py -> [Only for REF]
# logleveltypes = {0: "none", 1: "fatal", 2: "warn", 3: "info", 4: "debug"}

# From settings
disable_OS_requirement = True
supported_file_exts = '.wav .mp3'.split()  # Supported file extensions (wav seeking sucks with pygame)
visible = True
max_yt_search_results_threshold = 15
loglevel = SETTINGS.get('loglevel')

if not loglevel: restore_default.restore('loglevel', SETTINGS)

# From last session info
cached_volume = 1  # Set as a factor between 0 to 1 times of max volume player volume

# Flattens list of any depth
def flatten(l):
    for el in l:
        if isinstance(el, Iterable) and not isinstance(el, (str, bytes)):
            yield from flatten(el)
        else:
            yield el


# Function to extract files from folders recursively
def audio_file_gen(Dir, ext):
    for root, dirs, files in os.walk(Dir):
        for filename in files:
            if os.path.splitext(filename)[1] == ext:
                yield os.path.join(root, filename)



def reload_sounds():
    global _sound_files, _sound_files_names_only, _sound_files_names_enumerated, paths

    no_lib_found = False

    try:
        with open('lib.lib', encoding='utf-8') as logfile:
            paths = logfile.read().splitlines()
            paths = [path for path in paths if not path.startswith('#')]
            paths = list(set(paths))
    except IOError:
        no_lib_found = True
        # TODO - write some SAY() here (instead of the humble `print()`)
        print("ERROR: Library file suddenly vanished -_-")

    # if _paths != paths: SAY(): Log <- new_dirs_added

    if not no_lib_found:
        # Use the recursive extractor function and format and store them into usable lists
        _sound_files = [[list(audio_file_gen(paths[j], supported_file_exts[i]))
                        for i in range(len(supported_file_exts))] for j in range(len(paths))]
        # Flattening irregularly nested sound files
        _sound_files = list(flatten(_sound_files))

        _sound_files_names_only = [os.path.splitext(os.path.split(i)[1])[0] for i in _sound_files]
        _sound_files_names_enumerated = [(i+1, j) for i, j in enumerate(_sound_files_names_only)]

reload_sounds()

if _sound_files_names_only == []:
    if loglevel in [3, 4]:
        print("[INFO] All source directories are empty, you may and add more source directories to your library")
        print("[INFO] To edit this library file (of source directories), refer to the `help.md` markdown file.")

try: _ = sp.run('ffmpeg', stdout=sp.DEVNULL, stdin=sp.PIPE, stderr=sp.DEVNULL)
except FileNotFoundError: FATAL_ERROR_INFO = "ffmpeg not recognised globally, download it and add to path (system environment)"

if redditsessions: r_seshs = redditsessions.get_redditsessions()
else: r_seshs = None

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


def get_current_progress(): # Will not work because pygame returns
                            # playtime instead of play position
                            # when running get_pos() for some
                            # odd reason...
    if current_media_player:
        cur_prog = vas.vlc_media_player.get_media_player().get_time()/1000
    else:
        cur_prog = pygame.mixer.music.get_pos()/1000

    return cur_prog

def save_user_data():
    global USER_DATA

    total_plays = [j for i, j in
                   USER_DATA['default_user_data']['stats']['play_count'].items()
                   if i in ['local', 'radio', 'audio', 'youtube', 'redditsession']]
    total_plays = sum(total_plays)
    USER_DATA['default_user_data']['stats']['play_count']['total'] = total_plays

    with open('user/user_data.yml', 'w', encoding="utf-8") as u_data_file:
        yaml.dump(USER_DATA, u_data_file)

def exitplayer(sys_exit=False):
    global EXIT_INFO, APP_BOOT_START_TIME, USER_DATA

    stopsong()
    if not current_media_player: pygame.mixer.quit()
    APP_CLOSE_TIME = time.time()

    time_spent_on_app = APP_CLOSE_TIME - APP_BOOT_START_TIME

    SAY(visible=visible,
        display_message = '',
        log_message = f'Time spent using app = {time_spent_on_app}',
        log_priority = 3)

    USER_DATA['default_user_data']['stats']['times_spent'].append(time_spent_on_app)
    save_user_data()

    if visible:
        print(colored.fg('red')+'Exiting...'+colored.attr('reset'))

    if sys_exit:
        sys.exit(f"{EXIT_INFO}")

# def loadsettings():
#     global settings
#     with open('', encoding='utf-8') as settingsfile:
#         settings = yaml.load(settingsfile)


def play_local_default_player(songpath, _songindex):
    global isplaying, currentsong, currentsong_length, songindex, current_media_player
    global USER_DATA, current_media_type, SONG_CHANGED

    try:
        if current_media_player:
            vas.media_player(action='stop')
        pygame.mixer.music.load(songpath)
        pygame.mixer.music.play()
        current_media_player = 0
        isplaying = True
        currentsong = songpath

        if _songindex:
            print(colored.fg('dark_olive_green_2') + \
                  f':: {_sound_files_names_only[int(_songindex)-1]}' + \
                  colored.attr('reset'))
        else:
            print(colored.fg('dark_olive_green_2') + \
                  f':: {os.path.splitext(os.path.split(songpath)[1])[0]}' + \
                  colored.attr('reset'))

            # The user is unreliable and may enter the
            # song path with weird inhumanly erratic and random
            # mix of upper and lower case characters.
            # Hence, we need to convert everything to lowercase...
            songindex = [i.lower() for i in _sound_files].index(songpath.lower())

        if not currentsong_length: get_currentsong_length()
        current_media_type = None
        USER_DATA['default_user_data']['stats']['play_count']['local'] += 1
        save_user_data()

        SAY(visible=visible,
            display_message = '',
            out_file='logs/recents.log',
            log_message = currentsong,
            log_priority = 3,
            format_style = 0)

    except Exception:
        # raise
        err(f'Failed to play: {os.path.splitext(os.path.split(songpath)[1])[0]}',
            say=False)
        SAY(
            visible=visible,
            log_priority=2,
            display_message=f"Failed to play \"{songpath}\"",
            log_message=f"Failed to play song: \"{songpath}\"",
        )


def voltransition(
    initial=cached_volume,
    final=cached_volume,
    disablecaching=False,  # NOT_USED: Enable volume caching by default
    transition_time=0.2,
    # transition_time=1,
):
    global cached_volume, current_media_player

    if current_media_player:
        for i in range(101):
            diffvolume = initial+(final-initial)*i
            time.sleep(transition_time/100)
            vas.vlc_media_player.get_media_player().audio_set_volume(int(diffvolume))
    else:
        for i in range(101):
            diffvolume = initial+(final-initial)*i/100
            time.sleep(transition_time/100)
            pygame.mixer.music.set_volume(round(diffvolume, 2))

    # if not disablecaching:
    #     cached_volume = final


def vol_trans_process_spawn():
    vol_trans_process = Process(target=voltransition,
                                args=({'initial': cached_volume,
                                       'final': 0,
                                       'disablecaching': True}))
    vol_trans_process.start()
    vol_trans_process.join()


def playpausetoggle(softtoggle=True, use_multi=False):  # Soft pause by default
    global isplaying, currentsong, cached_volume, current_media_player

    try:
        if currentsong:
            if isplaying:
                # with concurrent.futures.ProcessPoolExecutor() as executor:
                if softtoggle:
                    if use_multi:
                        vol_trans_process_spawn()
                    else:
                        voltransition(initial=cached_volume,
                                      final=0, disablecaching=True)
                    # executor.submit(voltransition, initial=cached_volume, final=0, disablecaching=True)
                else:
                    if use_multi:
                        vol_trans_process_spawn()
                    else:
                        voltransition(initial=cached_volume, final=0,
                                      transition_time=0, disablecaching=True)
                    # executor.submit(voltransition, initial=cached_volume, final=0, transition_time=0, disablecaching=True)

                if current_media_player:
                    vas.media_player(action='pausetoggle')
                else:
                    pygame.mixer.music.pause()

                isplaying = False
                print("|| Paused")
            else:
                if current_media_player:
                    vas.media_player(action='pausetoggle')
                else:
                    pygame.mixer.music.unpause()

                # with concurrent.futures.ProcessPoolExecutor() as executor:
                if softtoggle:
                    if current_media_player:
                        vas.vlc_media_player.get_media_player().audio_set_volume(0)
                    else:
                        pygame.mixer.music.set_volume(0)
                    if use_multi:
                        vol_trans_process_spawn()
                    else:
                        voltransition(initial=0, final=cached_volume)
                    # executor.submit(voltransition, initial=0, final=cached_volume)
                else:
                    if current_media_player:
                        vas.vlc_media_player.get_media_player().audio_set_volume(0)
                    else:
                        pygame.mixer.music.set_volume(0)
                    if use_multi:
                        vol_trans_process_spawn()
                    else:
                        voltransition(initial=0, final=cached_volume, transition_time=0)
                    # executor.submit(voltransition, initial=0, final=cached_volume, transition_time=0)

                isplaying = True
                print("|> Resumed")
        else:
            isplaying = False
            err("Nothing to pause/unpause", say=False)

    except Exception:
        # raise
        err(f'Failed to toggle play/pause: {currentsong}', say=False)
        SAY(
            visible=visible,
            log_priority=2,
            display_message=f"Failed to toggle play/pause for \"{currentsong}\"",
            log_message=f"Failed to toggle play pause for song: \"{currentsong}\"",
        )


def stopsong():
    global isplaying, currentsong, current_media_player
    try:
        if current_media_player:
            vas.media_player(action='stop')
        else:
            pygame.mixer.music.stop()
        currentsong = None
        isplaying = False
    except Exception:
        print(f'Failed to stop: {currentsong}')


def err(error_topic='', message='', say=True):
    global visible
    print(colored.fg('red')+f'x| ERROR {error_topic}'+colored.attr('reset'))
    if message:
        print(colored.fg('red')+'x|  '+message+colored.attr('reset'))

    if say:
        SAY(visible=visible, log_priority=2, display_message=error_topic)


def searchsongs(queryitems):
    global _sound_files_names_enumerated

    out = []
    for index, song in _sound_files_names_enumerated:
        flag = True
        for queryitem in list(set(queryitems)):
            if queryitem.lower() not in song.lower():
                flag = False

        if flag:
            out.append((index, song))

    return out


# TODO - Implement librosa bpm + online bpm API features 
# def get_bpm(filename, duration=50, enable_round=True):
#     y, sr = librosa.load(filename, duration=duration)
#     tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
#     if enable_round:
#         return round(tempo)
#     else:
#         return tempo

def enqueue(songindices):
    print("Enqueueing")
    global song_paths_to_enqueue

    song_paths_to_enqueue = []

    for songindex in songindices:
        song_paths_to_enqueue.append(_sound_files[int(songindex)-1])

    for songpath in song_paths_to_enqueue:
        try:
            pygame.mixer.music.queue(songpath)
            print("Queued")
            if isplaying:
                pygame.mixer.music.unpause()
        except Exception:
            err("Queueing error", "Could not enqueue one or more files")
            raise


def play_commands(commandslist, _command=False):
    global cached_volume, currentsong_length
    pygame.mixer.music.set_volume(cached_volume)

    if not _command:
        if len(commandslist) == 2:
            songindex = commandslist[1]
            if songindex.isnumeric():
                if int(songindex) in range(len(_sound_files)+1):
                    currentsong_length = None
                    play_local_default_player(_sound_files[int(songindex)-1],
                             _songindex=songindex)
                else:
                    err('Out of range',
                        f'Please input song number between 1 and {len(_sound_files)}')

        else:
            songindices = commandslist[1:]
            _ = []
            for songindex in songindices:
                try:
                    if songindex.isnumeric():
                        _.append(songindex)
                except Exception:
                    pass

            songindices = _
            del _

            enqueue(songindices)
    else:
        currentsong_length = None
        play_local_default_player(songpath=_command[1:], _songindex=None)

def timeinput_to_timeobj(rawtime):
    try:
        if ':' in rawtime.strip():
            processed_rawtime = rawtime.split(':')
            processed_rawtime = [int(i) if i else 0 for i in processed_rawtime]

            # print(processed_rawtime)

            # timeobj: A list of the format [WHOLE HOURS IN SECONDS, WHOLE MINUTES in SECONDS, REMAINING SECONDS]
            timeobj = [value * 60 ** (len(processed_rawtime) - _index - 1)
                       for _index, value in enumerate(processed_rawtime)]

            totaltime = sum(timeobj)

            formattedtime = ' '.join([''.join(map(lambda x: str(x), i)) for i in list(
                zip(processed_rawtime, ['h', 'm', 's'][3-len(processed_rawtime):]))])

            if totaltime > currentsong_length:
                return ValueError
            else:
                return (formattedtime, totaltime)

        else:
            if rawtime.strip() == '-0':
                return ('0', 0)

            elif rawtime.isnumeric():
                if int(rawtime) > currentsong_length:
                    return ValueError
                else:
                    processed_rawtime = list(
                        map(lambda x: int(x), convert(int(rawtime)).split(':')))
                    formattedtime = ' '.join([''.join(map(lambda x: str(x), i)) for i in list(
                        zip(processed_rawtime, ['h', 'm', 's'][3-len(processed_rawtime):]))])
                    # print (None, rawtime)
                    return (formattedtime, rawtime)

    except Exception:
        # print (None, None)
        return (None, None)

def get_currentsong_length():
    global current_media_player, currentsong_length, currentsong_length
    if currentsong:
        if current_media_player:
            if not currentsong_length:
                currentsong_length = currentsong_length/1000
        else:
            cursong_obj = pygame.mixer.Sound(currentsong)
            currentsong_length = cursong_obj.get_length()

    return currentsong_length

def song_seek(timeval=None, rel_val=None):
    global currentsong

    if timeval:
        if current_media_player:
            try:
                vas.vlc_media_player.get_media_player().set_time(int(timeval)*1000)
                return True
            except Exception:
                raise
                return None
                # raise # TODO - remove all "raise"d exceptions?
        else:
            try:
                pygame.mixer.music.set_pos(int(timeval))  # *1000)
                return True
            except pygame.error:
                SAY(visible=visible, display_message="Error: Can't seek in this song",
                    log_message=f'Unsupported codec for seeking song: {currentsong}', log_priority=2)
                return None

    elif rel_val:
        pass
    else:
        SAY(visible=visible, display_message="Error: Can't seek in this song",
            log_message=f'Unsupported codec for seeking song: {currentsong}', log_priority=2)
        return None


def setmastervolume(value=None):
    global cached_volume
    if not value:
        value = cached_volume

    if value in range(101):
        set_master_volume(value)
    else:
        SAY(visible=visible, display_message='ERROR: Could not set master volume',
            log_message='Could not set master volume', log_priority=2)

def convert(seconds):
    seconds = seconds % (24 * 3600)
    hour = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60

    return "{0:0>2.0f}:{1:0>2.0f}:{2:0>2.0f}".format(hour, minutes, seconds)


def rand_song_index():
    global _sound_files_names_only
    return rand.randint(0, len(_sound_files_names_only)-1)


def validate_time(rawtime):
    rawtime = rawtime.replace(':', '')
    try:
        _ = float(rawtime)
    except Exception:
        return 2
    if '.' in rawtime:
        return 1
    elif float(rawtime) < 0:
        return 3
    else:
        return 0


# `media_url` is the only mandatory param in `play_vas_media`
def play_vas_media(media_url, single_video = None, media_name = None,
                   print_now_playing = True, media_type = 'video'):

    global isplaying, current_media_player, visible, currentsong, cached_volume, current_media_type
    global currentsong_length, currentsong_length

    # Stop prev songs b4 loading VAS Media...
    stopsong()

    # VAS Media Load/Set
    current_media_player = 1 # Set current media player as VLC
    if media_type == 'video':
        YT_aud_url = vas.set_media(_type='yt_video', vidurl=media_url)

        current_media_type = 0

        if not media_name:
            try:
                vid_info = YT_query.vid_info(media_url)
                media_name = vid_info['title']
            except Exception:
                media_name = '[VIDEO NAME COULD NOT BE RESOLVED]'
                SAY(visible=visible,
                    display_message = '',
                    log_message = f'video name could not be resolved for {currentsong[1]}',
                    log_priority = 2)

        currentsong = (media_name, media_url, YT_aud_url)

        if print_now_playing and visible:
            if single_video:
                print(f"Playing YouTube search result: {colored.fg('plum_1')}{media_name}{colored.attr('reset')}")
            else:
                print(f"Chosen YouTube video: {colored.fg('plum_1')}{media_name}{colored.attr('reset')}")
            print(f"{colored.fg('light_red')}@ {colored.fg('orange_1')}{media_url}{colored.attr('reset')}")

    elif media_type == 'audio':
        vas.set_media(_type='audio', audurl=media_url)

        current_media_type = 1
        currentsong = media_url
        print(f"Chosen custom audio url {currentsong}")

    elif media_type == 'radio':
        # Here `media_name` is actually the radio name
        vas.set_media(_type=f'radio/{media_name}') # No need for an explicit `audurl` here... (as per definition of vas.set_media)

        current_media_type = 2
        currentsong = media_name
        print(f"Chosen radio: {colored.fg('light_goldenrod_1')}{currentsong}{colored.attr('reset')}")

    elif media_type == 'redditsession':
        vas.set_media(_type='audio', audurl=media_url)

        current_media_type = 3
        currentsong = (media_name, media_url)

    else:
        media_type = None
        SAY(visible=visible, display_message = "Invalid media type provided", log_message = "Invalid media type provided", log_priority = 2)

    if media_type == 'video': media_type = 'youtube'
    if media_type:
        # VAS Media Play
        vas.media_player(action='play')
        vas.vlc_media_player.get_media_player().audio_set_volume(int(cached_volume*100))

        SAY(visible=visible,
            display_message = '',
            out_file='logs/recents.log',
            log_message = [' \u2014 '.join(currentsong[:-1]) if type(currentsong)==tuple else currentsong][0],
            log_priority = 3,
            format_style = 0)

    currentsong_length = None

    USER_DATA['default_user_data']['stats']['play_count'][media_type] += 1
    save_user_data()

    while not vas.vlc_media_player.get_media_player().is_playing(): pass
    while not vas.vlc_media_player.get_media_player().get_length(): pass
    currentsong_length = vas.vlc_media_player.get_media_player().get_length()/1000
    # currentsong_length gives output in ms, this will be converted to seconds when needed

    if currentsong_length == -1:
        SAY(visible=visible,
            log_message = "Cannot get length for vas media",
            display_message = "",
            log_priority=3)
    isplaying = True


def choose_media_url(media_url_choices: list, yt: bool = True):
    global current_media_player, isplaying, currentsong

    if yt:
        if len(media_url_choices) == 1:
            media_name, media_url = media_url_choices[0]
            play_vas_media(media_name=media_name, media_url=media_url, single_video=True)

        else:
            chosen_index = input(f"{colored.fg('deep_pink_4c')}Choose video number between 1 and {len(media_url_choices)}" \
                                 f" (leave blank to skip): {colored.fg('navajo_white_1')}").strip()
            print(colored.attr('reset'), end='')

            if chosen_index:
                try:
                    chosen_index = int(chosen_index)
                except Exception:
                    print("ERROR: Invalid choice, choose again: ", end='\r')

                if chosen_index in range(1, len(media_url_choices)+1):
                    _, media_name, media_url = media_url_choices[chosen_index-1]
                    play_vas_media(media_name=media_name, media_url=media_url,
                                   single_video=False)
                else:
                    print("ERROR: Invalid choice, choose again: ", end='\r')

                print()

def process(command):
    global _sound_files_names_only, visible, currentsong, isplaying, ismuted, cached_volume
    global current_media_player, current_media_type

    commandslist = command.strip().split()

    if current_media_player:
        try:
            if vas.vlc_media_player.get_state().value == 6:
                currentsong = None
                isplaying = False
        except Exception:
            pass

    else:
        if pygame.mixer.music.get_pos() == -1:
            currentsong = None

    if commandslist != []:  # Atleast 1 word

        # Quitting the player
        if commandslist in [['exit'], ['quit'], ['e']]:
            perm = input(colored.fg('light_red')+'Do you want to exit? [Y]es, [N]o (default = N): '+colored.fg('magenta_3c'))
            print(colored.attr('reset'), end = '')
            if perm.strip().lower() == 'y':
                return False

        # Quitting the player w/o conf
        elif commandslist in [['exit', 'y'], ['quit', 'y'], ['e', 'y']]:
            return False

        if commandslist == ['all']:
            results_enum = enumerate(_sound_files_names_only)
            print(tbl([(i+1, j) for i, j in results_enum], tablefmt='plain'))

        if commandslist[0] in ['list', 'ls']:
            # TODO: Need to display files in n columns (Mostly 3 cols) depending upon terminal size (dynamically...)
            if len(commandslist) == 1:
                rescount = FALLBACK_RESULT_COUNT # Default value of rescount
            elif len(commandslist) == 2:
                if commandslist[1].isnumeric():
                    rescount = int(commandslist[1])
            else:
                indices = []
                order_results = False
                order_type = 1 # Default value (1): Display in ascending order

                for i in commandslist[1:]:
                    if i.isnumeric():
                        if int(i)-1 not in indices:
                            indices.append(int(i)-1)
                    elif i == '-o': order_results = True
                    elif i == '-desc': order_type = 0

                if indices:
                    results = [_sound_files_names_only[index] for index in indices]
                    results_enum = list(zip(indices, results))
                    if order_results:
                        results_enum = sorted(results_enum, key = lambda x: x[0], reverse = not order_type)
                else:
                    # List files matching provided regex pattern
                    # Need to implement a check to validate the provided regex pattern
                    print(f'Regex search is still in progress... The developer @{ABOUT["about"]["author"]} will add this feature shortly...')
                    # regex_pattern
                    # regexp = re.compile(regex_pattern)

            if len(commandslist) in [1, 2]:
                results_enum = enumerate(_sound_files_names_only[:rescount])

            print(tbl([(i+1, j) for i, j in results_enum], tablefmt='plain'))

        elif commandslist == ['reload']: # TODO - Make useful...
            print("Reloading sounds")
            reload_sounds()
            print("Done...")

        elif commandslist == ['vis']: # TODO - Make useful...
            visible = not visible
            if visible:
                print('visibility on')

        elif commandslist == ['now']:
            if currentsong:
                if current_media_player: # VLC
                    if current_media_type == 0:
                        print(f"@ys: {currentsong[0]}")
                    elif current_media_type == 1:
                        print(f"@al: {currentsong}")
                    elif current_media_type == 2:
                        print(f"@wra: {currentsong}")
                    elif current_media_type == 3:
                        print(f"@rs: {currentsong[0]}")
                else: # pygame
                    cur_song = os.path.splitext(
                        os.path.split(currentsong)[1])[0]
                    print(f":: {_sound_files.index(currentsong)+1} | {cur_song}")
            else:
                # currentsong = None
                print("(Not Playing)")

        elif commandslist == ['now*']:
            if currentsong:
                if current_media_player: # VLC
                    if current_media_type == 0:
                        print(f"@youtube-search: Title | {currentsong[0]}")
                        print(f"                 Link  | {currentsong[1]}")
                    elif current_media_type == 1:
                        print(f"@audio-link: {currentsong}")
                    elif current_media_type == 2:
                        print(f"@webradio/{currentsong}")
                    elif current_media_type == 3:
                        print(f"@redditsession: Session | {currentsong[0]}")
                        print(f"                Link    | {currentsong[1]}")

                else: # pygame
                    print(f":: {_sound_files.index(currentsong)+1} | {currentsong}")

            else:
                currentsong = None
                print(f"(Not Playing)")

        elif commandslist[0].lower() == 'play':
            play_commands(commandslist=commandslist)

        elif commandslist[0].lower() in ['m?', 'ism?', 'ismute?']:
            # TODO - Make more reliable...?
            print(int(ismuted))

        elif commandslist[0].lower() in ['isp?', 'ispl', 'isp']:
            SAY(visible=visible,
                display_message='/? Invalid command, perhaps you meant "ispl?" for "is playing?"', log_message=f'Command assumed to be misspelled: {currentsong}', log_priority=3)

        elif commandslist[0].lower() in ['ispl?', 'isplaying?']:
            # TODO - Make more reliable...?
            print(int(isplaying))

        elif commandslist[0].lower() in ['isl?', 'isloaded?']:
            # TODO - Make more reliable...?
            if current_media_player:
                print(vas.vlc.media)
            print(int(bool(currentsong)))

        elif commandslist[0].lower() == 'seek':
            if currentsong_length:
                if len(commandslist) == 2:
                    if commandslist[1].startswith('+'):
                        rawtime = str(int(get_current_progress()) + int(commandslist[1][1:]))
                    elif commandslist[1].startswith('-'):
                        rawtime = str(int(get_current_progress()) - int(commandslist[1][1:]))
                    else:
                        rawtime = commandslist[1]
    
                    time_validity = validate_time(rawtime)

                    if not time_validity: # Raw time is valid
                        # Take a valid raw value for time from the user. Format is defined in the time section of help
                        timeobj = timeinput_to_timeobj(rawtime)
                        if not timeobj == ValueError:
                            if timeobj == (None, None):
                                err('Invalid time format', 'Invalid time object')
                            else:
                                _ = song_seek(timeval=timeobj[1])
                                if _:
                                    print(f"Seeking to: {timeobj[0]}")

                        # TODO - Make following error messages more meaningful by giving them more
                        # context depending on if absolute or relative seek was called...
                        
                        # E.g. say "reached beginning" instead of "seek val can't be -ve"
                        # When using relative seek

                        else:
                            SAY(visible=visible, display_message="Error: Seek value too large for this song",
                                log_message=f'Seek value too large for: {currentsong}', log_priority=2)
                    elif time_validity == 1:
                        SAY(visible=visible, display_message="Error: Seek value can't have a decimal point",
                            log_message=f'Seek value floating point for: {currentsong}', log_priority=2)
                    elif time_validity == 2:
                        SAY(visible=visible, display_message="Error: Seek value must be numeric",
                            log_message=f'Seek value non numeric for: {currentsong}', log_priority=2)
                    elif time_validity == 3:
                        SAY(visible=visible, display_message="Error: Seek value can't be negative",
                            log_message=f'Seek value negative for: {currentsong}', log_priority=2)
                    else:
                        pass
            else:
                SAY(visible=visible, display_message="Error: No song to seek",
                    log_message=f'Seeked song w/o playing any', log_priority=2)

        elif commandslist in [['prog'], ['progress'], ['prog*'], ['progress*']]:
            if currentsong:
                if currentsong_length:
                    cur_len = currentsong_length
                else:
                    cur_len = get_currentsong_length()

                cur_prog = get_current_progress()

                prog_sep = f"{colored.fg('green_1')}|{colored.attr('reset')}"

                if commandslist[0].endswith('*'):

                    print(f"progress: {colored.fg('deep_pink_1a')}{round(cur_prog)}/{round(cur_len)}"
                        f" {prog_sep} {colored.attr('reset')}remaining: {colored.fg('orange_1')}{round(cur_len-cur_prog)}"
                        f" {prog_sep} {colored.attr('reset')}elapsed: {colored.fg('light_goldenrod_1')}{round(cur_prog/cur_len*100)}%")
                else:
                    print(f"{colored.fg('deep_pink_1a')}{round(cur_prog)}/{round(cur_len)}"
                        f" {prog_sep} {colored.fg('orange_1')}{round(cur_len-cur_prog)}"
                        f" {prog_sep} {colored.fg('light_goldenrod_1')}{round(cur_prog/cur_len*100)}%")

        elif commandslist == ['t']:
            print(convert(get_current_progress()))

        elif commandslist == ['.rand']:  # Play random song
            play_commands(commandslist=[None, str(rand_song_index())])

        elif commandslist == ['=rand']:  # Print random song number
            print(rand_song_index())
            convert(get_current_progress())

        elif commandslist == ['rand']:  # Print random song name
            print(_sound_files_names_only[rand_song_index()])

        elif commandslist == ['rand*']:  # Print random song path
            print(_sound_files[rand_song_index()])

        elif commandslist == ['/rand']:  # Print random song number+name
            rand_index = rand_song_index()
            print(f"{rand_index+1}: {_sound_files_names_only[rand_index]}")

        elif commandslist == ['reset']:
            if currentsong_length:
                try:
                    song_seek('0')
                except Exception:
                    SAY(visible=visible, display_message="Error: Can't reset this song",
                        log_message=f'Error in resetting: {currentsong}', log_priority=2)
            else:
                SAY(visible=visible, display_message="Error: No song to seek",
                    log_message=f'Seeked song w/o playing any', log_priority=2)

        elif command[0] == '.':
            try:
                if len(commandslist) == 1:
                    # Get info of currently loaded song and display pleasantly...
                    # The info params displayed depend on those specified in the settings...
                    # getstats() # TODO - Make such a function...???
                    if commandslist[0][1:].isnumeric():
                        play_commands(commandslist=[None, ''.join(commandslist[0][1:])])

                if all([not i.replace(' ', '').isnumeric() for i in command.split('.')]): # Identifying a file-existence-check command
                    if len(command.split('.')) == 3:
                        if command.startswith('. '):
                            path = ' '.join(commandslist[1:])
                            if os.path.isfile(path):
                                if os.path.splitext(path)[1] in supported_file_exts:
                                    print(1)
                                else:
                                    print(0)
                            else:
                                print(0)
                        elif command.startswith('.'):
                            play_commands(commandslist=[None, command[1:]],
                                          _command=command)

            except Exception:
                raise

        elif commandslist in [['clear'], ['cls']]:
            os.system('cls' if os.name == 'nt' else 'clear')
            showbanner()

        elif commandslist == ['p']:
            playpausetoggle()

        elif commandslist == ['ph']:
            playpausetoggle(softtoggle=False)

        # TODO: Refactor to replace two `err` funcs with one
        elif commandslist[0].isnumeric():  # Check if only a number is entered
            # global _sound_files
            if len(commandslist) == 1:
                if int(commandslist[0]) > 0:
                    try:
                        print(colored.fg('medium_orchid_1a')+\
                              _sound_files_names_only[int(commandslist[0])-1]+\
                              colored.attr('reset'))
                    except IndexError:
                        err('', f'Please input song number between 1 and {len(_sound_files)}')
                else:
                    err('', f'Please input song number between 1 and {len(_sound_files)}')

        elif commandslist in [['count'], ['howmany'], ['total']]:
            print(len(_sound_files_names_only))

        elif commandslist[0] == 'weblinks':
            print(f'Weblinks feature is still in progress... The developer @{ABOUT["about"]["author"]} will add this feature shortly...')

        elif commandslist[0] == 'open':
            if commandslist == ['open']:
                if currentsong and current_media_player == 0:
                    if os.path.isfile(currentsong):
                        if os.path.splitext(currentsong)[1] in supported_file_exts:
                            os.system(f'explorer /select, {currentsong}')
                        else:
                            print(0)
                    else:
                        print(0)
                else:
                    if current_media_player: # VLC
                        if current_media_type == 0:
                            webbrowser.open(f"{currentsong[1]}&t={int(get_current_progress())}s")
                        elif current_media_type == 1:
                            webbrowser.open(currentsong)
                        elif current_media_type == 2:
                            webbrowser.open(f"https://s2-webradio.antenne.de/{currentsong}")
                        elif current_media_type == 3:
                            webbrowser.open(currentsong[1])
                        else:
                            SAY(visible=visible,
                                display_message = '',
                                log_message = 'Received invalid type for current media',
                                log_priority = 2,
                                format_style = 1)
                    else:
                        err("No song playing, no file selected to open")

            else:
                path = ' '.join(commandslist[1:])
                if os.path.isfile(path):
                    if os.path.splitext(path)[1] in supported_file_exts:
                        os.system(f'explorer /select, {path}')
                    else:
                        print(0)
                else:
                    print(0)

        elif commandslist in [['sm'], ['sync'], ['sync', 'media']]:
            print("Syncing current media...")
            if current_media_type == 0: # If YT vid is playing...
                print(f"YouTube audio cannot be synced, only seeked")
            elif current_media_type == 1: # If audio is playing...
                print(f"audio url cannot be synced, only seeked")
            elif current_media_type == 2: # If radio is playing...
                vas.media_player(action='resync') # Resync radio to live stream
            elif current_media_type == 3: # If reddit-session is streaming...
                # TODO - Find a way to get the current stream timestamp of current RPAN session
                print(f'Reddit session syncing... The developer @{ABOUT["about"]["author"]} will add this feature shortly...')

        elif commandslist[0] == 'path':
            if len(commandslist) == 2:
                if int(commandslist[1]) > 0:
                    try:
                        print(_sound_files[int(commandslist[1])-1])
                    except IndexError:
                        err('', f'Please input song number between 1 and {len(_sound_files)}')
                else:
                    err('', f'Please input song number between 1 and {len(_sound_files)}')

        elif commandslist[0].lower() in ['find', 'f']:
            if len(commandslist) > 1:
                myquery = commandslist[1:]
                searchresults = (searchsongs(queryitems=myquery))
                if searchresults != []:
                    print(
                      f"{colored.fg('orange_1')}Found {len(searchresults)} match{('es')*(len(searchresults)>1)} for: {' '.join(myquery)}{colored.attr('reset')}")
                    print(tbl(searchresults, tablefmt='mysql', headers=('#', 'Song')))
                else:
                    print(colored.fg('hot_pink_1a')+"-- No results found --"+colored.attr('reset'))

        elif commandslist == ['stop']:
            stopsong()

        elif commandslist == ['m']:
            ismuted = not ismuted

            if ismuted:
                if current_media_player:
                    vas.vlc_media_player.get_media_player().audio_set_mute(1)
                else:
                    pygame.mixer.music.set_volume(0)
            else:
                if current_media_player:
                    vas.vlc_media_player.get_media_player().audio_set_mute(0)
                    vas.vlc_media_player.get_media_player().audio_set_volume(cached_volume*100)
                else:
                    pygame.mixer.music.set_volume(cached_volume)

        elif commandslist in [['lyr'], ['lyrics']]:
            global isshowinglyrics
            isshowinglyrics = not isshowinglyrics
            if current_media_player:
                if current_media_type == 0:
                    print(f"Loading lyrics window for (Time taking)...")
                    lvw.show_window(weblink=currentsong[1], isYT=1)
                elif current_media_type == 1:
                    print(f"Loading lyrics window for (Time taking)...")
                    lvw.show_window(weblink=currentsong)
                elif current_media_type == 2:
                    print(f"Lyrics for Radio are not supported")
                elif current_media_type == 3:
                    print(f"Lyrics for reddit sessions are not supported")
            else:
                if currentsong:
                    if os.path.isfile(currentsong):
                        lvw.show_window(songfile=currentsong)

        elif commandslist[0].lower() in ['v', 'vol', 'volume']:
            try:
                if len(commandslist) == 2 and commandslist[1].isnumeric():
                    if '.' in commandslist[1]:
                        SAY(visible=visible, display_message='Volume must not have decimal point precision',
                            log_message='Volume set to decimal percentage', log_priority=2)
                    else:
                        volper = int(commandslist[1])
                        if volper in range(101):
                            if current_media_player:
                                vas.vlc_media_player.get_media_player().audio_set_volume(volper)
                            else:
                                pygame.mixer.music.set_volume(volper/100)

                            cached_volume = volper/100
                        else:
                            SAY(visible=visible, display_message='Volume percentage is out of range, it must be between 0 and 100',
                                log_message='Volume percentage out of range', log_priority=2)

                elif len(commandslist) == 1:
                    # print(f"}}}} {pygame.mixer.music.get_volume()*100} %")
                    print(f"}}}} {cached_volume*100} %")

            except Exception:
                err(error_topic='Some internal issue occured while setting player volume')

        elif commandslist[0].lower() in ['mv', 'mvol', 'mvolume']:
            '''
            try:
                if len(commandslist) == 2 and commandslist[1].isnumeric():
                    if '.' in commandslist[1]:
                        SAY(visible=visible, display_message='System volume must not have decimal point precision',
                            log_message='System volume set to decimal percentage', log_priority=2)
                    else:
                        volper = int(commandslist[1])
                        if volper in range(101):
                            setmastervolume(value=volper)
                        else:
                            SAY(visible=visible, display_message='System volume percentage is out of range, it must be between 0 and 100',
                                log_message='System volume percentage out of range', log_priority=2)

                elif len(commandslist) == 1:
                    try:
                        print(f"}}}} {get_master_volume()} %")
                    except Exception:
                        SAY(visible=visible, display_message='ERROR: Couldn\'t get system master volume', log_message=f'Unknown error while getting master volume as percent: {currentsong}', log_priority=2)

            except Exception:
                err(error_topic='Some internal issue occured while setting the system volume')
            '''
            print('Sorry, system volume commands have been (temporarily) disabled due to some internal issue')

        elif commandslist in [['l'], ['len'], ['length']]:
            if currentsong:
                if currentsong_length:
                    print(convert(currentsong_length))
                else:
                    print(convert(get_currentsong_length()))

        # E.g. /ys "The Weeknd Blinding Lights"
        #                       or
        #      /ys "The Weeknd Blinding Lights" 4
        elif commandslist[0] in ['/ys', '/youtube-search']:
            try:
                user_query = list(re.finditer(r'\"(.+?)"', command))
                if len(user_query):
                    query_re_obj = user_query[0]
                    qr_span = query_re_obj.span()
                    qr_val = query_re_obj.group()[1:-1].strip()
                    rescount = command[qr_span[1]:].strip()
                else: # User casually forgot to place query in double quotes..., let's assume they're there
                    qr_val = ' '.join(commandslist[1:])
                    rescount=''

                ytv_choices = None

                if rescount == '':
                    try:
                        ytv_choices = [YT_query.search_youtube(search=qr_val)]
                    except OSError:
                        err("Could not load video... (Maybe check your VPN?)",
                            "Video Load Error", say=False)
                elif rescount.isnumeric():
                    if int(rescount) == 1:
                        try:
                            ytv_choices = [YT_query.search_youtube(search=qr_val)]
                        except OSError:
                            err("Could not load video... (Maybe check your VPN?)",
                                "Video Load Error", say=False)
                    if int(rescount) in range(2, max_yt_search_results_threshold+1):
                        ytv_choices = YT_query.search_youtube(
                            search=qr_val, rescount=int(rescount))                            
                    else:
                        SAY(visible=visible,
                            log_message = 'Exceeded upper threshold for YT search result count',
                            display_message = f'YT results threshold exceeded, retry with result count <= {max_yt_search_results_threshold}',
                            log_priority = 3)

                if ytv_choices:
                    choose_media_url(media_url_choices=ytv_choices)

            except Exception:
                raise
                err("Invalid YouTube search, type: [/youtube-search | /ys] \"<search terms>\" [<result_count>]", say=False)

        elif commandslist[0].lower() in ['/yl', '/youtube-link']:
            if len(commandslist) == 2:
                media_url = commandslist[1]
                if url_is_valid(media_url):
                    try:
                        play_vas_media(media_url=media_url, single_video=True)
                    except OSError:
                        err("Could not load video... (Maybe check your VPN?)",
                            "Video Load Error", say=False)
                else:
                    SAY(visible=visible, display_message='Entered Youtube URL is invalid')
            else:
                err("Invalid YouTube-link command, too long")  # Too many args

        elif commandslist[0] in ['/al', '/audio-link']:
            if len(commandslist) == 2:
                user_aud_url = commandslist[1]
                if url_is_valid(user_aud_url, yt=False):
                    play_vas_media(media_url = commandslist[1], media_type='audio')
                else:
                    err("Invalid audio link") # Too many args
            else:
                err("Invalid audio-link command, too long") # Too many args

        elif commandslist[0] in ['/wra', '/webradio']:
            if len(commandslist) == 1: # Default station is coffee if not stated otherwise
                r_station = 'coffee'
            elif len(commandslist) == 2:
                r_station = commandslist[1].strip()

            if len(commandslist) in [1, 2]:
                r_stations = 'coffee chillout lounge'.split()

                radio_media = None
                if r_station.isnumeric():
                    if int(r_station)-1 in range(len(r_stations)):
                        r_station = r_stations[int(r_station)-1]
                        radio_media = r_station
                elif r_station in r_stations: # TODO - print these values in help...
                    radio_media = r_station

                if radio_media:
                    play_vas_media(media_url=None, media_type='radio', media_name=r_station)
                else:
                    SAY(visible=visible,
                        display_message = f'Unknown webradio station {colored.fg("navajo_white_1")}"{r_station}"{colored.fg("magenta_3a")} selected'+\
                                           '\n'+f'Choose one of the following stations ({colored.fg("navajo_white_1")}index or name{colored.fg("magenta_3a")}):',
                        log_message=f'Unknown webradio station "{r_station}" selected',
                        log_priority = 2)
                    print(tbl([(f"{colored.fg('light_red')}/wra {i+1}{colored.attr('reset')}", j) for i, j in enumerate(r_stations)], tablefmt='plain'))
            else:
                err("Unknown webradio command, too long")  # Too many args

        elif commandslist[0] in ['/rs', '/reddit-sessions']:
            # print(f'Live sessions from r/redditsessions are still in progress... The developer @{ABOUT["about"]["author"]} will add this feature shortly...')
            if r_seshs:
                global r_seshs_data
                r_seshs_data, rs_params = redditsessions.display_seshs_as_table(r_seshs)
                r_seshs_data_processed = [[i+1]+j for i,j in enumerate([list(i.values()) for i in r_seshs_data])]
                if len(commandslist) == 1:
                    r_seshs_table = tbl(r_seshs_data_processed,
                                        tablefmt='simple',
                                        headers=["#", "RPAN Session"]+[*rs_params[1:]])
                    print(r_seshs_table)
                    print()
                    sesh_index = input(f"{colored.fg('light_slate_blue')}Enter RPAN session number to tune into: {colored.fg('navajo_white_1')}")
                    print(colored.attr('reset'), end='')
                elif len(commandslist) == 2:
                    sesh_index = commandslist[1]

                if len(commandslist) <= 3:
                    print("[INFO] Reddit sessions sometimes may take ages to start and seek...")
                    if sesh_index.isnumeric():
                        sesh_index = int(sesh_index)-1
                        if sesh_index in range(len(r_seshs_data)):
                            sesh_name=r_seshs_data[sesh_index].get('title')
                            if not sesh_name: sesh_name = '[UNRESOLVED REDDIT SESSION]'
                            print(f"Tuning into RPAN: {colored.fg('indian_red_1b')}{sesh_name}{colored.attr('reset')}")
                            play_vas_media(media_url=r_seshs[sesh_index]['audiolink'],
                                        media_type='redditsession',
                                        media_name=sesh_name)
                    else:
                        if sesh_index.strip():
                            SAY(visible=visible,
                                display_message=f'You have entered an invalid RPAN session number',
                                log_message=f'Invalid RPAN session number entered',
                                log_priority=2)
                else:
                    SAY(visible=visible,
                        display_message=f'You have entered an invalid reddit session command',
                        log_message=f'Invalid reddit session command entered',
                        log_priority=2)
            else:
                if visible:
                    if loglevel in [3, 4]:
                        print("Redditsessions are unavailable because your API credentials are missing")
def mainprompt():
    while True:
        try:
            command = input(colored.bg('gold_1')+\
                            colored.fg('black')+')> '+\
                            colored.attr('reset')+\
                            colored.fg('dark_turquoise'))
            print(colored.attr('reset'), end='')
            outcode = process(command)

            if outcode == False:
                exitplayer()
                break
        except KeyboardInterrupt:
            print()


def showversion():
    global visible, ABOUT
    if visible and ABOUT:
        try:
            print(colored.fg('aquamarine_3')+\
                  f"v {ABOUT['ver']['maj']}.{ABOUT['ver']['min']}.{ABOUT['ver']['rel']}"+\
                  colored.attr('reset'))
            print()
        except Exception:
            pass


def showbanner():
    global visible
    banner_lines = []
    if visible:
        try:
            with open('about/banner.banner', encoding='utf-8') as file:
                banner_lines = file.read().splitlines()
                maxlen = len(max(banner_lines, key=len))
                if maxlen % 10 != 0:
                    maxlen = (maxlen // 10 + 1) * 10 # Smallest multiple of 10 >= maxlen,
                                                     # Since 10 is the length of cols...
                                                     # So lines will be printed with full olor range
                                                     # and would be more visually pleasing...
                banner_lines = [(x + ' ' * (maxlen - len(x))) for x in banner_lines]
                for banner_line in banner_lines:
                    IPrint.rainbow_print(banner_line, IPrint.cols+IPrint.cols[::-1])
        except IOError:
            pass

    showversion()

def run():
    global disable_OS_requirement, visible, USER_DATA

    if disable_OS_requirement and visible and sys.platform != 'win32':
        print("WARNING: OS requirement is disabled, performance may be affected on your Non Windows OS")

    USER_DATA['default_user_data']['stats']['log_ins'] += 1
    save_user_data()

    pygame.mixer.init()
    showbanner()
    mainprompt()


def startup():
    global disable_OS_requirement

    try: os.system('color 0F') # Needed?!? idk
    except Exception: pass

    try: first_startup_greet(FIRST_BOOT)
    except Exception: pass

    if not disable_OS_requirement:
        if sys.platform != 'win32':
            sys.exit('ABORTING: This program may not work on'
            'Non-Windows Operating Systems (hasn\'t been tested)')
        else: run()
    else: run()


if __name__ == '__main__':
    if FATAL_ERROR_INFO:
        print(f"FATAL ERROR ENCOUNTERED: {FATAL_ERROR_INFO}")
        print("Exiting program...")
        sys.exit(1) # End program...gracefully...
    else:
        startup()
else:
    print(' '*30, end='\r')  # Get rid of the current '\r'...

#################################################################################################################################
#
#           Mariana Player v0.5.1 dev
#     (Read help.md for help on commands)
#
#    Running the app:
#      For very first boot (SETUP):
#        Make sure you have python version < 3.10 to run this file (unless compatible llvmlite wheel bins exist...)
#     
#        QUICK-SETUP (NEW DROP-IN REPLACEMENT FOR MANUAL SETUP!)
#           Run INITSETUP.py and follow along with it's instructions (Run with "--help" flag for more info)
#          *NOTE: Don't run manual setup if you have already done a quick setup
#          *BENEFITS: Enjoy auto created ".bat" and ".ps1" runner files to automate successive runs of Mariana Player
#                                                                  |
#  +-----<--(You can skip to here after the QUICK-SETUP)---------<-+
#  |
#  |     MANUAL SETUP (Go through a tedious setup procedure)
#  |         Setup compatible architecture of VLC media player, install FFMPEG and add to path...
#  |         Install git scm if not already installed
#  v         Install given git package directly from url using: `pip install git+https://github.com/Vivojay/pafy@develop`
#  |         run `pip install -r requirements.txt`
#  |     
#  v         *OPTIONAL: Download and pip install unofficial binary for llvmlite wheel compatible with your python version
#  |         *NOTE: Specify py version < 3.10 in virtualenv (if installing optional llvmlite), as other py vers don't support llvmlite wheels :)
#  |     
#  +---> Firstly, look at help.md before running any py file
#         Run this file (main.py) on the very first bootup, nothing else (no flags, just to test bare minimum run)...
#         You are good to go...
#        *Note: If you encounter errors, look for online help as the current help file doesn't have fixes for common problems yet
#      
#      All successive boots (RUNNING NORMALLY):
#        just run this file (main.py) with desired flags (discussed in help.md)
#        and enjoy... (and possibly debug...)

# This app may take a LOT of time to load at first...
# Hence the loading prompt...

# Editor's Note: Make sure to brew a nice coffee beforehand... :)
#################################################################################################################################


# IMPORTS BEGIN #

import time
APP_BOOT_START_TIME = time.time();                  print("Loaded 1/29", end='\r')

import os;                                          print("Loaded 2/29", end='\r')
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

# import itertools;                                   print("Loaded 3/29", end='\r')

import re;                                          print("Loaded 4/29", end='\r')
import sys;                                         print("Loaded 5/29",  end='\r')
import pygame;                                      print("Loaded 6/29",  end='\r')
import numpy as np;                                 print("Loaded 7/29", end='\r')
import random as rand;                              print("Loaded 8/29", end='\r')
import importlib;                                   print("Loaded 9/29", end='\r')
import colored;                                     print("Loaded 10/29", end='\r')
import subprocess as sp;                            print("Loaded 11/29", end='\r')
import restore_default;                             print("Loaded 12/29", end='\r')
import toml;                                        print("Loaded 13/29", end='\r')
import json;                                        print("Loaded 14/29", end='\r')
import webbrowser;                                  print("Loaded 15/29", end='\r')

# import concurrent.futures;                          print("Loaded 16/29", end='\r')

from url_validate import url_is_valid;              print("Loaded 17/29",  end='\r')
from tabulate import tabulate as tbl;               print("Loaded 18/29", end='\r')
from ruamel.yaml import YAML;                       print("Loaded 19/29", end='\r')
from collections.abc import Iterable;               print("Loaded 20/29", end='\r')
from logger import SAY;                             print("Loaded 21/29", end='\r')
from multiprocessing import Process;                print("Loaded 22/29", end='\r')


online_streaming_ext_load_error = 0
comtypes_load_error = True # Unavailable due to comtypes issue #244, #180
                           # Previously: comtypes_load_error = False
lyrics_ext_load_error = 0
reddit_creds_are_valid = False


# try:
#     import librosa
#     print("Loaded 23/29",  end='\r') # Time taking import (Sometimes, takes ages...)
# except ImportError:
#     print("[WARN] Could not load music computation extension...")
#     print("[WARN] ...Skipped 23/29")

try:
    vas = importlib.import_module("beta.vlc-async-stream")
    vas = importlib.reload(vas)
    print("Loaded 24/29", end='\r')
except ImportError:
    online_streaming_ext_load_error = 1
    print("[INFO] Could not load online streaming extension...")
    print("[INFO] ...Skipped 24/29")

try:
    YT_query = importlib.import_module("beta.YT_query")
    print("Loaded 25/29", end='\r')
except ImportError:
    # raise
    if not online_streaming_ext_load_error:
        print("[INFO] Could not load online streaming extension...")
    print("[INFO] ...Skipped 25/29")

try:
    from beta.IPrint import IPrint, blue_gradient_print, loading, cols
    print("Loaded 26/29", end='\r')
except ImportError:
    lyrics_ext_load_error = 1
    print("[INFO] Could not load coloured print extension...")
    print("[INFO] ...Skipped 26/29")

try:
    from lyrics_provider import get_lyrics
    print("Loaded 27/29", end='\r')
except ImportError:
    print("[INFO] Could not load lyrics extension...")
    if not lyrics_ext_load_error:
        print("[INFO] ...Could not load online streaming extension...")
    print("[INFO] ...Skipped 27/29")

try:
    from beta import redditsessions
    if redditsessions.WARNING:
        print("[WARN] Could not load reddit-sessions extension...")
        print(f"[WARN] ...{redditsessions.WARNING}...")
        print("[WARN] ...Skipped 28/29")
    else:
        reddit_creds_are_valid = True
        print("Loaded 28/29", end='\r')
except ImportError:
    print("[INFO] Could not load reddit-sessions extension..., module 'praw' missing...")
    print("[INFO] ...Skipped 28/29")

# try:
#     from beta.master_volume_control import get_master_volume, set_master_volume
#     print("Loaded 29/29", end='\r')
# except Exception:
#     comtypes_load_error = True
#     SAY(visible=False, # global var `visible` hasn't been defined yet...
#         log_message="comtypes load failed",
#         display_message="", # ...because we don't want to display anything on screen to the user
#         log_priority=2)

# IMPORTS END #


# TODO - Replace `err` with SAY
# TODO - Rename SAY to `err` or `errlogger`...
# TODO - Add option to display type of error in display_message parameter of `SAY`
#        to print kind of log [ (debg)/(info)/(warn)/(fatl) ] ??

CURDIR = os.path.dirname(os.path.realpath(__file__))
os.chdir(CURDIR)
yaml = YAML(typ='safe')  # Allows for safe YAML loading

webbrowser.register_standard_browsers()

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
    with open('settings/system.toml', encoding='utf-8') as file:
        SYSTEM_SETTINGS = toml.load(file)
        FIRST_BOOT = SYSTEM_SETTINGS['first_boot']
except IOError:
    SYSTEM_SETTINGS = None

ISDEV = SYSTEM_SETTINGS['isdev'] # Useful as a test flag for new features

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
    global SOFT_FATAL_ERROR_INFO

    if is_first_boot:
        try:
            import first_boot_setup
            SOFT_FATAL_ERROR_INFO = first_boot_setup.fbs(about=SYSTEM_SETTINGS)
            if SOFT_FATAL_ERROR_INFO: SOFT_FATAL_ERROR_INFO = "User skipped startup"
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
APP_BOOT_END_TIME = time.time()
EXIT_INFO = 0
FATAL_ERROR_INFO = None
SOFT_FATAL_ERROR_INFO = None
HISTORY_QUEUE = []
YOUTUBE_PLAY_TYPE = None

isplaying = False
currentsong = None  # No song playing initially
ismuted = False
isshowinglyrics = False
currentsong_length = None

songindex = -1
current_media_player = 0

lyrics_window_note = "[Please close the lyrics window to continue issuing more commands...]"

"""
current_media_player can be either 0 or 1:
    0: default (pygame)
    1: vlc
"""

# Log levels from logger.py -> [Only for REF]
# logleveltypes = {0: "none", 1: "fatal", 2: "warn", 3: "info", 4: "debug"}

# From settings
disable_OS_requirement = SYSTEM_SETTINGS['system_settings']['enforce_os_requirement']

# Supported file extensions
# (For *.wav get_pos() in pygame provides played duration and not actual play position)
supported_file_types = SYSTEM_SETTINGS["system_settings"]['supported_file_types'] 
max_wait_limit_to_get_song_length = SYSTEM_SETTINGS['system_settings']['max_wait_limit_to_get_song_length']
MAX_HISTORY_SIZE = SYSTEM_SETTINGS["system_settings"]['max_hist_size']

visible = SETTINGS['visible']
loglevel = SETTINGS.get('loglevel')
DEFAULT_EDITOR = SETTINGS.get('editor path')
FALLBACK_RESULT_COUNT = SETTINGS['display items count']['general']['fallback']
max_yt_search_results_threshold = SETTINGS['display items count']['youtube-search results']['maximum']

if not loglevel:
    restore_default.restore('loglevel', SETTINGS)
    loglevel = SETTINGS.get('loglevel')

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
        SAY(visible=visible,
            log_message="Library file suddenly made unavailable",
            display_message="Library file suddenly vanished -_-",
            log_priority=2)

    # if _paths != paths: SAY(): Log <- new_dirs_added

    if not no_lib_found:
        # Use the recursive extractor function and format and store them into usable lists
        _sound_files = [[list(audio_file_gen(paths[j], supported_file_types[i]))
                        for i in range(len(supported_file_types))] for j in range(len(paths))]
        # Flattening irregularly nested sound files
        _sound_files = list(flatten(_sound_files))

        _sound_files_names_only = [os.path.splitext(os.path.split(i)[1])[0] for i in _sound_files]
        _sound_files_names_enumerated = [(i+1, j) for i, j in enumerate(_sound_files_names_only)]

reload_sounds()

if _sound_files_names_only == []:
    if loglevel in [3, 4]:
        IPrint("[INFO] All source directories are empty, you may and add more source directories to your library", visible=visible)
        IPrint("[INFO] To edit this library file (of source directories), refer to the `help.md` markdown file.", visible=visible)

with open('data/snd_files.json', 'w', encoding='utf-8') as fp:
    json.dump(_sound_files, fp)

try: _ = sp.run('ffmpeg', stdout=sp.DEVNULL, stdin=sp.PIPE, stderr=sp.DEVNULL)
except FileNotFoundError: FATAL_ERROR_INFO = "ffmpeg not recognised globally, download it and add to path (system environment)"

try: _ = sp.run('ffprobe', stdout=sp.DEVNULL, stdin=sp.PIPE, stderr=sp.DEVNULL)
except FileNotFoundError: FATAL_ERROR_INFO = "ffprobe not recognised globally, download it and add to path (system environment)"

if reddit_creds_are_valid: r_seshs = redditsessions.get_redditsessions()
else: r_seshs = None

def hist_queue_save(inf):
    """
    inf = {
        'yt_play_type': int,
        'type': int,
        'identity': (song_info_as_tuple) OR 'some/absolute/file/path',
    }
    inf is a dict of "yt_play_type" (applicable only for YT streams), "identity" and "type" of song
    "identity" is a kind of unique locater for a song. It can be a streaming url
    or the filepath of a locally streamed song (as a string)

    Songs are pushed to the HISTORY_QUEUE and when it is full
    the oldest songs are removed first to clear space for the new ones

    HISTORY_QUEUE has a fixed size (determined by settings.yml)
    (max allowed value = 10,000,000 (1 Million) items)
    """

    global HISTORY_QUEUE, MAX_HISTORY_SIZE

    if current_media_player:
        if current_media_type == 0:
            inf = [YOUTUBE_PLAY_TYPE, current_media_type, inf]
        else:
            inf = [None, current_media_type, inf]
    else:
        inf = [None, -1, inf]

    # Clear atleast 1 space for the new item
    if len(HISTORY_QUEUE) == MAX_HISTORY_SIZE:
        del HISTORY_QUEUE[0]

    # Store item in the newly cleared space
    HISTORY_QUEUE.append(inf)



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
    app_boot_time = APP_BOOT_END_TIME - APP_BOOT_START_TIME

    SAY(visible=visible,
        display_message = '',
        log_message = f'Time spent to boot app = {app_boot_time}',
        log_priority = 3)

    SAY(visible=visible,
        display_message = '',
        log_message = f'Time spent using app = {time_spent_on_app}',
        log_priority = 3)

    USER_DATA['default_user_data']['stats']['times_spent'].append(time_spent_on_app)
    save_user_data()

    IPrint(colored.fg('red')+'Exiting...'+colored.attr('reset'), visible=visible)

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
            IPrint(colored.fg('dark_olive_green_2') + \
                  f':: {_sound_files_names_only[int(_songindex)-1]}' + \
                  colored.attr('reset'), visible=visible)

            # The user is unreliable and may enter the
            # song path with weird inhumanly erratic and random
            # mix of upper and lower case characters.
            # Hence, we need to convert everything to lowercase...
            try:
                songindex = [i.lower() for i in _sound_files].index(songpath.lower())+1
            except:
                songindex = 'N/A'

            hist_queue_save((songindex, currentsong))

        else:
            IPrint(colored.fg('dark_olive_green_2') + \
                  f':: {os.path.splitext(os.path.split(songpath)[1])[0]}' + \
                  colored.attr('reset'), visible=visible)
            hist_queue_save(currentsong)


        if not currentsong_length and currentsong_length != -1:
            get_currentsong_length()
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
                IPrint("|| Paused", visible=visible)
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
                IPrint("|> Resumed", visible=visible)
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
        purge_old_lyrics_if_exist()
    except Exception:
        IPrint(f'Failed to stop: {currentsong}', visible=visible)


def err(error_topic='', message='', say=True):
    global visible
    IPrint(colored.fg('red')+f'x| ERROR {error_topic}'+colored.attr('reset'), visible=visible)
    if message:
        IPrint(colored.fg('red')+'x|  '+message+colored.attr('reset'), visible=visible)

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
    print(f'Enqueuing feature is still in progress... The developer @{SYSTEM_SETTINGS["about"]["author"]} will add this feature shortly...')
    # IPrint("Enqueueing", visible=visible)
    # global song_paths_to_enqueue

    # song_paths_to_enqueue = []

    # for songindex in songindices:
    #     song_paths_to_enqueue.append(_sound_files[int(songindex)-1])

    # for songpath in song_paths_to_enqueue:
    #     try:
    #         pygame.mixer.music.queue(songpath)
    #         IPrint("Queued", visible=visible)
    #         if isplaying:
    #             pygame.mixer.music.unpause()
    #     except Exception:
    #         err("Queueing error", "Could not enqueue one or more files")
    #         raise

def purge_old_lyrics_if_exist():
    lyrics_file_path = 'temp/lyrics.txt'
    try:
        if os.path.isfile(lyrics_file_path):
            os.remove(lyrics_file_path)
    except Exception:
        raise

def local_play_commands(commandslist, _command=False):
    global cached_volume, currentsong_length
    pygame.mixer.music.set_volume(cached_volume)

    purge_old_lyrics_if_exist()

    if not _command:
        if len(commandslist) == 2:
            songindex = commandslist[1]
            if songindex.isnumeric():
                if int(songindex) in range(1, len(_sound_files)+1):
                    currentsong_length = None
                    play_local_default_player(_sound_files[int(songindex)-1],
                                              _songindex=songindex)
                else:
                    if any(_sound_files):
                        SAY(visible=visible,
                            log_message='Out of bound song index',
                            display_message=f'Song number {songindex} does not exist. Please input song number between 1 and {len(_sound_files)}',
                            log_priority=3)

                    else:
                        SAY(visible=visible,
                            log_message='User attempted to play local song, even though there are no songs in library',
                            display_message='There are no songs in library',
                            log_priority=2)

        else:
            # TODO - Implement full queue functionality
            # as per `future ideas{...}.md`
            # Not yet implemented
            # This is just a sekeleton code for future

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
            if not currentsong_length and not currentsong_length == -1:
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

    if comtypes_load_error:
        SAY(visible=visible,
            log_message="comtypes functionality used even when not available",
            display_message="This functionality is unavailable",
            log_priority=3)
    else:
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


def rand_song_index_generate():
    global _sound_files_names_only
    if len(_sound_files) == 0:
        SAY(visible=visible,
        log_message='User attempted to play local song, even though there are no songs in library',
        display_message='There are no songs in library',
        log_priority=2)
        return None
    else:
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

    global isplaying, current_media_player, visible, currentsong, cached_volume
    global currentsong_length, current_media_type

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
                    log_message = f'video name could not be resolved for:: {currentsong[1]}',
                    log_priority = 2)

        currentsong = (media_name, media_url, YT_aud_url)
        hist_queue_save(currentsong)

        if print_now_playing and visible:
            if single_video:
                IPrint(f"Playing YouTube search result:: {colored.fg('plum_1')}{media_name}{colored.attr('reset')}", visible=visible)
            else:
                IPrint(f"Chosen YouTube video:: {colored.fg('plum_1')}{media_name}{colored.attr('reset')}", visible=visible)
            IPrint(f"{colored.fg('light_red')}@ {colored.fg('orange_1')}{media_url}{colored.attr('reset')}", visible=visible)

    elif media_type == 'audio':
        vas.set_media(_type='audio', audurl=media_url)

        current_media_type = 1
        currentsong = media_url
        hist_queue_save(currentsong)
        IPrint(f"Chosen custom audio url:: {text_overflow_prettify(media_url)}", visible=visible)

    elif media_type == 'radio':
        # Here `media_name` is actually the radio name
        vas.set_media(_type=f'radio/{media_name}') # No need for an explicit `audurl` here... (as per definition of vas.set_media)

        current_media_type = 2
        currentsong = media_name
        hist_queue_save(currentsong)
        IPrint(f"Chosen radio: {colored.fg('light_goldenrod_1')}{currentsong}{colored.attr('reset')}", visible=visible)

    elif media_type == 'redditsession':
        vas.set_media(_type='audio', audurl=media_url)

        current_media_type = 3
        currentsong = (media_name, media_url)
        hist_queue_save(currentsong)

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

    if current_media_type == 2:
        currentsong_length = -1
    else:
        IPrint("Attempting to calculate song length")
        length_find_start_time = time.time()
        while True:
            if vas.vlc_media_player.get_media_player().get_length():
                currentsong_length = vas.vlc_media_player.get_media_player().get_length()/1000
                break
            if time.time() - length_find_start_time >= max_wait_limit_to_get_song_length:
                currentsong_length = -1
                break
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
                    if visible:
                        print("ERROR: Invalid choice, choose again: ", end='\r')

                if chosen_index in range(1, len(media_url_choices)+1):
                    _, media_name, media_url = media_url_choices[chosen_index-1]
                    play_vas_media(media_name=media_name, media_url=media_url,
                                   single_video=False)
                else:
                    if visible:
                        print("ERROR: Invalid choice, choose again: ", end='\r')

                if visible: IPrint('\n', visible=visible)

def refresh_settings():
    global SYSTEM_SETTINGS, visible, supported_file_types, disable_OS_requirement, max_yt_search_results_threshold
    global max_wait_limit_to_get_song_length, FALLBACK_RESULT_COUNT, DEFAULT_EDITOR, MAX_HISTORY_SIZE

    try:
        with open('settings/system.toml', encoding='utf-8') as file:
            SYSTEM_SETTINGS = toml.load(file)
    except IOError:
        SYSTEM_SETTINGS = None

    try:
        with open('settings/settings.yml', encoding='utf-8') as u_data_file:
            SETTINGS = yaml.load(u_data_file)

    except IOError:
        SAY(visible=visible,
            display_message = f'Encountered missing program file @{os.path.join(CURDIR, "settings/settings.yml")}',
            log_message = 'Aborting player because settings file was not found',
            log_priority = 1) # Log fatal crash
        sys.exit(1) # Fatal crash

    # Supported file extensions
    # (wav get_pos() in pygame provides played duration and not actual play position)
    supported_file_types = SYSTEM_SETTINGS["system_settings"]['supported_file_types'] 
    max_wait_limit_to_get_song_length = SYSTEM_SETTINGS['system_settings']['max_wait_limit_to_get_song_length']
    MAX_HISTORY_SIZE = SYSTEM_SETTINGS["system_settings"]['max_hist_size']

    visible = SETTINGS['visible']
    loglevel = SETTINGS.get('loglevel')
    DEFAULT_EDITOR = SETTINGS.get('editor path')
    FALLBACK_RESULT_COUNT = SETTINGS['display items count']['general']['fallback']
    max_yt_search_results_threshold = SETTINGS['display items count']['youtube-search results']['maximum']

    if not loglevel:
        restore_default.restore('loglevel', SETTINGS)
        loglevel = SETTINGS.get('loglevel')

def reload_reddit_creds():
    global r_seshs

    try:
        from beta import redditsessions
        importlib.reload(redditsessions)

        if redditsessions.WARNING:
            if loglevel in [3, 4]:
                IPrint("[WARN] Could not load reddit-sessions extension...", visible=visible)
                IPrint(f"[WARN] ...{redditsessions.WARNING}...", visible=visible)
            reddit_creds_are_valid = False
        else:
            reddit_creds_are_valid = True
    except ImportError:
        if loglevel in [3, 4]:
            IPrint("[INFO] Could not load reddit-sessions extension..., module 'praw' missing...", visible=visible)

    if reddit_creds_are_valid: r_seshs = redditsessions.get_redditsessions()
    else: r_seshs = None

def text_overflow_prettify(url):
	if len(url) > 100:
		return f"{url[:92]}...{url[-5:]}"
	else:
		return url

def get_prettified_history(indices):
    global HISTORY_QUEUE

    results = [] # prettified results (formatted as WYSIWYG)

    # results = [HISTORY_QUEUE[::-1][index] for index in indices]
    for index in indices:
        result= HISTORY_QUEUE[::-1][index]
        yt_play_type, media_player, inf = result

        if media_player == -1:
            cur_song = inf[1]
            cur_song = os.path.splitext(os.path.split(cur_song)[1])[0]
            result = f":: {colored.fg('plum_1')}{inf[0]}{colored.attr('reset')} | {cur_song}"

        elif media_player == 0:
            yt_prefix = ["@yl", "@ys"][yt_play_type]
            result = (f"{colored.fg('red')}{yt_prefix}: {colored.fg('aquamarine_3')}Title | {inf[0]}\n"
                      f"     {colored.fg('navajo_white_1')}Link  | {inf[1]}{colored.attr('reset')}")

        elif media_player == 1:
            result = f"{colored.fg('hot_pink_1a')}@audio-link: {colored.fg('aquamarine_3')}{text_overflow_prettify(inf)}{colored.attr('reset')}"

        elif media_player == 2:
            result = f"{colored.fg('light_slate_blue')}@webradio/{colored.fg('navajo_white_1')}{inf}{colored.attr('reset')}"

        elif media_player == 3:
            result = (f"{colored.fg('orange_1')}@rs: {colored.fg('aquamarine_3')}Session | {text_overflow_prettify(inf[0])}{colored.attr('reset')}\n"
                      f"     {colored.fg('navajo_white_1')}Link    | {text_overflow_prettify(inf[1])}{colored.attr('reset')}")

        results.append(result)

    return results

def lyrics_ops(show_window):
    get_related = SETTINGS['get related songs']
    if current_media_player: # FIXME: Broken
        if current_media_type == 0:
            IPrint(f"Loading lyrics window for (Time taking)...", visible=visible)
            get_lyrics.show_window(max_wait_lim = max_wait_limit_to_get_song_length, get_related=get_related, show_window=show_window, weblink=currentsong[1], isYT=1)
        elif current_media_type == 1:
            IPrint(f"Loading lyrics window for (Time taking)...", visible=visible)
            get_lyrics.show_window(max_wait_lim = max_wait_limit_to_get_song_length,  get_related=get_related, show_window=show_window, weblink=currentsong)
        elif current_media_type == 2:
            IPrint(f"Lyrics for Radio are not supported", visible=visible)
        elif current_media_type == 3:
            IPrint(f"Lyrics for reddit sessions are not supported", visible=visible)
    else:
        if currentsong:
            if os.path.isfile(currentsong):
                if show_window:
                    IPrint(lyrics_window_note, visible=visible)
                get_lyrics.show_window(max_wait_lim = max_wait_limit_to_get_song_length, get_related=get_related, show_window=show_window, songfile=currentsong)

def process(command):
    global _sound_files_names_only, visible, currentsong, isplaying, ismuted, cached_volume
    global current_media_player, current_media_type, DEFAULT_EDITOR, YOUTUBE_PLAY_TYPE

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
            if visible:
                results_enum = enumerate(_sound_files_names_only)
                IPrint(tbl([(i+1, j) for i, j in results_enum], tablefmt='plain'), visible=visible)
            else:
                SAY(visible=True,
                display_message="Turn on visibility to access this command",
                log_message="Accessing all command with visibility switched off",
                priority=3)

        # TODO: Need to display files in n columns (Mostly 3 cols) depending upon terminal size (dynamically...)
        if commandslist[0] in ['list', 'ls']:

            if len(_sound_files) != 0:
                # TODO: Get values for `order_results` and `order_type` from SETTINGS
                indices = [] # Indices of songs to be displayed
                rescount = FALLBACK_RESULT_COUNT
                order_results = False
                order_type = 1 # Default value (1): Display in ascending order

                if 'o' in commandslist[1:]:
                    order_results = True
                if 'desc' in commandslist[1:]:
                    order_type = 0

                range_command_is_valid = True
                if '-' in command:

                    _command = command.replace('o', '').replace('desc', '')
                    _command = _command.strip().lstrip(commandslist[0]).split('-')

                    if len(_command) == 2:
                        try:
                            ls_x_to_y = list(map(lambda i:int(i.strip()), _command))
                            ls_x_to_y[0] -= 1
                            if ls_x_to_y[0] < ls_x_to_y[1]:
                                indices = list(range(*ls_x_to_y))
                            else:
                                SAY(visible=visible,
                                    display_message = 'Range order is reversed. It should be lower to upper',
                                    log_message = 'Invalid order of bounds for listing range of songs',
                                    log_priority = 2)
                                range_command_is_valid = False
                        except Exception:
                            SAY(visible=visible,
                                display_message = 'Invalid bounds for listing range of songs',
                                log_message = 'Invalid bounds for listing range of songs',
                                log_priority = 2)
                            range_command_is_valid = False
                    else:
                        SAY(visible=visible,
                            display_message = 'Invalid command for listing a range of songs',
                            log_message = 'Invalid command for listing a range of songs',
                            log_priority = 2)
                        range_command_is_valid = False
                else:
                    _commandslist = commandslist.copy()

                    if 'o' in commandslist: _commandslist.remove('o')
                    if 'desc' in commandslist: _commandslist.remove('desc')
                    if len([i for i in commandslist if i.isnumeric()]) == 1:
                        if commandslist[1].isnumeric():
                            rescount = int(commandslist[1])
                    else:
                        for i in commandslist[1:]:
                            if i.isnumeric():
                                if int(i)-1 not in indices:
                                    indices.append(int(i)-1)


                if indices:
                    results = [_sound_files_names_only[index] for index in indices]
                    results_enum = list(zip(indices, results))
                    if order_results:
                        results_enum = sorted(results_enum, key = lambda x: x[0], reverse = not order_type)

                if len([i for i in commandslist if i.isnumeric()]) == 0 and '-' not in command and len(commandslist) != 1:
                    # List files matching provided regex pattern
                    # Need to implement a check to validate the provided regex pattern
                    print(f'Regex search is still in progress... The developer @{SYSTEM_SETTINGS["about"]["author"]} will add this feature shortly...')
                    # regex_pattern
                    # regexp = re.compile(regex_pattern)

                else:
                    if len([i for i in commandslist if i.isnumeric()]) in [0, 1] and '-' not in command:
                        results_enum = list(enumerate(_sound_files_names_only[:rescount]))
                        if order_results:
                            results_enum = sorted(results_enum, key = lambda x: x[0], reverse = not order_type)

                    if indices or len([i for i in commandslist if i.isnumeric()]) in [0, 1]:
                        if range_command_is_valid:
                            IPrint(tbl([(i+1, j) for i, j in results_enum], tablefmt='plain'), visible=visible)


            else:
                SAY(visible=visible,
                    log_message='User attempted to play local song, even though there are no songs in library',
                    display_message='There are no songs in library',
                    log_priority=2)

        elif commandslist == ['last']:
            last_index, last_name = _sound_files_names_enumerated
            IPrint(">| ", visible=visible)

        elif commandslist[0] in ['hist', 'history']:
            # TODO: Get values for `order_results` and `order_type` from SETTINGS
            indices = [] # Indices of songs to be displayed
            rescount = FALLBACK_RESULT_COUNT
            order_results = False
            order_type = 1 # Default value (1): Display in ascending order

            if 'o' in commandslist[1:]:
                order_results = True
            if 'desc' in commandslist[1:]:
                order_type = 0

            range_command_is_valid = True
            if '-' in command:

                _command = command.replace('o', '').replace('desc', '')
                _command = _command.strip().lstrip(commandslist[0]).split('-')

                if len(_command) == 2:
                    try:
                        hist_x_to_y = list(map(lambda i:int(i.strip()), _command))
                        hist_x_to_y[0] -= 1
                        if hist_x_to_y[0] < hist_x_to_y[1]:
                            indices = list(range(*hist_x_to_y))
                        else:
                            SAY(visible=visible,
                                display_message = 'Range order is reversed. It should be lower to upper',
                                log_message = 'Invalid order of bounds for listing range of history',
                                log_priority = 2)
                            range_command_is_valid = False
                    except Exception:
                        SAY(visible=visible,
                            display_message = 'Invalid bounds for listing history range',
                            log_message = 'Invalid bounds for listing range of history',
                            log_priority = 2)
                        range_command_is_valid = False
                else:
                    SAY(visible=visible,
                        display_message = 'Invalid command for listing history range',
                        log_message = 'Invalid command for listing a range of history',
                        log_priority = 2)
                    range_command_is_valid = False
            else:
                _commandslist = commandslist.copy()

                if 'o' in commandslist: _commandslist.remove('o')
                if 'desc' in commandslist: _commandslist.remove('desc')
                if len([i for i in commandslist if i.isnumeric()]) == 1:
                    if commandslist[1].isnumeric():
                        rescount = int(commandslist[1])
                else:
                    for i in commandslist[1:]:
                        if i.isnumeric():
                            if int(i)-1 not in indices:
                                indices.append(int(i)-1)


            if indices:
                results = get_prettified_history(indices)
                results_enum = list(zip(indices, results))

                if order_results:
                    results_enum = sorted(results_enum, key = lambda x: x[0], reverse = not order_type)

            if len([i for i in commandslist if i.isnumeric()]) == 0 and '-' not in command and len(commandslist) != 1:
                # List files matching provided regex pattern
                # Need to implement a check to validate the provided regex pattern
                print(f'Regex search is still in progress... The developer @{SYSTEM_SETTINGS["about"]["author"]} will add this feature shortly...')
                # regex_pattern
                # regexp = re.compile(regex_pattern)

            else:
                if len([i for i in commandslist if i.isnumeric()]) in [0, 1] and '-' not in command:
                    if rescount > len(HISTORY_QUEUE):
                        rescount = len(HISTORY_QUEUE)
                    results = get_prettified_history(list(range(rescount)))
                    results_enum = list(enumerate(results))
                    if order_results:
                        results_enum = sorted(results_enum, key = lambda x: x[0], reverse = not order_type)

                if indices or len([i for i in commandslist if i.isnumeric()]) in [0, 1]:
                    if range_command_is_valid:
                        IPrint(tbl([(-(i+1), j) for i, j in results_enum], tablefmt='plain'), visible=visible)

        elif commandslist == ['last', 'played']:
            if HISTORY_QUEUE:
                if currentsong and len(HISTORY_QUEUE) >= 2:
                    IPrint(f"<:: {colored.fg('navajo_white_1')}{HISTORY_QUEUE[-2]}{colored.attr('reset')}", visible=visible)
                else:
                    IPrint(f"<:: {colored.fg('navajo_white_1')}{HISTORY_QUEUE[-1]}{colored.attr('reset')}", visible=visible)
            else:
                SAY(visible=visible,
                    display_message='No history recorded yet for the current session',
                    log_message='No history to display',
                    log_priority=2)

        elif commandslist == ['reload']:
            IPrint("Reloading sounds", visible=visible)
            reload_sounds()
            IPrint("Done...", visible=visible)
        
        elif commandslist == ['refresh']:
            IPrint("Reloading sounds", visible=visible)
            reload_sounds()
            IPrint("Reloading settings", visible=visible)
            refresh_settings()
            IPrint("Done...", visible=visible)

        elif commandslist == ['vis']:
            visible = not visible
            IPrint('visibility on', visible=visible)

        elif commandslist[0] in ['prev', 'next', '.prev', '.next']:
            if not current_media_player: # default player currently active
                offset = None
                if songindex not in ['N/A', -1]:
                    if len(commandslist) == 1: # default to 1 song skip
                        offset = 1
                    elif len(commandslist) > 1:
                        if commandslist[1].isnumeric():
                            if int(commandslist[1]) != 0:
                                # number of songs to be skipped is provided by the user
                                # store offset as either +ve for fwd skip (next)
                                # or                     -ve for bwd seeks (prev)
                                offset = int(commandslist[1])
                            else:
                                SAY(visible=visible,
                                    display_message = 'Provided 0 songs to skip. Not allowed',
                                    log_message = 'Number of songs to skip was 0',
                                    log_priority = 2)
                        else:
                            SAY(visible=visible,
                                display_message = 'Number of songs to skip must be a positives integer',
                                log_message = 'Number of songs to skip wasn not a valid +ve int',
                                log_priority = 2)

                    if offset:
                        if commandslist[0] in ['prev', '.prev']: offset *= -1
                        offsetted_index = songindex + offset
                        if offsetted_index in range(1, len(_sound_files)+1): # is song found at offsetted index?
                            if commandslist[0][0] == '.':
                                local_play_commands(commandslist=[None, str(offsetted_index)])
                            else:
                                IPrint(f"@{commandslist[0][0]} {colored.fg('light_red')}{offsetted_index}{colored.fg('aquamarine_3')} | {_sound_files_names_only[offsetted_index-1]}{colored.attr('reset')}", visible=visible)
                        else:
                            if offset > 0:
                                if offsetted_index == 1:
                                    offset_err_disp_msg = 'Cannot skip backward as you have reached beginning of library'
                                    offset_err_log_msg = 'Reached beginning of library, cannot skip bwd'
                                else:
                                    offset_err_disp_msg = f'Number of songs to skip forward was too large, try "next" command with <= {len(_sound_files)-songindex} skips'
                                    offset_err_log_msg = 'Reached upper bound of index in library when skipping fwd'
                            else:
                                if offsetted_index == len(_sound_files_names_only):
                                    offset_err_disp_msg = 'Cannot skip forward as you have reached end of library'
                                    offset_err_log_msg = 'Reached end of library, cannot skip fwd'
                                else:
                                    offset_err_disp_msg = f'Number of songs to skip backward was too large, try "prev" command with <= {songindex} skips'
                                    offset_err_log_msg = 'Reached index 0 in library when skipping bwd'

                            SAY(visible=visible,
                                display_message = offset_err_disp_msg,
                                log_message = offset_err_log_msg,
                                log_priority = 2)
                else:
                    if songindex == -1:
                        SAY(visible=visible,
                            display_message = 'Cannot skip. No song is currently playing',
                            log_message = 'Cannot skip when no song is playing',
                            log_priority = 2)
                    if songindex == 'N/A':
                        SAY(visible=visible,
                            display_message = 'Cannot skip songs when playing individual song files outside of your music library',
                            log_message = 'Cannot skip when playing explicit filepaths outside library',
                            log_priority = 2)

        elif commandslist == ['now']:
            if currentsong:
                if current_media_player: # VLC
                    if current_media_type == 0:
                        if YOUTUBE_PLAY_TYPE == 0:
                            IPrint(f"@yl: {currentsong[0]}", visible=visible)
                        elif YOUTUBE_PLAY_TYPE == 1:
                            IPrint(f"@ys: {currentsong[0]}", visible=visible)
                    elif current_media_type == 1:
                        IPrint(f"@al: {currentsong}", visible=visible)
                    elif current_media_type == 2:
                        IPrint(f"@wra: {currentsong}", visible=visible)
                    elif current_media_type == 3:
                        IPrint(f"@rs: {currentsong[0]}", visible=visible)
                else: # pygame
                    cur_song = os.path.splitext(os.path.split(currentsong)[1])[0]
                    IPrint(f":: {colored.fg('plum_1')}{songindex}{colored.fg('deep_pink_4c')} | {colored.fg('navajo_white_1')}{cur_song}{colored.attr('reset')}", visible=visible)
            else:
                # currentsong = None
                IPrint(f"{colored.fg('red')}({colored.attr('reset')}Not Playing{colored.fg('red')}){colored.attr('reset')}", visible=visible)

        elif commandslist == ['now*']:
            if currentsong:
                if current_media_player: # VLC
                    if current_media_type == 0:
                        if YOUTUBE_PLAY_TYPE == 0:
                            IPrint(f"{colored.fg('red')}@youtube-link: {colored.fg('aquamarine_3')}Title | {currentsong[0]}", visible=visible)
                            IPrint(f"               {colored.fg('navajo_white_1')}Link  | {currentsong[1]}{colored.attr('reset')}", visible=visible)
                        elif YOUTUBE_PLAY_TYPE == 1:
                            IPrint(f"{colored.fg('red')}@youtube-search: {colored.fg('aquamarine_3')}Title | {currentsong[0]}", visible=visible)
                            IPrint(f"                 {colored.fg('navajo_white_1')}Link  | {currentsong[1]}{colored.attr('reset')}", visible=visible)
                    elif current_media_type == 1:
                        IPrint(f"{colored.fg('hot_pink_1a')}@audio-link: {colored.fg('aquamarine_3')}{currentsong}{colored.attr('reset')}", visible=visible)
                    elif current_media_type == 2:
                        IPrint(f"{colored.fg('light_slate_blue')}@webradio/{colored.fg('navajo_white_1')}{currentsong}{colored.attr('reset')}", visible=visible)
                    elif current_media_type == 3:
                        IPrint(f"{colored.fg('orange_1')}@redditsession: {colored.fg('aquamarine_3')}Session | {currentsong[0]}{colored.attr('reset')}", visible=visible)
                        IPrint(f"                {colored.fg('navajo_white_1')}Link    | {currentsong[1]}{colored.attr('reset')}", visible=visible)

                else: # pygame # TODO - Change to VLC or Local or Default
                    IPrint(f":: {colored.fg('plum_1')}{songindex}{colored.attr('reset')} | {currentsong}", visible=visible)

            else:
                currentsong = None
                IPrint(f"{colored.fg('red')}({colored.attr('reset')}Not Playing{colored.fg('red')}){colored.attr('reset')}", visible=visible)

        elif commandslist[0].lower() == 'play':
            local_play_commands(commandslist=commandslist)

        elif commandslist[0].lower() in ['m?', 'ism?', 'ismute?']:
            # TODO - Make more reliable...?
            IPrint(int(ismuted), visible=visible)

        elif commandslist[0].lower() in ['isp?', 'ispl', 'isp']:
            SAY(visible=visible,
                display_message='/? Invalid command, perhaps you meant "ispl?" for "is playing?"',
                log_message=f'"ispl[aying]?" command assumed to be misspelled',
                log_priority=3)

        elif commandslist[0].lower() in ['ispl?', 'isplaying?']:
            # TODO - Make more reliable...?
            IPrint(int(isplaying), visible=visible)

        elif commandslist[0].lower() in ['isl?', 'isloaded?']:
            # TODO - Make more reliable...?
            if current_media_player:
                IPrint(vas.vlc.media, visible=visible)
            IPrint(int(bool(currentsong)), visible=visible)

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
                                    IPrint(f"Seeking to: {timeobj[0]}", visible=visible)

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
                if currentsong_length == -1:
                    SAY(visible=visible,
                        display_message="Error: Can't seek song, as song length could not be loaded",
                        log_message=f'Song length could not be loaded, cannot seek',
                        log_priority=2)
                else:
                    SAY(visible=visible,
                        display_message="Error: No song to seek",
                        log_message=f'Seeked song w/o playing any',
                        log_priority=2)

        elif commandslist in [['prog'], ['progress'], ['prog*'], ['progress*']]:
            if currentsong:
                if currentsong_length:
                    cur_len = currentsong_length
                else:
                    cur_len = get_currentsong_length()

                if cur_len != -1:
                    cur_prog = get_current_progress()

                    prog_sep = f"{colored.fg('green_1')}|{colored.attr('reset')}"
                    prog_div = f"{colored.fg('navajo_white_1')}\u2014{colored.attr('reset')}"

                    if commandslist[0].endswith('*'):
                        IPrint(f"elapsed: {colored.fg('deep_pink_1a')}{convert(round(cur_prog))} {prog_div} {colored.fg('deep_pink_1a')}{convert(round(cur_len))}"
                               f" {prog_sep} {colored.attr('reset')}remaining: {colored.fg('orange_1')}{convert(round(cur_len-cur_prog))}"
                               f" {prog_sep} {colored.attr('reset')}progress: {colored.fg('light_goldenrod_1')}{round(cur_prog/cur_len*100)}%", visible=visible)
                    else:
                        # IPrint(f"{colored.fg('deep_pink_1a')}{convert(round(cur_prog))}/{convert(round(cur_len))}", visible=visible)
                        IPrint(f"{colored.fg('deep_pink_1a')}{round(cur_prog)} {prog_div} {colored.fg('deep_pink_1a')}{round(cur_len)}"
                               f" {prog_sep} {colored.fg('orange_1')}{round(cur_len-cur_prog)}"
                               f" {prog_sep} {colored.fg('light_goldenrod_1')}{round(cur_prog/cur_len*100)}%", visible=visible)

                else:
                    SAY(visible=visible,
                        display_message = f'Progress cannot be displayed for song of unknown length',
                        log_message = 'Progress undefined for song of unknown length',
                        log_priority = 2) # Log fatal crash

        elif commandslist[0].lower() in ['download',  'download-yt',  'download-au',  'download-a',
                                         '/download', '/download-yt', '/download-au', '/download-a']:
            SAY(visible=visible,
                display_message=f'/? Invalid command, perhaps you meant one of:\n'
                f'  {colored.fg("magenta_3a")}download-yv:{colored.fg("light_sky_blue_1")} Download YouTube video\n'
                f'  {colored.fg("magenta_3a")}download-ya:{colored.fg("light_sky_blue_1")} Download YouTube audio\n'
                f'  {colored.fg("magenta_3a")}download-al:{colored.fg("light_sky_blue_1")} Download custom audio link'
                f'{colored.attr("reset")}\n',
                log_message=f'"download-(\'ys\'|\'yv\'|\'al\')" command assumed to be misspelled', log_priority=3)

        # Download current/custom YouTube media (as video with audio)
        elif commandslist[0].lower() == 'download-yv':
            # TODO - Add way for user to customize download settings...
            continue_dl = False
            confirm_dl = False

            if current_media_player == 0:
                SAY(visible=visible,
                    log_message='Cannot download locally available songs',
                    display_message='Whoops! Looks like you\'re trying to download a song already present in your hard drive',
                    log_priority = 3)

            if len(commandslist) == 1 and current_media_player == 1:
                if currentsong is not None:
                    url = currentsong[1]
                    continue_dl = True
                else:
                    url = None
                    IPrint("No song currently playing", visible=visible)

            elif len(commandslist) == 2 and current_media_player == 1:
                url = commandslist[1]
                if url_is_valid(url = url, yt=True):
                    IPrint('Attempting to download YouTube video from:\n  '
                          f'{colored.fg("sandy_brown")}@ {colored.fg("orchid_2")}{url}{colored.attr("reset")}',
                          visible=visible)
                    continue_dl = True
                else:
                    SAY(visible=visible,
                        log_message=f'Invalid YouTube URL for video download: {url}',
						display_message=f'Invalid YouTube URL for video download: {url}',
						log_priority = 3)

            if len(commandslist) in [1, 2] and url:
                download_parmeters = {
                    "SETTINGS": SETTINGS,
                    "SYSTEM_SETTINGS": SYSTEM_SETTINGS,
                    "media_urls": url,
                    "typ": 1,
                    "quality": None,
                    "make_separate_mariana_dl_dir": None,
                    "dry_run": False,
                }

                if continue_dl:
                    confirm_dl = input("Do you want to confirm VIDEO download? (y/n): ").lower().strip()
                    while confirm_dl not in ['y', 'n', 'yes', 'no']:
                        confirm_dl = input("[INVALID RESPONSE] Do you want to confirm VIDEO download? (y/n): ").lower().strip()

                    if confirm_dl in ['yes', 'y']:
                        confirm_dl = True
                    else:
                        confirm_dl = False
                
                if confirm_dl:
                    SAY(visible=visible,
                        log_message='Download confirmed and initiated',
                        display_message='Your download has started',
                        log_priority = 3)
                    sp.Popen(['py', 'beta/mediadl.py', json.dumps(download_parmeters)], shell=True)

        elif commandslist[0].lower() == 'download-ya':
            # TODO - Add way for user to customize download settings...
            continue_dl = False
            confirm_dl = False

            if current_media_player == 0:
                SAY(visible=visible,
                    log_message='Cannot download locally available songs',
                    display_message='Whoops! Looks like you\'re trying to download a song already present in your hard drive',
                    log_priority = 3)

            if len(commandslist) == 1 and current_media_player == 1:
                if currentsong is not None:
                    url = currentsong[1]
                    continue_dl = True
                else:
                    url = None
                    IPrint("No song currently playing", visible=visible)

            elif len(commandslist) == 2 and current_media_player == 1:
                url = commandslist[1]
                if url_is_valid(yt=True):
                    IPrint('Attempting to download YouTube audio from:\n  '
                          f'{colored.fg("sandy_brown")}@ {colored.fg("orchid_2")}{url}{colored.attr("reset")}',
                          visible=visible)
                    continue_dl = True
                else:
                    SAY(visible=visible,
                        log_message=f'Invalid YouTube URL for audio download: {url}',
						display_message=f'Invalid YouTube URL for video download: {url}',
						log_priority = 3)

            if len(commandslist) in [1, 2] and url:
                download_parmeters = {
                    "SETTINGS": SETTINGS,
                    "SYSTEM_SETTINGS": SYSTEM_SETTINGS,
                    "media_urls": url,
                    "typ": 0,
                    "quality": None,
                    "make_separate_mariana_dl_dir": None,
                    "dry_run": False,
                }

                if continue_dl:
                    confirm_dl = input("Do you want to confirm AUDIO download? (y/n): ").lower().strip()
                    while confirm_dl not in ['y', 'n', 'yes', 'no']:
                        confirm_dl = input("[INVALID RESPONSE] Do you want to confirm AUDIO download? (y/n): ").lower().strip()

                    if confirm_dl in ['yes', 'y']:
                        confirm_dl = True
                    else:
                        confirm_dl = False
                
                if confirm_dl:
                    SAY(visible=visible,
                        log_message='Download confirmed and initiated',
                        display_message='Your download has started',
                        log_priority = 3)
                    sp.Popen(['py', 'beta/mediadl.py', json.dumps(download_parmeters)], shell=True)


        elif commandslist == ['t']:
            IPrint(convert(get_current_progress()), visible=visible)

        # TODO - Add following command and interctive helps
        # with syntax ?<command-name> ...
        # elif commandslist == ['? rand']:  # Random comand help
        #     IPrint("", visible=visible)

        elif commandslist == ['.rand']:  # Play random song
            rand_song_index = rand_song_index_generate()
            if rand_song_index:
                local_play_commands(commandslist=[None, str(rand_song_index)])

        elif commandslist == ['=rand']:  # Print random song number
            rand_song_index = rand_song_index_generate()
            if rand_song_index:
                IPrint(rand_song_index, visible=visible)

        elif commandslist == ['rand']:  # Print random song name
            rand_song_index = rand_song_index_generate()
            if rand_song_index:
                IPrint(_sound_files_names_only[rand_song_index], visible=visible)

        elif commandslist == ['rand*']:  # Print random song path
            rand_song_index = rand_song_index_generate()
            if rand_song_index:
                IPrint(_sound_files[rand_song_index], visible=visible)

        elif commandslist == ['/rand']:  # Print random song number+name
            rand_song_index = rand_song_index_generate()
            if rand_song_index:
                IPrint(f"{rand_song_index+1}: {_sound_files_names_only[rand_song_index]}", visible=visible)

        elif commandslist == ['reset']:
            if currentsong_length and currentsong_length != -1:
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
                        local_play_commands(commandslist=[None, ''.join(commandslist[0][1:])])

                if all([not i.replace(' ', '').isnumeric() for i in command.split('.')]): # Identifying a file-existence-check command
                    if len(command.split('.')) == 3:
                        if command.startswith('. '):
                            path = ' '.join(commandslist[1:])
                            if os.path.isfile(path):
                                if os.path.splitext(path)[1] in supported_file_types:
                                    IPrint(1, visible=visible)
                                else:
                                    IPrint(0, visible=visible)
                            else:
                                IPrint(0, visible=visible)
                        elif command.startswith('.'):
                            local_play_commands(commandslist=[None, command[1:]],
                                          _command=command)

            except Exception:
                raise

        elif commandslist in [['clear'], ['cls']]:
            os.system('cls' if os.name == 'nt' else 'clear')
            if visible: showbanner()

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
                        IPrint(colored.fg('medium_orchid_1a')+\
                              _sound_files_names_only[int(commandslist[0])-1]+\
                              colored.attr('reset'), visible=visible)
                    except IndexError:
                        err('', f'Please input song number between 1 and {len(_sound_files)}')
                else:
                    err('', f'Please input song number between 1 and {len(_sound_files)}')

        elif commandslist in [['count'], ['howmany'], ['total']]:
            IPrint(len(_sound_files_names_only), visible=visible)

        elif commandslist[0] == 'weblinks':
            print(f'Weblinks feature is still in progress... The developer @{SYSTEM_SETTINGS["about"]["author"]} will add this feature shortly...')

        if commandslist[0] == 'open':
            if commandslist == ['open']:
                if currentsong and current_media_player == 0:
                    if os.path.isfile(currentsong):
                        if os.path.splitext(currentsong)[1] in supported_file_types:
                            if sys.platform == 'win32':
                                currentsong=currentsong.replace('/', '\\')
                                IPrint(f"Opening currently playing song: {currentsong}", visible=visible)
                                os.system(f'explorer /select, {currentsong}')
                            else:
                                currentsong=currentsong.replace('\\', '/')
                        else:
                            IPrint(0, visible=visible)
                    else:
                        IPrint(0, visible=visible)
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

            elif len(commandslist) > 1 and commandslist[1] in ['lib', 'library']:
                IPrint(fr'Opening library file in editor', visible=visible)
                if not DEFAULT_EDITOR:
                    restore_default.restore('editor path', SETTINGS)
                    DEFAULT_EDITOR = SETTINGS.get('editor path')

                sp.Popen([fr"{DEFAULT_EDITOR}", 'lib.lib'], shell = True)

            elif len(commandslist) > 1 and commandslist[1] in ['lyr', 'lyrics']:
                IPrint(fr'Opening library file in editor', visible=visible)
                lyrics_ops(show_window = False)
                if not DEFAULT_EDITOR:
                    restore_default.restore('editor path', SETTINGS)
                    DEFAULT_EDITOR = SETTINGS.get('editor path')

                sp.Popen([fr"{DEFAULT_EDITOR}", 'temp/lyrics.txt'], shell = True)

            else:
                path = ' '.join(commandslist[1:])
                if os.path.isfile(path):
                    if os.path.splitext(path)[1] in supported_file_types:
                        if sys.platform == 'win32': path=path.replace('/', '\\')
                        else: path=path.replace('\\', '/')
                        IPrint(f"Opening currently playing song: {path}", visible=visible)
                        os.system(f'explorer /select, {path}')
                    else:
                        IPrint(0, visible=visible)
                else:
                    IPrint(0, visible=visible)

        elif commandslist in [['sm'], ['sync'], ['sync', 'media']]:
            IPrint("Syncing current media...", visible=visible)
            if current_media_type == 0: # If YT vid is playing...
                IPrint(f"YouTube audio cannot be synced, only seeked", visible=visible)
            elif current_media_type == 1: # If audio is playing...
                IPrint(f"audio url cannot be synced, only seeked", visible=visible)
            elif current_media_type == 2: # If radio is playing...
                vas.media_player(action='resync') # Resync radio to live stream
            elif current_media_type == 3: # If reddit-session is streaming...
                # TODO - Find a way to get the current stream timestamp of current RPAN session
                print(f'Reddit session sync: The developer @{SYSTEM_SETTINGS["about"]["author"]} will add this feature shortly...')

        elif commandslist[0] == 'path':
            if len(commandslist) == 1 and currentsong and current_media_player == 0:
                IPrint(f":: {colored.fg('plum_1')}{songindex}{colored.attr('reset')} | {currentsong}", visible=visible)

            elif len(commandslist) == 2:
                if int(commandslist[1]) > 0:
                    try:
                        IPrint(_sound_files[int(commandslist[1])-1], visible=visible)
                    except IndexError:
                        err('', f'Please input song number between 1 and {len(_sound_files)}')
                else:
                    err('', f'Please input song number between 1 and {len(_sound_files)}')

        elif commandslist[0].lower() in ['find', 'f']:
            if len(commandslist) > 1:
                if commandslist[-1].isnumeric():
                    myquery = commandslist[1:-1]
                    searchresults = (searchsongs(queryitems=myquery))
                    searchresults = searchresults[:int(commandslist[-1])]
                else:
                    myquery = commandslist[1:]
                    searchresults = (searchsongs(queryitems=myquery))
                if searchresults != []:
                    IPrint(
                    f"{colored.fg('orange_1')}Found {len(searchresults)} match{('es')*(len(searchresults)>1)} for: {' '.join(myquery)}{colored.attr('reset')}", visible=visible)
                    IPrint(tbl(searchresults, tablefmt='mysql', headers=('#', 'Song')), visible=visible)
                else:
                    IPrint(colored.fg('hot_pink_1a')+"-- No results found --"+colored.attr('reset'), visible=visible)

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

            lyrics_ops(show_window = True)

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
                    IPrint(f"}}}} {cached_volume*100} %", visible=visible)

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
                    if comtypes_load_error:
                        SAY(visible=visible,
                            log_message="comtypes functionality used even when not available",
                            display_message="This functionality is unavailable",
                            log_priority=3)
                    else:
                        try:
                            IPrint(f"}}}} {get_master_volume()} %", visible=visible)
                        except Exception:
                            SAY(visible=visible, display_message='ERROR: Couldn\'t get system master volume', log_message=f'Unknown error while getting master volume as percent: {currentsong}', log_priority=2)

            except Exception:
                err(error_topic='Some internal issue occured while setting the system volume')
            '''

            print('Sorry, system volume commands have been (temporarily) disabled...\n...due to some internal issue (Issue #244, #180 comtypes)')

        elif commandslist in [['l'], ['len'], ['length']]:
            if currentsong and currentsong_length != -1:
                if currentsong_length:
                    IPrint(convert(currentsong_length), visible=visible)
                else:
                    IPrint(convert(get_currentsong_length()), visible=visible)

        elif commandslist in [['lib'], ['library']]:
            IPrint("Opening location of library file", visible=visible)
            sp.Popen(f'explorer /select, lib.lib')

        elif commandslist[0] == 'view':
            if len(commandslist) == 2:
                if commandslist[1] in ['lib', 'library']:
                    IPrint("Opening library file in browser for viewing", visible=visible)
                    if webbrowser._tryorder in [['windows-default'], None]:
                        for brave_path in SYSTEM_SETTINGS['system_settings']['brave_paths']:
                            if os.path.exists(brave_path):
                                break

                        webbrowser.register('brave', None, webbrowser.BackgroundBrowser(brave_path))
                        webbrowser.get('brave').open_new(os.path.join(CURDIR, 'lib.lib'))

                    else:
                        webbrowser.get('brave').open_new(os.path.join(CURDIR, 'lib.lib'))

                elif commandslist[1] in ['lyr', 'lyrics']:
                    IPrint("Attempting to open lyrics file in browser for viewing", visible=visible)
                    lyrics_ops(show_window = False)
                    if webbrowser._tryorder in [['windows-default'], None]:
                        for brave_path in SYSTEM_SETTINGS['system_settings']['brave_paths']:
                            if os.path.exists(brave_path):
                                break

                        webbrowser.register('brave', None, webbrowser.BackgroundBrowser(brave_path))
                        if os.path.isfile('temp/lyrics.txt'):
                            webbrowser.get('brave').open_new(os.path.join(CURDIR, 'temp/lyrics.txt'))
                        else:
                            SAY(visible=visible,
                                log_message = 'No lyrics available to view',
                                display_message = 'No lyrics available to view',
                                log_priority = 2)
                    else:
                        if os.path.isfile('temp/lyrics.txt'):
                            webbrowser.get('brave').open_new(os.path.join(CURDIR, 'temp/lyrics.txt'))
                        else:
                            SAY(visible=visible,
                                log_message = 'No lyrics available to view',
                                display_message = 'No lyrics available to view',
                                log_priority = 2)

        elif commandslist in [['music-downloads'], ['md']]:
            from beta import mediadl
            dl_dir_setup_code = mediadl.setup_dl_dir(SETTINGS, SYSTEM_SETTINGS)
            if dl_dir_setup_code not in range(4):
                dl_dir = dl_dir_setup_code
                if sys.platform == 'win32': dl_dir=dl_dir.replace('/', '\\')
                else: dl_dir=dl_dir.replace('\\', '/')
                IPrint(f"Opening downloads directory: {dl_dir}", visible=visible)
                os.system(f'explorer {dl_dir}')
            else:
                # ERRORS have already been handled and logged by `mediadl.setup_dl_dir()`
                pass

        # E.g. /ys "The Weeknd Blinding Lights"
        #                       or
        #      /ys "The Weeknd Blinding Lights" 4
        elif commandslist[0] in ['/ys', '/youtube-search']:
            YOUTUBE_PLAY_TYPE = 1
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
                    elif int(rescount) in range(2, max_yt_search_results_threshold+1):
                        ytv_choices = YT_query.search_youtube(
                            search=qr_val, rescount=int(rescount))
                    else:
                        if int(rescount) <= 0:
                            SAY(visible=visible,
                                log_message = 'Subceeded lower threshold for YT search result count',
                                display_message = f'YT result count should be > 0, please retry',
                                log_priority = 2)

                        if int(rescount) > max_yt_search_results_threshold:
                            SAY(visible=visible,
                                log_message = 'Exceeded upper threshold for YT search result count',
                                display_message = f'YT results limit exceeded, retry with result count <= {max_yt_search_results_threshold}',
                                log_priority = 2)

                else:
                    SAY(visible=visible,
                        log_message = 'Invalid value for YT search result count',
                        display_message = f'Invalid value for YT search result count',
                        log_priority = 2)

                if ytv_choices:
                    choose_media_url(media_url_choices=ytv_choices)

            except Exception:
                # raise
                SAY(visible=visible,
                    display_message="Invalid YouTube search, type: [/youtube-search | /ys] \"<search terms>\" [<result_count>]",
                    log_message="Invalid YouTube search by user",
                    log_priority=2)

        elif commandslist[0].lower() in ['/yl', '/youtube-link']:
            YOUTUBE_PLAY_TYPE = 0
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
                    IPrint(tbl([(f"{colored.fg('light_red')}/wra {i+1}{colored.attr('reset')}", j) for i, j in enumerate(r_stations)], tablefmt='plain'), visible=visible)
            else:
                err("Unknown webradio command, too long")  # Too many args

        elif commandslist[0] in ['/rs', '/reddit-sessions']:

            reload_reddit_creds()

            if r_seshs:
                global r_seshs_data
                r_seshs_data, rs_params = redditsessions.display_seshs_as_table(r_seshs)
                r_seshs_data_processed = [[i+1]+j for i,j in enumerate([list(i.values()) for i in r_seshs_data])]
                if len(commandslist) == 1:
                    r_seshs_table = tbl(r_seshs_data_processed,
                                        tablefmt='simple',
                                        headers=["#", "RPAN Session"]+[*rs_params[1:]])
                    IPrint(r_seshs_table, visible=visible)
                    IPrint('\n', visible=visible)
                    sesh_index = input(f"{colored.fg('light_slate_blue')}Enter RPAN session number to tune into: {colored.fg('navajo_white_1')}")
                    print(colored.attr('reset'), end='')
                elif len(commandslist) == 2:
                    sesh_index = commandslist[1]

                if len(commandslist) <= 3:
                    if sesh_index.strip():
                        IPrint("[INFO] Reddit sessions sometimes may take ages to start and seek...", visible=visible)
                    else:
                        IPrint(f"{colored.fg('hot_pink_1a')}Skipping RPAN stream (left empty){colored.attr('reset')}")
                    if sesh_index.isnumeric():
                        sesh_index = int(sesh_index)-1
                        if sesh_index in range(len(r_seshs_data)):
                            sesh_name=r_seshs_data[sesh_index].get('title')
                            if not sesh_name: sesh_name = '[UNRESOLVED REDDIT SESSION]'
                            IPrint(f"Tuning into RPAN: {colored.fg('indian_red_1b')}{sesh_name}{colored.attr('reset')}", visible=visible)
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
            IPrint('\n', visible=visible)


def showversion():
    global visible, SYSTEM_SETTINGS
    if visible and SYSTEM_SETTINGS:
        try:
            print(colored.fg('aquamarine_3')+\
                  f"v {SYSTEM_SETTINGS['ver']['maj']}.{SYSTEM_SETTINGS['ver']['min']}.{SYSTEM_SETTINGS['ver']['rel']}"+\
                  colored.attr('reset'))
            print()
        except Exception:
            pass


def showbanner():
    global visible
    banner_lines = []
    if visible:
        try:
            with open('res/banner.banner', encoding='utf-8') as file:
                banner_lines = file.read().splitlines()
                maxlen = len(max(banner_lines, key=len))
                if maxlen % 10 != 0:
                    maxlen = (maxlen // 10 + 1) * 10 # Smallest multiple of 10 >= maxlen,
                                                     # Since 10 is the length of cols...
                                                     # So lines will be printed with full olor range
                                                     # and would be more visually pleasing...
                banner_lines = [(x + ' ' * (maxlen - len(x))) for x in banner_lines]
                for banner_line in banner_lines:
                    blue_gradient_print(banner_line, cols+cols[::-1])
        except IOError:
            pass
    
    if visible: showversion()

def run():
    global disable_OS_requirement, visible, USER_DATA

    if disable_OS_requirement and visible and sys.platform != 'win32':
        print("WARNING: OS requirement is disabled, performance may be affected on your Non Windows OS")

    USER_DATA['default_user_data']['stats']['log_ins'] += 1
    save_user_data()

    pygame.mixer.init()
    if visible: showbanner()
    mainprompt()


def startup():
    global disable_OS_requirement, SOFT_FATAL_ERROR_INFO

    try: os.system('color 0F') # Needed?!? idk
    except Exception: pass

    try: first_startup_greet(FIRST_BOOT)
    except Exception: raise

    # Spawn get_media process in the bg
    if _sound_files != [] and FIRST_BOOT:
        sp.Popen(['py', 'meta_getter.py', str(supported_file_types)], shell=True)

    if not disable_OS_requirement:
        if sys.platform != 'win32':
            sys.exit('ABORTING: This program may not work on'
            'Non-Windows Operating Systems (hasn\'t been tested)')
    if not SOFT_FATAL_ERROR_INFO: # End program silently if SOFT_FATAL_ERROR_INFO is set
        if FATAL_ERROR_INFO:
            IPrint(f"FATAL ERROR ENCOUNTERED: {FATAL_ERROR_INFO}", visible=visible)
            IPrint("Exiting program...", visible=visible)
            sys.exit(1) # End program...forcefully...
        else: run()


if __name__ == '__main__':
    startup()
else:
    print(' '*30, end='\r')  # Get rid of the current '\r'...

# Way to convert chars outside BMP to unicode:
# out_str = test_str.encode('utf-16','surrogatepass').decode('utf-16')

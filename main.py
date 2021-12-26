
##############################################################################
# Mariana Player v0.1.0

# run: `pip install -r requirements.txt` and
# take a look at `help.md` before running this...

# This app may take a LOT of time to load at first...
# Hence the loading prompt...
# Prompts like these will be made better and more
# dynamic using the IPrint (custom) and multiprocess modules

# Editor's Note: Make sure to brew a nice coffee beforehand... :)
##############################################################################



# IMPORTS BEGIN #

import time
APP_BOOT_START_TIME = time.time();                  print("Loaded 1/24", end='\r')

import os;                                          print("Loaded 2/24", end='\r')
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

# import itertools;                                   print("Loaded 3/24", end='\r')

import re;                                          print("Loaded 4/24", end='\r')
import sys;                                         print("Loaded 5/24",  end='\r')
import urllib;                                      print("Loaded 6/24",  end='\r')
import pygame;                                      print("Loaded 7/24",  end='\r')
import numpy as np;                                 print("Loaded 8/24", end='\r')
import random as rand;                              print("Loaded 9/24", end='\r')
import importlib;                                   print("Loaded 10/24", end='\r')

# import concurrent.futures;                          print("Loaded 11/24", end='\r')

from tabulate import tabulate as tbl;               print("Loaded 12/24", end='\r')
from ruamel.yaml import YAML;                       print("Loaded 13/24", end='\r')
from collections.abc import Iterable;               print("Loaded 14/24", end='\r')
from logger import SAY;                             print("Loaded 15/24", end='\r')
from multiprocessing import Process;                print("Loaded 16/24", end='\r')


online_streaming_ext_load_error = 0
lyrics_ext_load_error = 0
redditsessions = None


try:
    import lyrics_provider.lyrics_view_window # Time taking import
    print("Loaded 17/24", end='\r')
except ImportError:
    # raise
    print("[INFO] Could not load lyrics extension...")
    print("[WARN] Skipped 17/24")

try:
    import librosa
    print("Loaded 18/24",  end='\r') # Time taking import (Sometimes, takes ages...)
except ImportError:
    print("[WARN] Could not load music computation extension...")
    print("[WARN] Skipped 18/24")

try:
    vas = importlib.import_module("beta.vlc-async-stream")
    vas = importlib.reload(vas)
    print("Loaded 19/24", end='\r')
except ImportError:
    online_streaming_ext_load_error = 1
    print("[INFO] Could not load online streaming extension...")
    print("[WARN] Skipped 19/24")

try:
    YT_query = importlib.import_module("beta.YT_query")
    print("Loaded 20/24", end='\r')
except ImportError:
    if not online_streaming_ext_load_error:
        print("[INFO] Could not load online streaming extension...")
    print("[WARN] Skipped 20/24")

try:
    IPrint = importlib.import_module('beta.IPrint')
    print("Loaded 21/24", end='\r')
except ImportError:
    lyrics_ext_load_error = 1
    print("[INFO] Could not load coloured print extension...")
    print("[INFO] Skipped 21/24")

try:
    lvw = importlib.import_module('lyrics_provider.lyrics_view_window')
    print("Loaded 22/24", end='\r')
except ImportError:
    print("[INFO] Could not load lyrics extension...")
    if not lyrics_ext_load_error:
        print("[INFO] Could not load online streaming extension...")
    print("[INFO] Skipped 22/24")

try:
    from beta import redditsessions
    if redditsessions.WARNING:
        print("[WARN] Could not load reddit-sessions extension...")
        print(f"[WARN] {redditsessions.WARNING}")
        print("[WARN] Skipped 23/24")
        redditsessions = None
    else:
        print("Loaded 23/24", end='\r')
except ImportError:
    print("[INFO] Could not load reddit-sessions extension..., module 'praw' missing")
    print("[INFO] Skipped 23/24")

from beta.master_volume_control import get_master_volume, set_master_volume
print("Loaded 24/24", end='\r')

    

# Variables
APP_BOOT_TIME_END = time.time()
FIRST_BOOT = False
yaml = YAML(typ='safe')  # Allows for safe YAML loading

EXIT_INFO = 0

isplaying = False
songstopped = True
currentsong = None  # No song playing initially
ismuted = False
isshowinglyrics = False

settings = None
disable_OS_requirement = True
songindex = -1

current_media_player = 0
"""
current_media_player can be either 0 or 1:
    0: default (pygame)
    1: vlc
"""

# From settings
supported_file_exts = '.wav .mp3'.split()  # Supported file extensions
visible = True
max_yt_search_results_threshold = 15
loglevel = 3

# From last session info
cached_volume = 1  # Set as a factor between 0 to 1 times of max volume player volume

# IMPORTS END #

curdir = os.path.dirname(os.path.realpath(__file__))
os.chdir(curdir)

if not os.path.isdir('logs'):
    os.mkdir('logs')


def create_required_files_if_not_exist(*files):
    global FIRST_BOOT
    for file in files:
        if not os.path.isfile(file):
            FIRST_BOOT = True
            with open(file, 'w') as _:
                pass


create_required_files_if_not_exist(
    'recents.log',
    'generallogs.log',
)

try:
    with open('about/about.info', encoding='utf-8') as file:
        ABOUT = yaml.load(file)
        FIRST_BOOT = ABOUT['first_boot']
except IOError:
    ABOUT = None


try:
    with open('lib.lib', encoding='utf-8') as logfile:
        paths = logfile.read().splitlines()
        paths = [path for path in paths if not path.startswith('#')]
except IOError:
    if FIRST_BOOT:
        try:
            import first_boot_setup
            first_boot_setup.fbs(about=ABOUT)
        except ImportError:
            sys.exit('[ERROR] Critical guide setup-file missing, please consider reinstalling this file or the entire program\nAborting Mariana Player. . .')
    else:
        sys.exit("[ERROR] Could not find lib.lib file, '\
                'please create one and add desired source directories. '\
                'Aborting program\n")


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



# Use the recursive extractor function and format and store them into usable lists
_sound_files = [[list(audio_file_gen(paths[j], supported_file_exts[i]))
                 for i in range(len(supported_file_exts))] for j in range(len(paths))]
# Flattening irregularly nested sound files
_sound_files = list(flatten(_sound_files))

_sound_files_names_only = [os.path.splitext(os.path.split(i)[1])[0] for i in _sound_files]
_sound_files_names_enumerated = [(i+1, j) for i, j in enumerate(_sound_files_names_only)]


if redditsessions:
    r_seshs = redditsessions.get_redditsessions()
else:
    r_seshs = None

# TODO - Make url_is_valid a multipurpose function for yt and otherwise
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
    else:
        return False


def exitplayer(sys_exit=False):
    global songstopped, EXIT_INFO, APP_BOOT_START_TIME

    songstopped = True
    try:
        pygame.mixer.music.stop()
        pygame.mixer.quit()
    except Exception:
        pass

    try:
        vas.media_player(action='stop')
    except Exception:
        pass

    APP_CLOSE_TIME = time.time()


    # TODO
    # Log exit info in logger...
    # Save this session info for next bootup...
    # including time spent on application (with APP_CLOSE_TIME - APP_BOOT_TIME_START)...

    if visible:
        print('Exiting...')

    if sys_exit:
        sys.exit(f"{EXIT_INFO}")

# def loadsettings():
#     global settings
#     with open('', encoding='utf-8') as settingsfile:
#         settings = yaml.load(settingsfile)


def play_local_default_player(songpath, _songindex):
    global isplaying, currentsong, songlength, songindex, current_media_player

    try:
        if current_media_player:
            vas.media_player(action='stop')
        pygame.mixer.music.load(songpath)
        pygame.mixer.music.play()
        current_media_player = 0
        isplaying = True
        currentsong = songpath

        load_song_info()

        if _songindex:
            print(f':: {_sound_files_names_only[int(_songindex)-1]}')
        else:
            print(f':: {os.path.splitext(os.path.split(songpath)[1])[0]}')

    except Exception:
        # raise
        err(
            f'Failed to play: {os.path.splitext(os.path.split(songpath)[1])[0]}', say=False)
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
            print(int(diffvolume))
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
        raise
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
    print(f'x| ERROR {error_topic}')
    if message:
        print('x|  '+message)

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


def get_bpm(filename, duration=50, enable_round=True):
    y, sr = librosa.load(filename, duration=duration)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    if enable_round:
        return round(tempo)
    else:
        return tempo


def display_lyrics_window():
    global isshowinglyrics
    isshowinglyrics = not isshowinglyrics

    lyrics_provider.lyrics_view_window.show_window(head=currentsong)


def enqueue(songindices):
    print("Enqueuing")
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
    # print(commandslist, _command)
    global cached_volume
    pygame.mixer.music.set_volume(cached_volume)

    if not _command:
        if len(commandslist) == 2:
            songindex = commandslist[1]
            if songindex.isnumeric():
                if int(songindex) in range(len(_sound_files)+1):
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
        play_local_default_player(songpath=_command[1:], _songindex=None)


def load_song_info():
    global isplaying, currentsong, songlength

    if currentsong:
        if isplaying:
            sound_obj = pygame.mixer.Sound(currentsong)

            songlength = sound_obj.get_length()

            curseekvalue = pygame.mixer.music.get_pos
            curseekper = pygame.mixer.music.get_pos()/(sound_obj.get_length()*10)


def timeinput_to_timeobj(rawtime):
    # print(songlength, type(songlength))
    try:
        if ':' in rawtime.strip():
            processed_rawtime = rawtime.split(':')
            processed_rawtime = [int(i) if i else 0 for i in processed_rawtime]

            print(processed_rawtime)

            # timeobj: A list of the format [WHOLE HOURS IN SECONDS, WHOLE MINUTES in SECONDS, REMAINING SECONDS]
            timeobj = [value * 60 ** (len(processed_rawtime) - _index - 1)
                       for _index, value in enumerate(processed_rawtime)]

            totaltime = sum(timeobj)

            formattedtime = ' '.join([''.join(map(lambda x: str(x), i)) for i in list(
                zip(processed_rawtime, ['h', 'm', 's']))])

            if totaltime > songlength:
                return ValueError
            else:
                # print (formattedtime, totaltime)
                return (formattedtime, totaltime)

        else:
            if rawtime.strip() == '-0':
                return ('0', 0)

            elif rawtime.isnumeric():
                if int(rawtime) > songlength:
                    return ValueError
                else:
                    processed_rawtime = list(
                        map(lambda x: int(x), convert(int(rawtime)).split(':')))
                    formattedtime = ' '.join([''.join(map(lambda x: str(x), i)) for i in list(
                        zip(processed_rawtime, ['h', 'm', 's']))])
                    # print (None, rawtime)
                    return (formattedtime, rawtime)

    except Exception:
        # raise
        # print (None, None)
        return (None, None)


def song_seek(timeval):
    global currentsong
    # print(f"Timeval: {timeval}")
    try:
        pygame.mixer.music.set_pos(int(timeval))  # *1000)
        # pygame.mixer.music.set_pos(int(timeval/1000))
        return True
    except pygame.error:
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

    return "%d:%02d:%02d" % (hour, minutes, seconds)


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

    global isplaying, current_media_player, visible, currentsong, cached_volume

    stopsong()

    current_media_player = 1

    if media_type == 'video':
        vas.set_media(_type='yt_video', vidurl=media_url)
    elif media_type == 'audio':
        vas.set_media(_type='audio', audurl=media_url)
    elif media_type == 'radio':
        # Here `media_name` is actually the radio name
        vas.set_media(_type=f'radio/{media_name}') # No need for an explicit `audurl` here... (as per definition of vas.set_media)
    else:
        err("Invalid media provided")

    vas.media_player(action='play')
    vas.vlc_media_player.get_media_player().audio_set_volume(int(cached_volume*100))
    isplaying = True

    if not media_name and media_type == 'video':
        try:
            vid_info = YT_query.vid_info(media_url)
            media_name = vid_info['title']
        except Exception:
            pass

    if media_type == 'video':
        current_media_type = 0
        currentsong = (media_name, media_url)
        if print_now_playing and visible:
            if single_video:
                print(f"Playing YouTube search result: {media_name}")
            else:
                print(f"Chosen YouTube video: {media_name}")
            print(f"@ {media_url}")
    elif media_type == 'audio':
        current_media_type = 1
        currentsong = media_url
        print("C")
    elif media_type == 'radio':
        current_media_type = 2
        currentsong = media_name




def choose_yt_vid(ytv_choices: list):
    global current_media_player, isplaying, currentsong

    if len(ytv_choices) == 1:
        vid_name, media_url = ytv_choices[0]
        play_vas_media(media_name=vid_name, media_url=media_url, single_video=True)

    else:
        chosen_index = input(f"Choose video number between 1 and {len(ytv_choices)} \
                             (leave blank to skip): ").strip()

        if chosen_index:
            try:
                chosen_index = int(chosen_index)
            except Exception:
                print("ERROR: Invalid choice, choose again: ", end='\r')

            if chosen_index in range(1, len(ytv_choices)+1):
                _, vid_name, media_url = ytv_choices[chosen_index-1]
                play_vas_media(media_name=vid_name, media_url=media_url,
                              single_video=False)
                # print(f"Chosen YouTube video: {vid_name}")
                # print(f"@ {media_url}")

                # stopsong()

                # vas.set_media(_type='yt_video', vidurl=media_url)
                # vas.media_player(action='play')
                # isplaying = True
                # currentsong = (vid_name, media_url)

                # current_media_player = 1
            else:
                print("ERROR: Invalid choice, choose again: ", end='\r')


def process(command):
    global _sound_files_names_only, visible, currentsong, isplaying, ismuted, cached_volume
    commandslist = command.strip().split()

    if pygame.mixer.music.get_pos() == -1:
        try:
            if vas.vlc_media_player.get_state().value == 5:
                currentsong = None
                isplaying = False
        except Exception:
            pass

    # print(commandslist)

    if commandslist != []:  # Atleast 1 word
        if commandslist in [['exit'], ['quit'], ['e']]:  # Quitting the player
            perm = input('Do you want to exit? [Y]es, [N]o (default = N): ')
            if perm.strip().lower() == 'y':
                return False

        # Quitting the player w/o conf
        elif commandslist in [['exit', 'y'], ['quit', 'y'], ['e', 'y']]:
            return False

        if commandslist in ['all', 'ls']:
            # TODO: Need to display files in n columns (Mostly 3 cols) depending upon terminal size (dynamically...)
            print(
                tbl([(i+1, j) for i, j in enumerate(_sound_files_names_only)], tablefmt='plain'))

        elif commandslist == ['vis']:
            visible = not visible
            if visible:
                print('visibility on')

        elif commandslist == ['dev:cachedvol']: # TODO - remove
            print(f"cached_volper {cached_volume*100}")

        elif commandslist == ['now']:
            if currentsong:
                if current_media_player: # VLC
                    print(f"@ys: {currentsong[0]}")
                else: # pygame
                    cur_song = os.path.splitext(
                        os.path.split(currentsong)[1])[0]
                    print(f":: {cur_song}")
            else:
                # currentsong = None
                print("(Not Playing)")

        elif commandslist == ['now*']:
            if currentsong:
                if current_media_player: # VLC
                    if current_media_type == 0:
                        print(f"@ys: Title | {currentsong[0]}")
                        print(f"     Link  | {currentsong[1]}")
                    elif current_media_type == 1:
                        print(f"@al: {currentsong}")
                    elif current_media_type == 2:
                        print(f"@radio web/{currentsong}")

                else: # pygame
                    print(f":: {currentsong}")

            else:
                currentsong = None
                print(f"(Not Playing)")

        elif commandslist[0].lower() == 'play':
            play_commands(commandslist=commandslist)

        elif commandslist[0].lower() in ['m?', 'ism?', 'ismute?']:
            print(int(ismuted))

        elif commandslist[0].lower() in ['isp?', 'ispl', 'isp']:
            SAY(visible=visible,
                display_message='/? Invalid command, perhaps you meant "ispl?" for "is playing?"', log_message=f'Command assumed to be misspelled: {currentsong}', log_priority=3)

        elif commandslist[0].lower() in ['ispl?', 'isplaying?']:
            print(isplaying)

        elif commandslist[0].lower() in ['isl?', 'isloaded?']:
            if current_media_player:
                print(vas.vlc.media)
            print(bool(currentsong))

        elif commandslist[0].lower() == 'seek':
            rawtime = commandslist[1]

            time_validity = validate_time(rawtime)

            if not time_validity:
                # Take a valid raw value for time from the user. Format is defined in the time section of help
                timeobj = timeinput_to_timeobj(rawtime)
                # print(timeobj)
                if not timeobj == ValueError:
                    if timeobj == (None, None):
                        err('Invalid time format', 'Invalid time object')
                    # elif timeobj[0] == None:
                    #     song_seek(timeobj[1])
                    else:
                        _ = song_seek(timeobj[1])
                        if _:
                            print(f"Seeking to: {timeobj[0]}")

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

        elif commandslist == ['t']:
            cur_prog = int(pygame.mixer.music.get_pos()/1000)
            print("Current Progress: {0}".format(cur_prog))
            print(convert(cur_prog))

        elif commandslist == ['.rand']:  # Play random song
            play_commands(commandslist=[None, str(rand_song_index())])

        elif commandslist == ['=rand']:  # Print random song number
            print(rand_song_index())

        elif commandslist == ['rand']:  # Print random song name
            print(_sound_files_names_only[rand_song_index()])

        elif commandslist == ['rand*']:  # Print random song path
            print(_sound_files[rand_song_index()])

        elif commandslist == ['/rand']:  # Print random song number+name
            rand_index = rand_song_index()
            print(f"{rand_index+1}: {_sound_files_names_only[rand_index]}")

        elif commandslist == ['reset']:
            try:
                pygame.mixer.music.set_pos(0)
            except pygame.error:
                SAY(visible=visible, display_message="Error: Can't reset this song",
                    log_message=f'Unsupported codec for resetting: {currentsong}', log_priority=2)

        elif command[0] == '.':
            try:
                if len(commandslist) == 1:
                    # print(commandslist[0][1:])
                    if commandslist[0][1:].isnumeric():
                        play_commands(
                            commandslist=[None, ''.join(commandslist[0][1:])])
                        # getstats()

                elif commandslist != ['.'] and len(command.split('.')) == 3:
                    if all([not i.isnumeric() for i in command.split('.')]):
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
                            play_commands(
                                commandslist=[None, command[1:]], _command=command)

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
                        print(_sound_files_names_only[int(commandslist[0])-1])
                    except IndexError:
                        err('Out of range',
                            f'Please input song number between 1 and {len(_sound_files)}')
                else:
                    err('Out of range',
                        f'Please input song number between 1 and {len(_sound_files)}')

        elif commandslist in [['count'], ['howmany'], ['total']]:
            print(len(_sound_files_names_only))

        elif commandslist[0] == 'open':
            if commandslist == ['open']:
                if currentsong:
                    if os.path.isfile(currentsong):
                        if os.path.splitext(currentsong)[1] in supported_file_exts:
                            os.system(f'explorer /select, {currentsong}')
                        else:
                            print(0)
                    else:
                        print(0)
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

        elif commandslist[0] == 'path':
            if len(commandslist) == 2:
                if int(commandslist[1]) > 0:
                    try:
                        print(_sound_files[int(commandslist[1])-1])
                    except IndexError:
                        err('Out of range',
                            f'Please input song number between 1 and {len(_sound_files)}')
                else:
                    err('Out of range',
                        f'Please input song number between 1 and {len(_sound_files)}')

        elif commandslist[0].lower() in ['find', 'f']:
            if len(commandslist) > 1:
                myquery = commandslist[1:]
                searchresults = (searchsongs(queryitems=myquery))
                if searchresults != []:
                    print(
                        f"Found {len(searchresults)} match{('es')*(len(searchresults)>1)} for: {' '.join(myquery)}")
                    print(tbl(searchresults, tablefmt='mysql', headers=('#', 'Song')))
                else:
                    print("-- No results found --")

        elif commandslist == ['stop']:
            stopsong()

        elif commandslist == ['m']:
            ismuted = not ismuted

            if ismuted:
                pygame.mixer.music.set_volume(0)
            else:
                pygame.mixer.music.set_volume(cached_volume)

        # elif commandslist in ['l', 'lyr', 'lyrics']:
        #     song_info = shazam_song_info.get_song_info(currentsong)
        #     save_info(song_info)

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

        # E.g. /ys "The Weeknd Blinding Lights"     or
        #      /ys "The Weeknd Blinding Lights" 4
        elif commandslist[0] in ['/ys', '/youtube-search']:
            try:
                query_re_obj = list(re.finditer(r'\"(.+?)"', command))[0]

                qr_span = query_re_obj.span()
                qr_val = query_re_obj.group()[1:-1].strip()
                rescount = command[qr_span[1]:].strip()

                ytv_choices = None

                if rescount == '':
                    try:
                        ytv_choices = [YT_query.search_youtube(search=qr_val)]
                    except OSError:
                        err("Could not load video... (Maybe check your VPN?)",
                            "Video Load Error", say=False)
                elif rescount.isdigit():
                    if int(rescount) == 1:
                        try:
                            ytv_choices = [YT_query.search_youtube(search=qr_val)]
                        except OSError:
                            err("Could not load video... (Maybe check your VPN?)",
                                "Video Load Error", say=False)
                    if int(rescount) in range(2, max_yt_search_results_threshold+1):
                        ytv_choices = YT_query.search_youtube(
                            search=qr_val, rescount=int(rescount))

                if ytv_choices:
                    choose_yt_vid(ytv_choices=ytv_choices)

            except Exception:
                raise
                err("Invalid YouTube search, type: [/youtube-search | /ys] \"<search terms>\" [<result_count>]", say=False)

        elif commandslist[0].lower() in ['/yl', '/youtube-link']:
            if len(commandslist) == 2:
                media_url = commandslist[1]
                if url_is_valid(media_url):
                    play_vas_media(media_url=media_url, single_video=True)
                else:
                    SAY(visible=visible, display_message='Entered Youtube URL is invalid')
            else:
                err("Invalid YouTube-link command, too long")  # Too many args

        elif commandslist[0] in ['/al', '/audio-link']:
            if len(commandslist) == 2:
                user_aud_url = commandslist[1]
                if url_is_valid(user_aud_url, yt=False):
                    play_vas_media(media_url = commandslist[1])
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
                if r_station in 'lounge coffee chillout'.split(): # TODO - print these values in help...
                    play_vas_media(media_url=None, media_type='radio', media_name=r_station)
                else:
                    err(f"Unknown webradio station {r_station}")
            else:
                err("Unknown webradio command, too long")  # Too many args

        # TODO - DEBUG THIS + CONNECT TO play_vas_media
        elif commandslist[0] in ['/rs', '/reddit-sessions']:
            print(f'live sessions from r/redditsessions are still in progress... The developer @{ABOUT["about"]["author"]} will add this feature shortly...')


def mainprompt():
    while True:
        try:
            command = input(')> ')
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
            print(f"v {ABOUT['ver']['maj']}.{ABOUT['ver']['min']}.{ABOUT['ver']['rel']}")
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


def loadsettings():
    global SETTINGS

    with open('settings/config.yml') as file:
        SETTINGS = yaml.load(file)


def run():
    global disable_OS_requirement, visible

    if disable_OS_requirement and visible and sys.platform != 'win32':
        print("WARNING: OS requirement is disabled, performance may be affected on your Non Windows OS")

    pygame.mixer.init()
    loadsettings()
    showbanner()
    mainprompt()


def startup():
    global disable_OS_requirement
    os.system('color 0F')

    if not disable_OS_requirement:
        if sys.platform != 'win32':
            sys.exit(
                'ABORTING: This program may not work on Non-Windows Operating Systems (hasn\'t been tested)')
        else:
            run()
    else:
        run()


if __name__ == '__main__':
    startup()
else:
    print(' '*30, end='\r')  # Get rid of the current '\r'...



# Mariana Player v0.1.0

# This app may take a LOT of time to load at first... 
# Hence the loading prompt...
# Prompts like these will be made better and more dynamic using the IPrint (custom) and multiprocess modules

# Editor's Note: Make sure to brew a nice coffee beforehand... :)

import time
APP_START_TIME=time.time()
print("Loaded 1/16", end='\r')

import os; print("Loaded 2/16", end='\r')
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import itertools; print("Loaded 3/16", end='\r')

try:
    import lyrics_provider.lyrics_view_window # Time taking import
    print("Loaded 4/16", end='\r')
except ImportError:
    # raise
    print("Skipped 4/16", end='\r')
    print("[INFO] Could not load lyrics extension...")
    # sys.exit("[FATAL ERROR] Could not load lyrics extension...")

import sys; print("Loaded 5/16", end='\r')
import pygame; print("Loaded 6/16", end='\r')
import librosa; print("Loaded 7/16", end='\r') # Time taking import (Sometimes, takes ages...)
import numpy as np; print("Loaded 8/16", end='\r')
import random as rand; print("Loaded 9/16", end='\r')
import importlib; print("Loaded 10/16", end='\r')

from tabulate import tabulate as tbl; print("Loaded 11/16", end='\r')
from ruamel.yaml import YAML; print("Loaded 12/16", end='\r')
from collections.abc import Iterable; print("Loaded 13/16", end='\r')
from datetime import datetime as dt; print("Loaded 14/16", end='\r')

vas = importlib.import_module("beta.vlc-async-stream"); print("Loaded 15/16", end='\r')
YT_query = importlib.import_module("beta.YT_query"); print("Loaded 16/16", end='\r')

yaml = YAML(typ='safe') # Allows for safe YAML loading

def create_required_files_if_not_exist(*files):
    for file in files:
        if not os.path.isfile(file):
            with open(file, 'w') as _:
                pass

create_required_files_if_not_exist(
    'recents.log',
    'generallogs.log',
)

try:
    with open('lib.lib', encoding='utf-8') as logfile:
        paths = logfile.read().splitlines()
        paths = [path for path in paths if not path.startswith('#')]
except IOError:
    sys.exit('Could not open lib.lib file for reading the library, aborting program')


curdir = os.path.dirname(os.path.realpath(__file__))
os.chdir(curdir)

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


# Variables
isplaying = False
songstopped = True
currentsong = None # No song playing initially
ismuted = False
isshowinglyrics=False

settings = None
disable_OS_requirement = True
songindex = -1

# From settings
supported_file_exts = '.wav .mp3'.split()  # Supported file extensions
visible = True
loglevel = 3

# From last session info
cached_volume = 1 # Set as a factor between 0 to 1 times of max volume player volume

# From res/data
logleveltypes = {0: "none", 1: "fatal", 2: "warn", 3: "info", 4: "debug"}

# Use the recursive extractor function and format and store them into usable lists
_sound_files = [[list(audio_file_gen(paths[j], supported_file_exts[i]))
                 for i in range(len(supported_file_exts))] for j in range(len(paths))]
_sound_files = list(flatten(_sound_files)) # Flattening irregularly nested sound files

_sound_files_names_only = [os.path.splitext(os.path.split(i)[1])[0] for i in _sound_files]
_sound_files_names_enumerated = [(i+1, j) for i, j in enumerate(_sound_files_names_only)]




def NOW():
    return dt.strftime(dt.now(), '%d-%b-%Y %H:%M:%S')

def SAY(displaymessage=None, logmessage='', log_priority=loglevel):
    global visible, loglevel, logleveltypes
    if visible and displaymessage:
        print(displaymessage)

    if loglevel:
        with open('generallogs.log', 'a') as genlogfile:
            llt = logleveltypes[log_priority]
            genlogfile.write(f"({llt}) {NOW()} => {logmessage}\n")

def exitplayer():
    global songstopped
    songstopped = True # Not really needed, cuz the player's going to exit anyways...
    try:
        pygame.mixer.music.stop()
        pygame.mixer.quit()
    except Exception:
        pass

    if visible:
        sys.exit('Exiting...')
    else:
        sys.exit()

# def loadsettings():
#     global settings
#     with open('', encoding='utf-8') as settingsfile:
#         settings = yaml.load(settingsfile)

def playsong(songpath, _songindex):
    global isplaying, currentsong, songlength, songindex

    try:
        pygame.mixer.music.load(songpath)
        pygame.mixer.music.play()
        isplaying = True
        currentsong = songpath

        load_song_info()

        if _songindex:
            print(f':: {_sound_files_names_only[int(_songindex)-1]}')
        else:
            print(f':: {os.path.splitext(os.path.split(songpath)[1])[0]}')

    except Exception:
        err(f'Failed to play: {os.path.splitext(os.path.split(songpath)[1])[0]}', say=False)
        SAY(None, f"Failed to play \"{songpath}\"", 2)

def voltransition(
    initial=cached_volume,
    final=cached_volume,
    transition_time=0.2,
    disablecaching = False, # Enable volume caching by default
):
    global cached_volume

    for i in range(101):
        diffvolume = initial+(final-initial)*i/100
        time.sleep(transition_time/100)
        pygame.mixer.music.set_volume(round(diffvolume, 2))

    # if not disablecaching:
    #     cached_volume = final

def playpausetoggle(softtoggle=True): # Soft pause by default
    global isplaying, currentsong, cached_volume

    try:
        if currentsong:
            if isplaying:
                if softtoggle:
                    voltransition(initial=cached_volume, final=0, disablecaching=True)
                else:
                    voltransition(initial=cached_volume, final=0, transition_time=0, disablecaching=True)
                pygame.mixer.music.pause()
                isplaying = False
                print("|| Paused")
            else:
                pygame.mixer.music.unpause()
                if softtoggle:
                    pygame.mixer.music.set_volume(0)
                    voltransition(initial=0, final=cached_volume)
                else:
                    pygame.mixer.music.set_volume(0)
                    voltransition(initial=0, final=cached_volume, transition_time=0)
                isplaying = True
                print("|> Resumed")
        else:
            isplaying = False
            err("Nothing to pause/unpause")

    except Exception:
        err(f'Failed to toggle play/pause: {currentsong}', say=False)
        SAY(None, f"Failed to toggle play/pause for \"{currentsong}\"", 2)

def stopsong():
    global isplaying, currentsong
    try:
        pygame.mixer.music.stop()
        currentsong = None
        isplaying = False
    except Exception:
        print(f'Failed to stop: {currentsong}')

def err(error_topic='', message='', say=True):
    print(f'x| ERROR {error_topic}')
    if message:
        print('x|  '+message)

    if say:
        SAY(None, error_topic, 2)

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

def getstats():
    global currentsong

    # 1. Get the file path to an included audio example
    filename = librosa.example(currentsong)

    # 2. Load the audio as a waveform `y`
    #    Store the sampling rate as `sr`
    y, sr = librosa.load(filename)

    # 3. Run the default beat tracker
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)

    print('Estimated tempo: {:.2f} beats per minute'.format(tempo))

def getstats2():
    global currentsong
    y, sr = librosa.load(librosa.ex(currentsong))
    
    # Set the hop length; at 22050 Hz, 512 samples ~= 23ms
    hop_length = 512

    # Separate harmonics and percussives into two waveforms
    y_harmonic, y_percussive = librosa.effects.hpss(y)

    # Beat track on the percussive signal
    tempo, beat_frames = librosa.beat.beat_track(y=y_percussive, sr=sr)

    # Compute MFCC features from the raw signal
    mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=hop_length, n_mfcc=13)

    # And the first-order differences (delta features)
    mfcc_delta = librosa.feature.delta(mfcc)

    # Stack and synchronize between beat events
    # This time, we'll use the mean value (default) instead of median
    beat_mfcc_delta = librosa.util.sync(np.vstack([mfcc, mfcc_delta]), beat_frames)

    # Compute chroma features from the harmonic signal
    chromagram = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr)

    # Aggregate chroma features between beat events
    # We'll use the median value of each feature between beat frames
    beat_chroma = librosa.util.sync(chromagram, beat_frames, aggregate=np.median)

    # Finally, stack all beat-synchronous features together
    beat_features = np.vstack([beat_chroma, beat_mfcc_delta])

    print(tempo)
    return tempo

def display_lyrics_window():
    global isshowinglyrics
    isshowinglyrics = not isshowinglyrics

    lyrics_provider.lyrics_view_window.show_window(head = currentsong)

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
                    playsong(_sound_files[int(songindex)-1], _songindex=songindex)
                else:
                    err('Out of range', f'Please input song number between 1 and {len(_sound_files)}')

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
        playsong(songpath=_command[1:], _songindex=None)

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
            processed_rawtime=rawtime.split(':')
            processed_rawtime = [int(i) if i else 0 for i in processed_rawtime]

            print(processed_rawtime)

            # timeobj: A list of the format [WHOLE HOURS IN SECONDS, WHOLE MINUTES in SECONDS, REMAINING SECONDS]
            timeobj = [value * 60 ** (len(processed_rawtime) - _index - 1) for _index, value in enumerate(processed_rawtime)]

            totaltime = sum(timeobj)

            formattedtime = ' '.join([''.join(map(lambda x: str(x) , i)) for i in list(zip(processed_rawtime, ['h', 'm', 's']))])

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
                    processed_rawtime = list(map(lambda x:int(x), convert(int(rawtime)).split(':')))
                    formattedtime = ' '.join([''.join(map(lambda x: str(x) , i)) for i in list(zip(processed_rawtime, ['h', 'm', 's']))])
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
        pygame.mixer.music.set_pos(int(timeval))# *1000)
        # pygame.mixer.music.set_pos(int(timeval/1000))
        return True
    except pygame.error:
        raise # TODO - remove
        SAY(displaymessage="Error: Can't seek in this song", logmessage='Unsupported codec for seeking song: {currentsong}', log_priority=2)
        return None

def setmastervolume(value=None):
    global cached_volume
    if not value:
        value = cached_volume

    pass # ...

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
    if '.' in rawtime: return 1
    elif float(rawtime) < 0: return 3
    else: return 0

def process(command):
    global _sound_files_names_only, visible, currentsong, isplaying, ismuted, cached_volume
    commandslist = command.strip().split()

    if pygame.mixer.music.get_pos() == -1:
        currentsong=None
        isplaying=False

    # print(commandslist)

    if commandslist != []: # Atleast 1 word
        if commandslist in [['exit'], ['quit'], ['e']]: # Quitting the player
            perm = input('Do you want to exit? [Y]es, [N]o (default = N): ')
            if perm.strip().lower() == 'y':
                return False

        elif commandslist in [['exit', 'y'], ['quit', 'y'], ['e', 'y']]: # Quitting the player w/o conf
            return False

        if commandslist == ['all']:
            # TODO: Need to display files in n columns (Mostly 3 cols) depending upon terminal size (dynamically...)
            print(tbl([(i+1, j) for i, j in enumerate(_sound_files_names_only)], tablefmt='plain'))

        elif commandslist == ['vis']:
            visible = not visible
            if visible: print('visibility on')

        elif commandslist == ['dev:cachedvol']:
            print(f"cached_volume: {cached_volume}")

        elif commandslist == ['now']:
            if currentsong:
                cur_song = os.path.splitext(os.path.split(currentsong)[1])[0]
                print(f":: {cur_song}")
            else:
                currentsong = None
                print("(Not Playing)")

        elif commandslist == ['now*']:
            if currentsong:
                print(f":: {currentsong}")
            else:
                currentsong = None
                print(f"(Not Playing)")

        elif commandslist[0].lower() == 'play':
            play_commands(commandslist=commandslist)

        elif commandslist[0].lower() in ['m?', 'ism', 'ismute']:
            print(int(ismuted))

        elif commandslist[0].lower() == 'seek':
            rawtime = commandslist[1]

            time_validity = validate_time(rawtime)

            if not time_validity:
                timeobj = timeinput_to_timeobj(rawtime) # Take a valid raw value for time from the user. Format is defined in the time section of help
                # print(timeobj)
                if not timeobj == ValueError:
                    if timeobj == (None, None):
                        err('Invalid time object')
                    # elif timeobj[0] == None:
                    #     song_seek(timeobj[1])
                    else:
                        _ = song_seek(timeobj[1])
                        if _:
                            print(f"Seeking to: {timeobj[0]}")

                else:
                    SAY(displaymessage="Error: Seek value too large for this song", logmessage=f'Seek value too large for: {currentsong}', log_priority=2)
            elif time_validity == 1:
                SAY("Error: Seek value can't have a decimal point", f'Seek value floating point for: {currentsong}', 2)
            elif time_validity == 2:
                SAY("Error: Seek value must be numeric", f'Seek value non numeric for: {currentsong}', 2)
            elif time_validity == 3:
                SAY("Error: Seek value can't be negative", f'Seek value negative for: {currentsong}', 2)
            else: pass

        elif commandslist == ['t']:
            cur_prog = int(pygame.mixer.music.get_pos()/1000)
            print("Current Progress: {0}".format(cur_prog))
            print(convert(cur_prog))

        elif commandslist == ['.rand']: # Play random song
            play_commands(commandslist=[None, str(rand_song_index())])

        elif commandslist == ['=rand']: # Print random song number
            print(rand_song_index())

        elif commandslist == ['rand']: # Print random song name
            print(_sound_files_names_only[rand_song_index()])

        elif commandslist == ['rand*']: # Print random song path
            print(_sound_files[rand_song_index()])

        elif commandslist == ['/rand']: # Print random song number+name
            rand_index = rand_song_index()
            print(f"{rand_index+1}: {_sound_files_names_only[rand_index]}")

        elif commandslist == ['reset']:
            try:
                pygame.mixer.music.set_pos(0)
            except pygame.error:
                SAY(displaymessage="Error: Can't reset this song", logmessage='Unsupported codec for resetting: {currentsong}', log_priority=2)

        elif command[0] == '.':
            try:
                if len(commandslist) == 1:
                    # print(commandslist[0][1:])
                    if commandslist[0][1:].isnumeric():
                        play_commands(commandslist=[None, ''.join(commandslist[0][1:])])
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
                            play_commands(commandslist=[None, command[1:]], _command=command)

            except Exception:
                raise

        elif commandslist in [['clear'], ['cls']]:
            os.system('cls' if os.name == 'nt' else 'clear')
            showbanner()

        elif commandslist == ['p']:
            if len(commandslist) == 1:
                playpausetoggle()

        elif commandslist == ['ph']:
            if len(commandslist) == 1:
                playpausetoggle(softtoggle=False)

        # TODO: Refactor to replace two `err` funcs with one
        elif commandslist[0].isnumeric(): # Check if only a number is entered
            # global _sound_files
            if len(commandslist) == 1:
                if int(commandslist[0]) > 0:
                    try:
                        print(_sound_files_names_only[int(commandslist[0])-1])
                    except IndexError:
                        err('Out of range', f'Please input song number between 1 and {len(_sound_files)}')
                else:
                    err('Out of range', f'Please input song number between 1 and {len(_sound_files)}')


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
                        err('Out of range', f'Please input song number between 1 and {len(_sound_files)}')
                else:
                    err('Out of range', f'Please input song number between 1 and {len(_sound_files)}')

        elif commandslist[0].lower() in ['find', 'f']:
            if len(commandslist) > 1:
                myquery = commandslist[1:]
                searchresults = (searchsongs(queryitems=myquery))
                if searchresults != []:
                    print(f"Found {len(searchresults)} match{('es')*(len(searchresults)>1)} for: {' '.join(myquery)}")
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
                        SAY(displaymessage='Volume must not have decimal point precision', logmessage='Volume set to decimal percentage', log_priority=2)
                    else:
                        volper = int(commandslist[1])
                        if volper in range(101):
                            pygame.mixer.music.set_volume(volper/100)
                            cached_volume = volper/100
                        else:
                            SAY(displaymessage='Volume percentage is out of range, it must be between 0 and 100', logmessage='Volume percentage out of range', log_priority=2)

                elif len(commandslist) == 1:
                    print(f"}}}} {pygame.mixer.music.get_volume()*100} %")

            except Exception:
                err(error_topic = 'Some internal issue occured while setting player volume')

        elif commandslist[0].lower() in ['v', 'vol', 'volume']:
            try:
                if len(commandslist) == 2 and commandslist[1].isnumeric():
                    if '.' in commandslist[1]:
                        SAY(displaymessage='System volume must not have decimal point precision', logmessage='System volume set to decimal percentage', log_priority=2)
                    else:
                        volper = int(commandslist[1])
                        if volper in range(101):
                            setmastervolume(value=volper)
                        else:
                            SAY(displaymessage='System volume percentage is out of range, it must be between 0 and 100', logmessage='System volume percentage out of range', log_priority=2)

            except Exception:
                err(error_topic = 'Some internal issue occured while setting the system volume')

def mainprompt():
    while True:
        try:
            command = input(')> ')
            outcode = process(command)

            if outcode == False:
                exitplayer()
        except KeyboardInterrupt:
            print()

def showversion():
    global visible, ABOUT
    if visible:
        try:
            with open('about/about.info', encoding='utf-8') as file:
                ABOUT = yaml.load(file)
                print(f"v {ABOUT['ver']['maj']}.{ABOUT['ver']['min']}.{ABOUT['ver']['rel']}")
                print()
        except IOError:
            pass

def showbanner():
    global visible
    if visible:
        try:
            with open('about/banner.banner', encoding='utf-8') as file:
                print(file.read())
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

    if not disable_OS_requirement:
        if sys.platform != 'win32':
            sys.exit('ABORTING: This program may not work on Non-Windows Operating Systems (hasn\'t been tested)')
        else: run()
    else: run()

if __name__ == '__main__':
    startup()
else: print(' '*80, end='\r') # Get rid of the current '\r'...


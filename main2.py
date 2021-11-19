
import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import itertools
import time
import sys
import pygame
from multiprocess import Process

from tabulate import tabulate as tbl
from ruamel.yaml import YAML
from collections.abc import Iterable
from datetime import datetime as dt

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
    with open('sources.log', encoding='utf-8') as logfile:
        paths = logfile.read().splitlines()
        paths = [path for path in paths if not path.startswith('#')]
except IOError:
    sys.exit('Could not open sources.log file for reading the library, aborting program')


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
settings = None

# From settings
visible = True
loglevel = 3
supported_file_exts = '.wav .mp3'.split()  # Supported file extensions

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
    songstopped = True
    try:
        pygame.mixer.music.stop()
        pygame.mixer.quit()
    except Exception:
        pass

    sys.exit('Exiting...')

# def loadsettings():
#     global settings
#     with open('', encoding='utf-8') as settingsfile:
#         settings = yaml.load(settingsfile)

def playsong(songpath, songindex):
    global isplaying, currentsong

    try:
        pygame.mixer.music.load(songpath)        
        pygame.mixer.music.play()
        isplaying = True
        currentsong = songpath
        print(f':: {_sound_files_names_only[int(songindex)-1]}')
    except:
        err(f'Failed to play: {os.path.splitext(os.path.split(songpath)[1])[0]}', say=False)
        SAY(None, f"Failed to play \"{songpath}\"", 2)

def playpausetoggle():
    global isplaying, currentsong

    try:
        if currentsong:
            if isplaying:
                pygame.mixer.music.pause()
                isplaying = False
                print("|| Paused")
            else:
                pygame.mixer.music.unpause()
                isplaying = True
                print("|> Resumed")
        else:
            isplaying = False
            err("Nothing to pause/unpause")

    except:
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

def enqueue(songindices):
    print("Enqueuing")
    song_paths_to_enqueue = []

    for songindex in songindices:
        song_paths_to_enqueue.append(_sound_files[int(songindex)-1])
    
    for songpath in song_paths_to_enqueue:
        try:
            pygame.mixer.music.queue(songpath)
        except Exception:
            err("Queueing error", "Could not enqueue one or more files")

def play_commands(commandslist):
    if len(commandslist) == 2:
        songindex = commandslist[1]
        if songindex.isnumeric():
            if int(songindex) in range(len(_sound_files)+1):
                playsong(_sound_files[int(songindex)-1], songindex=songindex)
            else:
                err('Out of range', f'Please input song number between 1 and {len(_sound_files)}')

    else:
        songindices = commandslist[1:]
        _ = []
        for songindex in songindices:
            try:
                if songindex.isnumeric():
                    _.append(songindex)
            except:
                pass
        
        songindices = _
        del _

        enqueue(songindices)

def playstatus():
    global isplaying, currentsong

    if pygame.mixer.music.get_pos() == -1:
        currentsong=None
        isplaying=False

    if currentsong:
        if isplaying:
            sound_obj = pygame.mixer.Sound(currentsong)

            curseekvalue = pygame.mixer.music.get_pos
            curseekper = pygame.mixer.music.get_pos()/(sound_obj.get_length()*10)
            return curseekvalue, curseekper
        else:
            return 0
    else:
        return 0

def liveplaystatus():
    while True:
        # print(playstatus)
        print(10101010)
        time.sleep(0.5)

def process(command):
    global _sound_files_names_only, visible, currentsong, isplaying
    commandslist = command.strip().split()

    if commandslist != []: # Atleast 1 word
        if commandslist in [['exit'], ['quit'], ['q'], ['e']]: # Quitting the player
            perm = input('Do you want to exit? [Y]es, [N]o (default = N): ')
            if perm.strip().lower() == 'y':
                return False

        elif commandslist in [['exit', 'y'], ['quit', 'y'], ['q', 'y'], ['e', 'y']]: # Quitting the player w/o conf
            return False

        if commandslist == ['all']:
            # TODO: Need to display files in n columns (Mostly 3 cols) depending upon terminal size (dynamically...)
            print(tbl([(i+1, j) for i, j in enumerate(_sound_files_names_only)], tablefmt='plain'))

        elif commandslist == ['vis']:
            visible = not visible
            if visible: print('visibility on')

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

        elif commandslist[0][0] == '.':
            try:
                if commandslist[0][1:].isnumeric():
                    play_commands(commandslist=[None, commandslist[0][1]])
            except Exception:
                raise

        elif commandslist in [['clear'], ['cls']]:
            os.system('cls' if os.name == 'nt' else 'clear')

        elif commandslist == ['p']:
            if len(commandslist) == 1:
                playpausetoggle()

        # TODO: Refactor to replace two `err` funcs with one
        elif commandslist[0].isnumeric(): # Check if only a number is entered
            global _sound_files
            if len(commandslist) == 1:
                if int(commandslist[0]) > 0:
                    try:
                        print(_sound_files_names_only[int(commandslist[0])-1])
                    except IndexError:
                        err('Out of range', f'Please input song number between 1 and {len(_sound_files)}')
                else:
                    err('Out of range', f'Please input song number between 1 and {len(_sound_files)}')

        elif commandslist[0] == '.':
            if commandslist != ['.']:
                path = ' '.join(commandslist[1:])
                if os.path.isfile(path):
                    if os.path.splitext(path)[1] in supported_file_exts:
                        print(1)
                    else:
                        print(0)
                else:
                    print(0)

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
                    print(f"Found {len(searchresults)} matches for: {' '.join(myquery)}")
                    print(tbl(searchresults, tablefmt='mysql', headers=('#', 'Song')))
                else:
                    print("-- No results found --")

        elif commandslist == ['stop']:
            stopsong()

def mainprompt():
    while True:
        try:
            command = input(')> ')
            outcode = process(command)

            if outcode == False:
                exitplayer()
        except KeyboardInterrupt:
            print()


def showbanner():
    global visible
    if visible:
        try:
            with open('banner.banner', encoding='utf-8') as file:
                print(file.read())
        except IOError:
            pass

def loadsettings():
    global SETTINGS

    with open('settings/config.yml') as file:
        SETTINGS = yaml.load(file)

def startprocesses():
    pass

def run():
    if sys.platform != 'win32':
        sys.exit('This program cannot work on Non-Windows Operating Systems')
    else:
        pygame.mixer.init()
        loadsettings()
        showbanner()

        p1 = Process(target=liveplaystatus)
        p1.start()

        p2 = Process(target=mainprompt)
        p2.start()

        p1.join()
        p2.join()

        mainprompt()

if __name__ == '__main__':
    run()


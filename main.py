
import os
import itertools
import sys
import pygame

from tabulate import tabulate as tbl
from ruamel.yaml import YAML
from collections.abc import Iterable

yaml = YAML(typ='safe') # Allows for safe YAML loading


try:
    with open('log.log', encoding='utf-8') as logfile:
        paths = logfile.read().splitlines()
except IOError:
    sys.exit('Could not open log file for paths')


audio_file_exts = '.wav'.split()  # Supported file extensions
curdir = os.path.dirname(os.path.realpath(__file__))
os.chdir(curdir)

# Extract files from these folders recursively Part 1 of 2
def audio_file_gen(Dir, ext):
    for root, dirs, files in os.walk(Dir):
        for filename in files:
            if os.path.splitext(filename)[1] == ext:
                yield os.path.join(root, filename)


# Flattens list of any depth
def flatten(l):
    for el in l:
        if isinstance(el, Iterable) and not isinstance(el, (str, bytes)):
            yield from flatten(el)
        else:
            yield el


# Extract files from these folders recursively Part 2 of 2
_sound_files = [[list(audio_file_gen(paths[j], audio_file_exts[i]))
                 for i in range(len(audio_file_exts))] for j in range(len(paths))]
_sound_files = list(flatten(_sound_files)) # Flattening irregularly nested sound files

_sound_files_names_only = [os.path.splitext(os.path.split(i)[1])[0] for i in _sound_files]
_sound_files_names_only_enumerated = list(enumerate(_sound_files_names_only))

isplaying = False
currentsong = None # No song playing initially

pygame.mixer.init()

def exitplayer():
    sys.exit('Exiting...')

def playsong(songpath, songindex):
    global isplaying, currentsong

    try:        
        pygame.mixer.music.load(songpath)        
        pygame.mixer.music.play()
        isplaying = True
        currentsong = songpath
        print(f':: {_sound_files_names_only[int(songindex)-1]}')
    except:
        print(f'Failed to play: {os.path.splitext(os.path.split(songpath)[1])[0]}')

def playpausetoggle():
    global isplaying, currentsong

    try:
        if isplaying:
            pygame.mixer.music.pause()
            isplaying = False
        else:
            pygame.mixer.music.unpause()
            isplaying = True
    except:
        print(f'Failed to toggle play/pause: {currentsong}')

def stopsong():
    try:
        pygame.mixer.music.stop()
    except Exception:
        print(f'Failed to stop: {currentsong}')

def err(error_topic='', message=''):
    print(f'ERROR {error_topic}')
    print('  '+message)

def searchsongs(query):
    print(_sound_files_names_only_enumerated)
    out = [i for i in _sound_files_names_only if query.lower() in i.lower()]
    return out

def process(command):
    global _sound_files_names_only
    commandslist = command.strip().split()

    if commandslist in [['exit'], ['quit'], ['q']]: # Quitting the player
        # perm = input('Do you want to exit? [Y]es, [N]o [default]: ')
        # if perm.strip().lower() == 'y':
        #     return False

        return False

    if commandslist != []: # Atleast 1 word
        if commandslist == ['all']:
            print(tbl([(i+1, j) for i, j in enumerate(_sound_files_names_only)], tablefmt='plain'))

        elif commandslist[0].lower() == 'play':
            if len(commandslist) == 2:
                songindex = commandslist[1]
                if songindex.isnumeric():
                    if int(songindex) in range(len(_sound_files)+1):
                        playsong(_sound_files[int(songindex)-1], songindex=songindex)
                    else:
                        err('Out of range', f'Please input song number between 1 and {len(_sound_files)}')

        elif commandslist[0].lower() == 'p':
            if len(commandslist) == 1:
                playpausetoggle()

        elif commandslist[0].lower().isnumeric(): # Check if only a number is entered
            if len(commandslist) == 1:
                print(_sound_files_names_only[int(commandslist[0])-1])

        if os.path.isfile(commandslist[0].lower()):
            if len(commandslist) == 1:
                print(1)

        if not os.path.isfile(commandslist[0].lower()):
            if len(commandslist) == 1:
                print(0)

        if commandslist[0].lower():
            if len(commandslist) > 1:
                myquery = ' '.join(commandslist[1:])
                searchresults = (searchsongs(query=myquery))
                print(tbl([[i] for i in searchresults]))

def mainprompt():
    while True:
        command = input('/> ')
        outcode = process(command)

        if outcode == False:
            exitplayer()
            break

def showbanner():
    try:
        with open('banner.banner', encoding='utf-8') as file:
            print(file.read())
    except IOError:
        pass

def loadsettings():
    global SETTINGS

    with open('settings/config.yml') as file:
        SETTINGS = yaml.load(file)

def run():
    if sys.platform != 'win32':
        sys.exit('This program cannot work on non Windows Operating Systems')
    else:
        loadsettings()
        showbanner()
        mainprompt()

if __name__ == '__main__':
    run()


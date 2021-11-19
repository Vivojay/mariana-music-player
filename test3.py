
import os
import itertools
import sys

from ruamel.yaml import YAML
from collections.abc import Iterable

yaml = YAML(typ='safe') # Allows for safe YAML loading

# We want files from these folders
# paths = [
#     r'D:\FL Utils\Downloaded Songs',
#     r'D:\C DOWNLOADS',
#     r'C:\Users\Vivo Jay\Desktop',
# ]

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


def exitplayer():
    print('Exiting...')


def process(command):
    commandslist = command.strip().split()

    if commandslist in [['exit'], ['quit'], ['q']]: # Quitting the player
        perm = input('Do you want to exit? [Y]es, [N]o [default]: ')
        if perm.strip().lower() == 'y':
            return False

    if commandslist != []:
        print(commandslist)


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

# sound_files_by_types

# # Creating empty file holders
# flac_files = []
# mp3_files = []
# wav_files = []
# aac_files = []
# ogg_files = []
# pcm_files = []
# aiff_files = []
# wma_files = []
# alac_files = []

# sound_files = []

# #Populating file holders with file corresponding paths
# for i in range(0, len(paths)):
#     flac_files.extend(list(audio_file_gen(paths[i], audio_file_exts[0])))
#     mp3_files.extend(list(audio_file_gen(paths[i], audio_file_exts[1])))
#     wav_files.extend(list(audio_file_gen(paths[i], audio_file_exts[2])))
#     aac_files.extend(list(audio_file_gen(paths[i], audio_file_exts[3])))
#     ogg_files.extend(list(audio_file_gen(paths[i], audio_file_exts[4])))
#     pcm_files.extend(list(audio_file_gen(paths[i], audio_file_exts[5])))
#     aiff_files.extend(list(audio_file_gen(paths[i], audio_file_exts[6])))
#     wma_files.extend(list(audio_file_gen(paths[i], audio_file_exts[7])))
#     alac_files.extend(list(audio_file_gen(paths[i], audio_file_exts[8])))

# flac_files.sort()
# mp3_files.sort()
# wav_files.sort()
# aac_files.sort()
# ogg_files.sort()
# pcm_files.sort()
# aiff_files.sort()
# wma_files.sort()
# alac_files.sort()
# sound_files.sort()

# sound_files.append(mp3_files)
# sound_files.append(wav_files)
# sound_files.append(flac_files)
# sound_files.append(ogg_files)
# sound_files.append(aac_files)
# sound_files.append(aiff_files)
# sound_files.append(alac_files)
# sound_files.append(wma_files)
# sound_files.append(pcm_files)

# flat_sound_files = [i for j in sound_files for i in j]
# k = [i.split('\\')[-1].lower() for i in flat_sound_files]

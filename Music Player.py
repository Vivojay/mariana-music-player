#Require support for:
#
#    ffmpeg
#    wav
#    mp3
#    ogg vorbis
#    alac
#    aac
#    pcm
#    wma
#    aiff

def printbanner():
    print('-'*20)
    print('[Vivo Music]')
    print('-'*20)
    print()

    print('Type "help" for information\n')

printbanner()

from playsound import playsound
from os.path import dirname, join as pjoin

import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import winsound

#from scipy.io import wavfile
from pygame import mixer
from subprocess import call

# supported_formats= ['mp3', 'wav', 'ogg Vorbis']
supported_formats= ['mp3', 'wav']

audio_file_exts = ('.flac', '.mp3', '.wav', '.aac', '.ogg', '.pcm', '.aiff', '.wma', '.alac')

Help = r"""______________________________
                              
<Vivo Music Help>
______________________________
--------------
:: Commands ::
--------------

Show
    mp3 2				    Show 2nd mp3 song
    <n> (number)			    Show nth song
    all				    	    Show all songs
    <search term>		    	    Show all songs matching search

Play
    play all				    Play all songs in alp order
    play all shuffle			    Play all songs in random order
    play all shuffle repeat		    Play all songs in random order and repeat order
    play all mp3			    Play all mp3 songs on alp order

Repeat
    play mp3 3				    Plays 3rd mp3 file
    play mp3 3 repeat			    Play 3rd mp3 song on repeat

Search
    play <search terms>			    Play all song matching search on repeat
    play <search terms> repeat		    Play all song matching search on repeat
    play <search terms> 3 repeat	    Play 3rd song matching search on repeat

Search and repeat
    play mp3 <search terms>		    Plays first song matching mp3 search
    play mp3 <search terms> repeat	    Plays first song matching mp3 search on repeat
    play mp3 <search terms> 3 repeat	    Plays 3rd song matching mp3 search on repeat

Try out other combinations! There is no rule for correct order of commands
*Note: One cannot show songs on shuffle or repeat, only play
"""

if not os.path.exists('log.log'):
    paths = input('Please enter dir paths separated by commas: ')
    paths = paths.replace(', ', ',').split(',')
    print(paths)

    with open('log.log', 'w') as f:
        f.write('\n'.join(paths))

else:
    with open('log.log') as f:
        paths = (f.read().split('\n'))

#path = paths[0]
#l = os.walk(paths[1]+'\\Others')
#files = list(l)

def err():
    print('Error, ', CMD, '< is an invalid command', sep = '')
def errFileNum():
    print('Error, ', CMD, '< is not a valid file number, try another', sep = '')

def audio_file_gen(Dir, ext):
    for root, dirs, files in os.walk(Dir):
        for filename in files:
            if os.path.splitext(filename)[1] == ext:
                yield os.path.join(root, filename)
                
def all_audio_file_gens(Dir):
    for root, dirs, files in os.walk(Dir):
        for filename in files:
            if os.path.splitext(filename)[1] in audio_file_exts:
                yield os.path.join(root, filename)

# Creating empty file holders
flac_files = []
mp3_files = []
wav_files = []
aac_files = []
ogg_files = []
pcm_files = []
aiff_files = []
wma_files = []
alac_files = []
sound_files = []

ispaused = True

#Populating file holders with file corresponding paths
for i in range(0, len(paths)):
    flac_files.extend(list(audio_file_gen(paths[i], audio_file_exts[0])))
    mp3_files.extend(list(audio_file_gen(paths[i], audio_file_exts[1])))
    wav_files.extend(list(audio_file_gen(paths[i], audio_file_exts[2])))
    aac_files.extend(list(audio_file_gen(paths[i], audio_file_exts[3])))
    ogg_files.extend(list(audio_file_gen(paths[i], audio_file_exts[4])))
    pcm_files.extend(list(audio_file_gen(paths[i], audio_file_exts[5])))
    aiff_files.extend(list(audio_file_gen(paths[i], audio_file_exts[6])))
    wma_files.extend(list(audio_file_gen(paths[i], audio_file_exts[7])))
    alac_files.extend(list(audio_file_gen(paths[i], audio_file_exts[8])))

    sound_files.extend(list(all_audio_file_gens(paths[i])))

def PlaySound(SoundFile):
    global ispaused
    try:
        mixer.init()
        mixer.music.load(SoundFile)
        mixer.music.play()
        print('Now Playing:', (SoundFile).split('\\')[-1])
    
        ispaused = False

    except:
        try:
            winsound.PlaySound(SoundFile, winsound.SND_ASYNC)
            print('Now Playing:', (SoundFile).split('\\')[-1])
        except:
            print('Can\'t play sound. [Check list of supported file formats with "help"]!')

        ispaused = True

def StopSound():
    try:
        winsound.PlaySound(None, winsound.SND_PURGE)
    except:
        pass
    try:
        mixer.music.stop()
        ispaused = True
    except:
        pass

def PauseToggleSound():
    global ispaused
    if ispaused:
        try:
            mixer.music.unpause()
            ispaused = False
        except:
            print('ERROR: Unable to pause sound')

    else:
        try:
            mixer.music.pause()
            ispaused = True
        except:
            print('ERROR: Unable to pause sound')


# Now you can call the PlaySound(mp3_or_wav_audio_file_name) function to listen to a
# wav or mp3 sound file
#E.g.

# PlaySound(mp3_files[2])

def console():
    global CMD
    CMD = input('\\> ')

    if CMD == '' or CMD.isspace():
        console()
    elif CMD == 'exit':
        print('Exiting...')

    elif CMD == 'stop':
        StopSound()
        console()

    elif CMD == 'p':
        PauseToggleSound()
        console()

    elif CMD == 'files':
        for i in sound_files:
            print(' '*4+i.split('\\')[-1])
        console()
    elif CMD == 'mp3 files':
        for i in mp3_files:
            print(' '*4+i.split('\\')[-1])
        console()
    elif CMD == 'wav files':
        for i in wav_files:
            print(' '*4+i.split('\\')[-1])
        console()
    elif CMD == 'ogg files':
        for i in ogg_files:
            print(' '*4+i.split('\\')[-1])
        console()
    elif CMD == 'wma files':
        for i in wma_files:
            print(' '*4+i.split('\\')[-1])
        console()
    elif CMD == 'flac files':
        for i in flac_files:
            print(' '*4+i.split('\\')[-1])
        console()
    elif CMD == 'aiff files':
        for i in aiff_files:
            print(' '*4+i.split('\\')[-1])
        console()
    elif CMD == 'alac files':
        for i in alac_files:
            print(' '*4+i.split('\\')[-1])
        console()
    elif CMD == 'aac files':
        for i in aac_files:
            print(' '*4+i.split('\\')[-1])
        console()
    elif CMD == 'pcm files':
        for i in pcm_files:
            print(' '*4+i.split('\\')[-1])
        console()

    elif CMD.startswith(('mp3 ', 'wav ', 'ogg ')):
        if CMD.split()[-1].isnumeric() and len(CMD.split()) == 2:
            try:
                if CMD.startswith('mp3 ') and CMD.split()[1].isnumeric():
                    PlaySound(mp3_files[int(CMD.split()[1]) - 1])
                    
                if CMD.startswith('wav ') and CMD.split()[1].isnumeric():
                    PlaySound(wav_files[int(CMD.split()[1]) - 1])

                if CMD.startswith('ogg ') and CMD.split()[1].isnumeric():
                    PlaySound(ogg_files[int(CMD.split()[1]) - 1])
                console()
            except:
                errFileNum()
                console()

        elif not CMD.split()[-1].isnumeric():
            out = [i for i in mp3_files if CMD.split()[-1] in i]
            for i in out:
                print(' '*4+i)
            console()

        elif not CMD.split()[-1].isnumeric():
            out = [i for i in mp3_files if CMD.split()[-1] in i]
            for i in out:
                print(' '*4+i)
            console()
        
        else:
            pass

    elif CMD == 'help':
        print(Help)
        console()

    else:
        err()
        console()

console()

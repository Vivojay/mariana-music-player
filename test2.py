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
 
print('-'*20+'\n[Vivo Music]\n'+'-'*20+'\nType "help" for information\n')

from playsound import playsound
from os.path import dirname, join as pjoin

import os
import threading
import re
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import winsound

#from scipy.io import wavfile
from pygame import mixer
from subprocess import call


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

Supported formats
    supported formats                       Displays list of supported formats

Try out other combinations! There is no rule for correct order of commands
*Note: One cannot show songs on shuffle or repeat, only play
"""


# Variables
supported_formats= ['mp3', 'wav', 'ogg Vorbis']
audio_file_exts = ('.flac', '.mp3', '.wav', '.aac', '.ogg', '.pcm', '.aiff', '.wma', '.alac')

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
"""             
def all_audio_file_gens(Dir):
    for root, dirs, files in os.walk(Dir):
        for filename in files:
            if os.path.splitext(filename)[1] in audio_file_exts:
                yield os.path.join(root, filename)
"""

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

flac_files.sort()
mp3_files.sort()
wav_files.sort()
aac_files.sort()
ogg_files.sort()
pcm_files.sort()
aiff_files.sort()
wma_files.sort()
alac_files.sort()
sound_files.sort()

sound_files.append(mp3_files)
sound_files.append(wav_files)
sound_files.append(flac_files)
sound_files.append(ogg_files)
sound_files.append(aac_files)
sound_files.append(aiff_files)
sound_files.append(alac_files)
sound_files.append(wma_files)
sound_files.append(pcm_files)

flat_sound_files = [i for j in sound_files for i in j]
k = [i.split('\\')[-1].lower() for i in flat_sound_files]

def PlaySound(SoundFile):
    try:
        mixer.init()
        mixer.music.load(SoundFile)
        mixer.music.play()
        print('Now Playing:', (SoundFile).split('\\')[-1])
        pausetoggle = 0

    except:
        try:
            winsound.PlaySound(SoundFile, winsound.SND_ASYNC)
            print('Now Playing wav:', (SoundFile).split('\\')[-1])
            pausetoggle = 0
        except:
            print('Can\'t play sound. [Check list of supported file formats with "help"]!')

def PlaySoundWait(SoundFile):
    try:
        mixer.init()
        mixer.music.load(SoundFile)
        mixer.music.play()
        print('Now Playing:', (SoundFile).split('\\')[-1])

    except:
        try:
            winsound.PlaySound(SoundFile, winsound.SND_FILENAME)
            print('Now Playing:', (SoundFile).split('\\')[-1])
        except:
            print('Can\'t play sound. [Check list of supported file formats with "help"]!')

def play_multi(x):
    global flat_sound_files
    for i in x:
        playsound(flat_sound_files)

def StopSound():
    try:
        winsound.PlaySound(None, winsound.SND_PURGE)
    except:
        pass
    try:
        mixer.music.stop()
    except:
        pass

def PlaySearch(q):
    if len(q.split()) == 1:
        q = 'search '+q

    res = [flat_sound_files[k.index(i.split(':')[1][1:])] for i in Search(q)]

    for i in res:
        PlaySoundWait(i) #One after the other -- Please change

def PlayDeepSearch(q):
    if len(q.split()) == 1:
        q = 'search '+q

    res = [flat_sound_files[k.index(i.split(':')[1][1:])] for i in DeepSearch(q)]

    for i in res:
        PlaySoundWait(i) #One after the other -- Please change

def DeepSearch(q, K = k):
    out = []
    q = set(q.lower().split()[1:])

    for i in k:
        if all(j in i for j in q):
            out.append(str(K.index(i))+':\t'+i)

    return out

def Search(q, K = k):
    global out
    out = []
    #a = re.sub('[^a-zA-Z0-9\n\.]', ' ', k).split('.')[:-1]
    q = set(q.split())

    for x in k:
        a = re.sub('[^a-zA-Z0-9\n\.]', ' ', x).split('.')[:-1]
        a = [' '.join(a)]
        for i in a:
            if q.issubset(set( i.split() )):
                out.append(str(k.index(x)+1)+'\t'+x)

    return out

# Now you can call the PlaySound(mp3_or_wav_audio_file_path) function to listen to a
# wav or mp3 sound file
#E.g.

# PlaySound(mp3_files[2])

pausetoggle = 0

def console():
    global CMD, flat_sound_files, k, pausetoggle
    CMD = input('\\> ')

    if CMD == '' or CMD.isspace():
        console()
    elif CMD == 'exit':
        print('Exiting...')
        StopSound()

    elif CMD == 'stop':
        StopSound()
        console()

    elif not 'play' in CMD and not CMD == 'p':
        if CMD == 'all':
            if not mp3_files == []:
                print()
                print('mp3 files ['+str(len(mp3_files))+']')
                print('-'*80)
                for i in mp3_files:
                    print(mp3_files.index(i)+1, '\t'+i)

            if not wav_files == []:
                print()
                print('wav files ['+str(len(wav_files))+']')
                print('-'*80)
                for i in wav_files:
                    print(wav_files.index(i)+1, '\t'+i)

            if not flac_files == []:
                print()
                print('flac files ['+str(len(flac_files))+']')
                print('-'*80)
                for i in flac_files:
                    print(flac_files.index(i)+1, '\t'+i)

            if not ogg_files == []:
                print()
                print('ogg files ['+str(len(ogg_files))+']')
                print('-'*80)
                for i in ogg_files:
                    print(ogg_files.index(i)+1, '\t'+i)

            if not aiff_files == []:
                print()
                print('aiff files ['+str(len(aiff_files))+']')
                print('-'*80)
                for i in aiff_files:
                    print(aiff_files.index(i)+1, '\t'+i)

            if not alac_files == []:
                print()
                print('alac files ['+str(len(alac_files))+']')
                print('-'*80)
                for i in alac_files:
                    print(alac_files.index(i)+1, '\t'+i)

            if not aac_files == []:
                print()
                print('aac files ['+str(len(aac_files))+']')
                print('-'*80)
                for i in aac_files:
                    print(aac_files.index(i)+1, '\t'+i)

            if not wma_files == []:
                print()
                print('wma files ['+str(len(wma_files))+']')
                print('-'*80)
                for i in wma_files:
                    print(wma_files.index(i)+1, '\t'+i)

            if not pcm_files == []:
                print()
                print('pcm files ['+str(len(pcm_files))+']')
                print('-'*80)
                for i in pcm_files:
                    print(pcm_files.index(i)+1, '\t'+i)

            print()
            console()

        elif CMD.isnumeric():
            print((flat_sound_files[int(CMD)-1]).split('\\')[-1])
            console()

        elif len(CMD.split()) == 2 and CMD.split()[1].isnumeric():
            try:
                print(eval(CMD.split()[0]+"_files")[int(CMD.split()[1])-1])
                console()
            except:
                try:

                    k = [i.split('\\')[-1].lower() for i in flat_sound_files]
                    q = set(CMD.lower().split())

                    for i in k:
                        if q.issubset(set(i.split())):
                            print(i)
                    console()
                except:
                    err()
                    console()

        elif len(CMD.split()) >= 2 and not CMD.split()[1].isnumeric() and not CMD.split()[0] == 'search':
            try:
                print()
                print(len(Search(CMD)), 'result(s)')
                print('-'*80)
                print()
                for i in Search(CMD):
                    print(i)
                console()
            except:
                print('Search Error')
                console()

        elif CMD.split()[0] == 'search':
            try:
                print()
                print(len( Search(' '.join(CMD.split()[1:])) ), 'result(s)')
                print('-'*80)
                print()
                for i in Search(' '.join(CMD.split()[1:])):
                    print(i)
                console()
            except:
                print('Search Error')
                console()

        elif ' ' not in CMD:
            try:
                for i in eval(CMD+"_files"):
                    print(i)
                console()
            except:
                err()
                console()

        else:
            err()
            console()

    elif 'play' in CMD:
        if len(CMD.split()[1:]) == 1:
            if CMD.split()[1].isdigit():
                num = int(CMD.split()[1])
                PlaySound(flat_sound_files[num-1])
            else:
                for t in ([i.split('\t')[1] for i in Search(CMD.split()[1])]):
                    #print(flat_sound_files[k.index(t)])
                    song_thread = threading.Thread(target = play_multi)
                    playsound(flat_sound_files[k.index(t)])
        
        pausetoggle = 1

        console()

    elif CMD == 'p':
        if pausetoggle == 0:
            pausetoggle = 1
        else:
            pausetoggle = 0

        try:
            if pausetoggle == 1:
                mixer.music.pause()
            else:
                mixer.music.unpause()
        except:
            pass

        console()

    elif CMD == 'help':
        print(Help)
        console()

    else:
        err()
        console()

console()

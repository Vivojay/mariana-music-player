# Mariana Music Player (v0.3.2)

## About
Feature rich command-line music player for Windows OS (Tested on Win10 only). \
Can play songs of [supported file types](some/path) and perform basic music control operations \
alongwith some [advanced controls and manipulations](some/other/path)

## Setup

### Step 1
#### Install Python3
You first need a python version < 3.10 from [www.python.org](https://www.python.org) \*  
To setup, you then need to install a supported version of the `llvmlite` wheel for python from [this site](https://www.lfd.uci.edu/~gohlke/pythonlibs/#llvmlite)  

### Step 2
#### Create and activate a python virtual environment
cd (or `sl` if using powershell) to the directory where you have installed the music player folder
Open cmd in explorer by typing cmd in the top address bar

#### Here's how to choose the correct llvmlite wheel version
Step 1.2: Choosing the version number
![image](https://user-images.githubusercontent.com/67545205/147437848-6ea54b96-afd3-4af4-98be-ef0f52f44fa7.png)

Step 1.3: Choosing the correct platform
![image](https://user-images.githubusercontent.com/67545205/147438943-07dbd825-a522-47f5-9623-942f31b6db1c.png)

### Step 2
Run: `py -m pip install git+https://github.com/Vivojay/pafy@develop`

Run `pip install <llvmlite_wheel_file_name>`  

E.g. `pip install llvmlite‑0.37.0‑cp39‑cp39‑win_amd64.whl`  
Now, Install PyPI modules from pip using `pip install -r requirements.txt`  

Now you need to install a release of ffmpeg from their official site at [www.ffmpeg.org](https://ffmpeg.org/download.html)  
and then VLC media player from their [official site]('videolan.com/vlc') with the same architecture (32 or 64 bit) as your python version.

Architecture match between VLC and Python (v < 3.10) is critical for python-vlc binding to install properly.


## Technical
This program uses the pygame module for playing and controlling songs stored locally.
This program also uses the vlc module for playing and controlling songs streamed from the internet.

### pygame module
Pygame requires you to first initialize its mixer object by calling the init function `pygame.mixer.init()`

Then you can load a song with `pygame.mixer.music.load( "path-to-file.ext" )`

Finally to play, pause, mute, unmute, set volume, queue, and stop song \
you can do it all using the `pygame.mixer.music` as follows:
- `pygame.mixer.music.play()`
- `pygame.mixer.music.pause()`
- `pygame.mixer.music.set_volume(0)`
- `pygame.mixer.music.set_volume(cached-volume-as-percentage)`
- `pygame.mixer.music.set_volume(desired-volume-as-percentage)`
- `pygame.mixer.music.queue('next_song')`

### VLC binding for python (python-vlc)
First, a VLC instance is created with `vlc.Instance()`  
E.g. `player = vlc.Instance()`, then we unset its logs to reduce the unecessary output on screen when adding media to this player  
i.e. `player.log_unset()`  

Get some media streaming url like and pass it to `player.media_new`  

E.g. `media_streaming_url = http://sa.mp3.icecast.magma.edge-access.net:7200/sc_rad41`  

Then new media_list_new and MediaPlayer instances are created  
and finally this media_list is inserted into the MediaPlayer  
```
media = player.media_new(media_streaming_url)

media_list = player.media_list_new()
media_list.add_media(media)

vlc_media_player = player.media_list_player_new()
vlc_media_player.set_media_list(media_list)
```

## Usage
Run `main.py` from command line (**with desired arguments, for more details, [look here](https://github.com/Vivojay/mariana-music-player/blob/main/help_future.md#command-line-flags)).  

<hr>

\*This player requires **Python version < 3.10** (exclusive of 3.10 itself) and will otherwise not work, because there are currently no unofficial binaries available for the _llvmlite wheel_ which is in turn required by the _librosa_ module.

\*\*Currently, this feature is sunimplemented... there are no command line flags available yet...
Also, interactive help documentation and interactive loading throbber/print statement need to be added.

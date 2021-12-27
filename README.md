# Mariana Music Player (v0.3.2)

## About
Feature rich command-line music player. \
Can play songs of [supported file types](some/path) and perform basic music control operations \
alongwith some [advanced controls and manipulations](some/other/path)

## Setup
To setup, you need to first install a supported version of the `llvmlite` wheel for python from [this site](https://www.lfd.uci.edu/~gohlke/pythonlibs/#llvmlite)

### Here's how to choose the correct llvmlite wheel version
Step 1: Choosing the version number
![image](https://user-images.githubusercontent.com/67545205/147437848-6ea54b96-afd3-4af4-98be-ef0f52f44fa7.png)

Step 2: Choosing the correct platform
![image](https://user-images.githubusercontent.com/67545205/147438943-07dbd825-a522-47f5-9623-942f31b6db1c.png)


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
Install PyPI modules from pip using `pip install -r requirements.txt` \
Run `main.py` from command line with desired arguments, for more details, [look here](rick/roll).

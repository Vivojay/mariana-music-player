# Mariana Music Player (v0.3.2)

## About
Feature rich command-line music player for Windows OS (Tested on Win10 only). \
Can play songs of [supported file types](some/path) and perform basic music control operations \
alongwith some [advanced controls and manipulations](some/other/path)

## Setup

### Step 1
#### Install Python3
You first need a python version < 3.10 from [www.python.org](https://www.python.org) \*  
Make sure to check the _"Add python to PATH"_ checkbox in the python installer before starting installation...  

### Step 2
#### Create and activate a python virtual environment

**Step 2.1**: cd (or `sl` if using powershell) to the directory where you have installed the music player folder  
Open cmd in explorer by typing cmd in the top address bar  

Type `py -m virtualenv -p="<path to your python < 3.10 executable>" .virtenv`  
E.g. In my case, I had python 3.9.5 installed at location: "C:\Users\Vivo Jay\AppData\Local\Programs\Python\Python39\python.exe"  
So I ran `py -m virtualenv -p="C:\Users\Vivo Jay\AppData\Local\Programs\Python\Python39\python.exe" .virtenv`  
You may have your python installation done in a similar location, try for your own path and run the command...  

In the same location run `.\.virtenv\Scripts\activate` and wait for a `(.virtenv)` prompt in your terminal, if this happens and you get no   error, you have successfully activated your newly created virtualenv with the specific supported python version.  

#### Install correct llvmlite wheel version
To setup, you then need to install a compatible version of the `llvmlite` wheel for python from [this site](https://www.lfd.uci.edu/~gohlke/pythonlibs/#llvmlite)  

**How to choose the right version of this wheel**  
**Step 2.2:** Choosing the version number  
![image](https://user-images.githubusercontent.com/67545205/147437848-6ea54b96-afd3-4af4-98be-ef0f52f44fa7.png)

**Step 2.3:** Choosing the correct platform  
![image](https://user-images.githubusercontent.com/67545205/147438943-07dbd825-a522-47f5-9623-942f31b6db1c.png)

**Step 2.4:** Run `pip install <llvmlite_wheel_file_name>`  
(E.g. `pip install llvmlite-0.37.0-cp39-cp39-win_amd64.whl`)  

### Step 3
Install git module. If you have it installed already, jump directly to **Step 4**.  

Visit [this site](https://www.git-scm.com/downloads) and download git for your system...  
Once downloaded, run the git installer with default settings...  

### Step 4
Now you need to install a release of ffmpeg from their official site at [www.ffmpeg.org](https://ffmpeg.org/download.html)  
Once downloaded, extract the downloaded zip file to a known location (E.g. "C:\Users\Admin\Desktop")  
Now copy the path to that directory (and not the extracted file itself) and add this to the system variables path ([see here for a short tutorial](https://www.youtube.com/watch?v=r1AtmY-RMyQ))  

### Step 5
Download VLC media player from their [official site]('https://www.videolan.org/') with the same architecture (32 or 64 bit) as your python version.  
Architecture match between VLC and Python (v < 3.10) is critical for python-vlc binding to install properly.  

### Step 6
Now, you must restart your terminal for path variables to refresh and take effect.  
Again cd to your .virtenv directory and activate it (Either with `.\.virtenv\Scripts\activate` or just `.\Scripts\activate` if you're already in .virtenv)  


**Step 6.1**: Run: `py -m pip install git+https://github.com/Vivojay/pafy@develop`  
**Step 6.2**: Now, Install PyPI modules from pip using `pip install -r requirements.txt`  
**Step 6.3*: That's it, setup is complete. Now just take a moment to go through the `help.md` file and get a look at the available commands and their syntax/usage rules...  

**Step 6.4**: Finall, run your app either with or without command line flags (flags may be provided in the `help.md`, if not so, then flags have not yet been implemented and will not work)  

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

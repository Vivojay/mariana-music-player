# Mariana Music Player (v0.6.2 dev-6)

## About
Feature rich command-line music player for Windows OS (Tested on Win10 only\*).   
Can play songs of [supported file types](https://github.com/Vivojay/mariana-music-player/blob/dev/settings/system.toml#L18) and perform basic music control operations  
`.wav` formats don't support seeking

## Setup

### Step 0

#### NOTE:

Do not install this program directly before going through these steps in order if you are new to git, python wheels and setting up virtual environments using virtualenv

### Step 1

#### Install Python3 (if not already installed)

You first need to **install a python version < 3.10**\*\* from [www.python.org](https://www.python.org)   
Make sure to check the _"Add python to PATH"_ checkbox in the python installer before starting installation...  

### Step 2

#### Install git on your system

If you have it installed already, skip directly to **Step 4**  
Visit [this site](https://www.git-scm.com/downloads) and download git for your system...  
Once downloaded, run the git installer with default settings...

Restart your terminal window for `git` to become available to it...

### Step 3

## NOTE
### You have a choice before continuing with the manual setup given below...
**There is a new kind of quick-setup (for Windows OS Only)... via the "INSTALLATION.py" file.** Click [here](https://www.dropbox.com/s/jtw33u265anaeyo/INSTALLATION.py?dl=1) to download.  
**It allows you to single-handedly download and setup this entire music player quickly and easily**  
**To try out this new easy way of installation, follow the steps given [here](#QUICK-SETUP)...**  

#### Setting up a virtual environment

Open up a *cmd* or *terminal* window

**Step 3.1:** `cd` (or `sl` if using `powershell`) to the directory where you want to install the music player folder (*any desired location is fine...*)  

**Step 3.2:** Run: `git clone https://github.com/Vivojay/mariana-music-player/`  

**Step 3.3:** `cd` to "mariana-music-player" dir (Our root folder/program folder...)  

Run `mkdir src`  
Run: `move * src/.` (Note: The period `.` is not to be excluded...) to move all files to src directory.  

**Step 3.4**: Make a virtual environment with python `virtualenv` module by  
running: `py -m pip install virtualenv`  in the terminal window

After `virtualenv` is installed, type `py -m virtualenv -p="<path_to_your_python_executable>" .virtenv`  
**E.g.** In my case, **I had python 3.9.5** installed at location: *"C:\Users\Vivo Jay\AppData\Local\Programs\Python\Python39\python.exe"*  
So I ran `py -m virtualenv -p="C:\Users\Vivo Jay\AppData\Local\Programs\Python\Python39\python.exe" .virtenv`  
You may have your python installation done in a similar location, try for your own path and run the command...  

In the same location run `.\.virtenv\Scripts\activate` and wait for a`(.virtenv)` prompt in your terminal, if this happens and you get no error, you have successfully activated your newly created virtualenv with the supported python version.  

**Step 3.5:** Run: `cd src` (change location to `src` dir)  

**Step 3.6:** Now, Install PyPI modules from pip using `pip install -r requirements.txt` (Wait for the installations to complete...)  

**Step 3.7:** Run: `py -m pip install git+https://github.com/Vivojay/pafy@develop`  

**Step 3.8:** Run: `py -m pip install --no-cache-dir comtypes` (Because comtypes throws errors on importing otherwise, [see #244 in comtypes](https://github.com/enthought/comtypes/issues/244))

### Step 4

Now you need to install a release of _ffmpeg_ from their official site at [www.ffmpeg.org](https://ffmpeg.org/download.html)  

Choosing an essential build should be enough, although you may choose to go for a full build while you're at it (you may need it for something else later...)  

Once downloaded, extract the downloaded zip file to a known location (E.g. "C:\Users\Admin\Desktop")  
Since the _ffmpeg_ project build will be an archive of the '.7z' format, to unzip and extract it, you will need to install the _7zip_ archiver from the [7zip official site](www.7zip.org)  

Now copy the path to that directory (not the path of an extracted file itself) and add this to the system variables path ([see here for a short tutorial](https://www.youtube.com/watch?v=r1AtmY-RMyQ))  

### Step 5

Download VLC media player from their [official site](https://www.videolan.org) with the same architecture (32 or 64 bit) as your python version.  
Architecture match between VLC and Python (v < 3.10) is critical for python-vlc binding to install properly. 

### Step 6 (Optional)

#### Installing llvmlite wheel for the *librosa* module (Optional as of now...)

This step explains an entirely useless installation procedure as of now.  
The llvmlite wheel *may* only be required in the future, so you may decide to skip to **Step 7** instead...

To continue with this step, you need to install a compatible version of the `llvmlite` wheel for python from [this site](https://www.lfd.uci.edu/~gohlke/pythonlibs/#llvmlite)  

**How to choose the right version of this wheel**  

**Step 6.1:** Choosing the version number  

![image](https://user-images.githubusercontent.com/67545205/147437848-6ea54b96-afd3-4af4-98be-ef0f52f44fa7.png)

**Step 6.2:** Choosing the correct platform  

![image](https://user-images.githubusercontent.com/67545205/147438943-07dbd825-a522-47f5-9623-942f31b6db1c.png)

**Step 6.3:** Run `pip install <llvmlite_wheel_file_name>`  
(E.g. `pip install llvmlite-0.37.0-cp39-cp39-win_amd64.whl`)

Now run: `py -m pip install librosa` to install librosa (which is the reason we needed the llvmlite wheel in the first place).

The *librosa* module may help in **bpm** and **key** detection of songs in the future... 

### Step 7
Now, you must restart your terminal for path variables (like *ffmpeg*) to refresh and take effect.  
**Step 7.1:** That's it, setup is complete. Now just take a moment to go through the `help.md` file and get a look at the available commands and their syntax/usage rules...  

**Step 7.2:** Finally, run your app either with or without command line flags (flags may be provided in the `help.md`, if not so, then flags have not yet been implemented and will not work)  

## Technical
This program uses the pygame module for playing and controlling songs stored locally.  
It also uses the vlc module for playing and controlling songs streamed directly from the internet.  

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
**E.g.** `player = vlc.Instance()`, then we unset its logs to reduce the unnecessary output on screen when adding media to this player  
i.e. `player.log_unset()`  

Get some media streaming url like and pass it to `player.media_new`  

**E.g.** `media_streaming_url = "http://sa.mp3.icecast.magma.edge-access.net:7200/sc_rad41"`  

Then new media_list_new and `MediaPlayer` instances are created  
and finally this media_list is inserted into the `MediaPlayer`  

```python
media = player.media_new(media_streaming_url)

media_list = player.media_list_new()
media_list.add_media(media)

vlc_media_player = player.media_list_player_new()
vlc_media_player.set_media_list(media_list)
```

Now that vlc_media_player is created, we can
control media via actions like play, pause, stop and resume.

To control the song positioning (seeking),
we can get the media player object from vlc_media_player using

`MPO = vlc_media_player.get_media_player()`
with this MPO (object), we can access more song parameters
such as..

- get/set song position
- change track within playlist (skip/prev/next)
- get/set audio volume (audio_set_volume)
etc...

<br>

## QUICK-SETUP
1. Follow all steps (1 to 7) **except Step 3**, in order...  
   i.e. Install Python (version < 3.10), git, VLC, FFMPEG (and optionally, the librosa wheel)
2. Restart all terminals
3. Download ONLY the initsetup.py file (**No other project files required**)...
4. Run it in console with command: `py "<absolute_path_to_py_file>"`  
   E.g. `py "C:\Users\Admin\Downloads\initsetup.py"`
5. Follow the instructions provided...

<br>

## Usage

Run `main.py` from command line (with desired arguments, for more details, \*\*\*[look here](https://github.com/Vivojay/mariana-music-player/blob/main/help_future.md#command-line-flags)).  

<br>

## Mariana Player in Action

![image](https://user-images.githubusercontent.com/67545205/147845057-eab483b2-4e8c-43ce-9f0d-349d2e655437.png)

<hr>

## Features
- Basic controls (mute, elapsed time, list library files, ...)
- Soft play/pause by default
- Colourful cheery interface
- Play random songs from library
- View prettified progress
- Absolute and relative seek
- Viewing, editing lyrics for downloaded songs *(only offline lyrics are supported)*
- View currently playing files (name or full path)
- Open currently playing files in windows file explorer
- View history of all played media in current session
- Listen to any one of 3 preprovided webradios
- View Reddit Sessions **(Requires a Reddit API)**
- Play directly from radio links and YouTube urls
- Play songs from direct YouTube searches
- Download songs and videos from YouTube
- Open currently playing YouTube media in browser (with synced timestamp...)
- Customisable via settings located in `settings/settings.yml`

## Known Issues
- Rarely: "ConnectionResetError": ... is shown on screen (non breaking)
- Very Rarely: "Segment fault pygame": ... breaking error
- Rarely: Random Thread Exception: ... is shown on screen (non breaking)

### Footnotes

\*Most features *may work on Linux*, but is still untested for any OS other than Win10...

\*\*This player requires **Python version < 3.10** (exclusive of 3.10 itself) and will not work otherwise, because there are currently no unofficial binaries available for the _llvmlite wheel_ compatible with Python versions >= 3.10.

The *llvmlite wheel* is in turn required by the _librosa_ module.

\*\*\*Currently, this feature is unimplemented and there are no command line flags available yet...
Also, interactive help documentation and an interactive loading *throbber/print-statement* need to be added.

```
Easter Eggs (Fun stuff)
Make into an executable release -> Host on GitHub
COLOUR OUTPUT
IMPLEMENT QUEUE PLAYING
Currently beta features are switched on by default and cannot be opted out of; Change this...

Run a "related-songs-getter" type function to get similar song to the ones you listen to
and package into a playlist (Mariana's own simple playlist format??
                             or prebuilt playlist formats e.g. m3u etc...)

MIGRATE ENTIRELY TO python-vlc FOR PLAYING SONGS OF ANY KIND(CODEC)...

Timed tagging and commenting withing songs:
    timed tagging/comenting will generate an editable yml file with some custom extension
        (maybe as an srt file??)

MAKE THE STEP-BY-STEP WIZARD FOR INITIAL SETUP A BREEZE... (Already kinda is...?)
    ASK 3 QUESTIONS                         ??? (Do we really need it?)
    TELL 3 THINGS                           ??? (Do we really need it?)
    ASK IF YOU WANT TO START APP NOW...     ??? (Do we really need it?)

Save all recursive file paths from all lib dirs in a libpaths files for quick reload 
Mark unplayable/corrupt song files and exclude them from libpaths
    Exclude the unplayable/corrupt from libpaths.yml "general" heading and shift them to "corrupt"
    These marked files WILL STILL be listed in "all" command but will not be directly searchable using the f[ind] command...
    unless the find command is issued with the extra option "c" (for corrupt)

Blacklisting will exclude the unplayable/corrupt from libpaths.yml "general" heading and shift them to "blacklist"
    These marked files WILL STILL be listed in "all" command but will not be directly searchable using the f[ind] command...
    unless the find command is issued with the extra option "b" (for corrupt)

Favourited files will be moved in libpaths.yml from "general" heading to "blacklist"
    These marked files WILL STILL be listed in "all" command but will not be directly searchable using the f[ind] command...
    unless the find command is issued with the extra option "b" (for corrupt)

Find command will be issuable with the following options:
    c: Show only corrupt/unplayable files
    b: Show only blacklisted files
    a: Show only  files
    t <tag_name>: Show only files with given tag (if multiple tags specified, then all tags mst be present)
    f: Show only favourited files
    

Many Great Visualizers (2D and 3D, color changing, other effects....)
Song Videos from youtube (if available) ... ? (May not be implemented)

Log time taken to load this cli tool on every boot and append data to data/app.yml under the "boot_params" heading

Separate error message if deleted file is attempted to be played
Make a temp folder: create ffmpeg version of wav file to mp3 (named cur_V.wav)??

Play a song with last remembered position and applied effects
Record sessions
Take regular auto backups of open sessions and offer to reopen them on next bootup
Set volume to default session volume value defined in settings (default=90)

Data for deleted files should be marked as deleted (can be prompted for later deletion if needed)
Record Main System while playing a certain song, to calculate a user's weighted liking to that song
Depending on the player and system vol, actively prevent setting volume to a value higher than some healthy threshold to avoid ear damage...
    (Show a continuous warning if this is disabled)

Make player mpre interactive if the current user's settings allow for it...

Get MFCC data from all lib songs and analyse the moods, genres, bpm (tempo), key (scale), energetics, danceability
    Write the analyzed data into a yml file called lib_analyses.yml in genres/genres folder

Set Artist name if not already mentioned in the metadata
Show lyrics in time sync if available, else show the whole lyrics on html page
    else

Quickly fingerprint audio and reliably find and separately save duplicates...
Give short summaries about user's listening habits

Make a `library` command to display all songs + their info in a tabular form (Like a CLI version of Windows File Explorer, but for sound files only)
Make small GUI display for current song progress
Record command history and logs in "historydump.log" and "generallogs.log" respectively
If a queue is requested during a play-queue, then the new queue overrides the play-queue.
In any other case, the new queue/play-queue is appended to the previous

The shuffle command will shuffle the current play-queue
The shuffle command can shuffle the current queue or any of the other requested "named queues" (Beta)
	Syntax:
		shuffle [q name]

Loops will be given preference over queues and play-queues, i.e. if a song is looped from within a queue,
then it will keep looping until the loop is closed. After the loop is closed,
the remaining queued songs will start playing as usual until the queue(s) end(s).
Make it colourful. Make display tasty and colourful with borders and themes!
If opening for the first time, find and save songs with their indices in "library.yml"
For all subsequent loads, use enumerated song paths cached in this file.
For refreshing this list, just type the refresh command and effect will take place immediately

Make an elaborate and heavily organized and detailed settings YAML file and markdown + html documentation.
Get list of available bluetooth + connected audio output devices… and highlight the current one. Define a simple command to view + change output devices
All Songs (`all`) should display in exactly 3 columns (not `library`)
Command to show now-playing/<number> in file explorer
Any and all setting changes should be saved/recorded and loaded on each startup/boot
Any and all settings must refresh and come into effect immediately upon issuing the appropriate command w/o the need for rebooting the player

Stream music directly:
	Create a "temp" directory in the program's main dir
	Convert wav to mp3 using FFMPEG
	Cast using SHOUTcast protocol

If all dirs empty, print no files warning (in the beginning)
Various type of tagging is allowed, e.g.:
	Genre
	Colour
	Custom (List of custom tags will be created, you may choose one or create new)

color code song indices by play freq:
  (Upper limits are excluded in range)
  key:	meaning	  abs(play_count)  rel (%)
    0:  never     0                0%
    1:  least     -                0-4%
    2:  less      4-15             4-10%
    3:  moderate  15-100           10-42%
    4:  more      100-inf          42-80%
    5:  most      -                80-100%

  relative plays (%) = (abs play_count)/(total play_count)*100 %

Connect to popular free radio service
Podcasts
    Connect to popular free podcast service(s)
    Allow to open a text file and read content from it in a podcast-like voice
        Using openAI perhaps?
        (beta feat: maybe add pauses, noises, crackles, etc... for a more natural podcast room/environment experience)
    Get Reddit post (podcast-like) texts from subreddits like:
    (preferably long, storylike texts)
        casualconversations
        seriousconversations
        talesfromtechsupport
        talesfromretail
        letsnotmeet
        creepyencounters
        worldnews
        financialindependence
        amitheasshole
        nosleep
        tifu
        legaladvice
        idontworkherelady
        confession
        relationships
        relationship_advice
        justnomil

Reddit RPAN - Add sync feature
Reddit sessions by famous* players:
    e.g.    @jonathandaleofficial
            @saxsquatch
            ...
Connect to popular free lyrics service (shazamio)
Hide/blacklist songs
Clear recents/history logs/etc….
Set metadata:
	Artist
	Song name
    .. (Few others?)
ReplayGain support
Easy way to rename and delete files from disk
The 'now' command should show if a 'queue' is playing or a 'sequence' or a 'play-queue'

Remote playback from/to other's systems

Copy/Replace a file into a converted format

Make Externally controllable (via keyboard keys...)?

Color coded convert() function for time!...

Use alternative: https://github.com/itspoma/audio-fingerprint-identifying-python.git
    for quicker fingerprinting and lyrics extraction...

If help or config file is not available or is corrupted, prompt user to download required files from GitHub or use default
If default file is not available or is corrupted, prompt user to download required files from GitHub or close program, play beep at the end


VAS Checklist:
    [ ] Add song stop detect; raise flag on song stop when played as VAS
    [x] Radio
    [x] Play single video as audio
    [x] Video list, pick video, play as audio
    [x] Reddit Sessions

Make everything configurable, including:
    Making commands (un)available
implement rel_val: rel_val = +5 means seek +5000 ms relative to cur pos
Make a new command t*: must show: (<abs_progress\> / <total_length\>) + (percent_complete)
Show a small GUI window for constant progress display... (Requires multiprocessing??)
Allow decimal-point time seeking for VAS media type
Make seek work for pygame? or solve it automatically by entirely migrating to VLC...

Have various user logins with completely separate encrypted data which is only decrypted once 
the user successfully logs in...

Set volume at boot to: `override_default_boot_volume` or set it to remember last session's volume

Get list of urls of `n` newly released songs from whatever sources possible (any 3rd party api or one of the moajor players listed below...)
Connect with Music Streaming Services?? E.g.
    YTMusic?
    Spotify?
    Deezer?
    SoundCloud?
    Other...
    (`n` maybe adjustable via the config/commandline/fallback_value/etc...)

Make the (ls|list) feature way more powerful and robust, migrate from (f[ind]) to (ls|list)
    i.e. deprecate (f[ind])... (but not completely remove it yet...)

Give users a short note about the fact that importing modules no.: 7, 17, 22, 23, and 24
    take a longer time than usual

ACTUALLY MAKE USE OF the `loglevel` variable, it's not just for fun :meh:
    for refs: loglevels have the following values:
        {
            0: "none",  # Don't log anything, not even fatal crashes (LIKE WHUT?)
            1: "fatal", # Only log fatalities
            2: "warn",  # Log fatalities + warnings
            3: "info",  # Log fatalities + warnings + info
            4: "debug"  # Log pretty much every single line of code, this's going to take my whole day :(
        }

-----------------------------------------------------------------------------------
Footnotes:
*They may not be that famous, but I think they're atleast regular and noticeable when I see them on r/redditsessions...
You guys can tell me more great subs/sites/people if u want, and I might add them!
```

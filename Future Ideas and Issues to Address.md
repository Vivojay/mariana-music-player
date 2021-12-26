```
Make into an executable release
COLOUR OUTPUT
IMPLEMENT QUEUE PLAYING

MAKE THE STEP-BY-STEP WIZARD FOR INITIAL SETUP A BREEZE...
    ASK IF YOU WANT TO START APP NOW...

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
Connect to popular free radio service
Connect to popular free podcast service
Connect to popular free lyrics service
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


If help or config file is not available or is corrupted, prompt user to download required files from GitHub or use default
If default file is not available or is corrupted, prompt user to download required files from GitHub or close program, play beep at the end

Have various user logins with completely separate encrypted data which is only decrypted once the user successfully logs in...
```

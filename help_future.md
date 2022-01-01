## About This Help

EBNF metasyntax is used for syntax formatting here.  
Lines written after a \` `#` \` symbol are not of any importance, they are stale unimplemented features or future ideas.

Show commands shows files matching query in 4 columns by default.  
This can be changed in the config file.

All searches are fuzzy

**Basic syntax rules are summarized as follows:**

| Command             | Description                        |
| ------------------- | ---------------------------------- |
| this \| that        | Option between values              |
| optional_ie_0_or_1? | Optional value                     |
| zero_or_more\*      | Value may occur zero or more times |
| one_or_more+        | Value may occur one or more times  |

<hr><br>

## Controls/Commands

### General

#### Legacy functions

| Command                    | Description                                                                                                                                                                                                 |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| all                        | display all sound files                                                                                                                                                                                     |
| <number\>                  | show name of \`number\`th song                                                                                                                                                                              |
| (<number\> <space\>)+ [-d] | show names of all \`number\`th songs in space separated list of numbers.<br>Display (max display count threshold) songs only..., if `-d` flag is specified, the aforementioned threshold will be overridden |

| Command             | Description                                                           |
| ------------------- | --------------------------------------------------------------------- |
| e[xit] \| q[uit]    | stop and exit after confirming, show warning if song is still playing |
| e[xit] \| q[uit] -y | stop and exit w/o confirmation, show warning if song is still playing |

#### Controlling Beta Feature

| Command      | Description                                    |
| ------------ | ---------------------------------------------- |
| beta on\|off | Enable/Disable beta functionality respectively |
| beta list    | List beta functionality consicely              |
| beta list\*  | List beta functionality in detail              |

#### Beta functions

| Command          | Description                                                                             |
| ---------------- | --------------------------------------------------------------------------------------- |
| . <filepath\>    | check if \`filepath\` is of a valid supported song file                                 |
| open             | open current song file in Windows File Explorer                                         |
| open <filepath\> | open file at \`filepath\` in Windows File Explorer if it is a valid supported song file |

| Command              | Description                                                                                                     |
| -------------------- | --------------------------------------------------------------------------------------------------------------- |
| vis                  | switch to hide interactive output/feedback from player on command success or failure                            |
| path <n\>            | show path of provided audio file                                                                                |
| now                  | show now playing song's index & name                                                                            |
| t                    | show current progress at the instant of issuing this command                                                    |
| help                 | show concise help (only the most important commands) with a link for more detailed help                         |
| restart              | restart/reboot the player                                                                                       |
| \$ \| prog           | see the progress in beautifed format                                                                            |
| l[en[gth]]           | show formatted song length                                                                                      |
| =rand                | pick random number from lib                                                                                     |
| rand                 | name of random song from lib and it's index                                                                     |
| .rand <count\>       | play a random song from lib                                                                                     |
| new <count\>         | list `count` number of new songs (default = 10) (If count > total number, list all songs)                       |
| neverplayed <count\> | list `count` number of songs which haven't been played (default = 10) (If count > total number, list all songs) |

| Command    | Description                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| .<number\> | show info of \`number\`th song, including: <br>&nbsp;&nbsp;&nbsp;&nbsp;- Song name <br>&nbsp;&nbsp;&nbsp;&nbsp;- Artist name <br>&nbsp;&nbsp;&nbsp;&nbsp;- Play length <br>&nbsp;&nbsp;&nbsp;&nbsp;- Your rating <br>&nbsp;&nbsp;&nbsp;&nbsp;- Favourited or not <br>&nbsp;&nbsp;&nbsp;&nbsp;- Recently played or not <br>&nbsp;&nbsp;&nbsp;&nbsp;- File type <br>&nbsp;&nbsp;&nbsp;&nbsp;- Shows the path of containing directory |

| Song Info Type       | Default Info Provided |
| -------------------- | --------------------- |
| **default minimal**  | name of song, ...     |
| **default basic**    | \_, \_, \_, ...       |
| **default detailed** | name of song, ...     |

\*Note: More detailed info can be found using the \`info\` command

| Command                  | Description                                                                                                                                                       |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| \*                       | Last played                                                                                                                                                       |
| \*<n\>                   | nth last played song                                                                                                                                              |
| rm <n\>                  | deletes nth song from disk (asks for premission)                                                                                                                  |
| rm <n\> -y               | deletes nth song from disk (asks for premission)                                                                                                                  |
| cp <n\> <new_path\>      | copies nth song to `new_path` with the specified name\* <br> \*If name and extension are not specified, the name becomes: <original_name\> copy <copy_count + 1\> |
| rn <number\> <new_name\> | rename song at `number` to `new_name`                                                                                                                             |

<br>

### Music Controls Overview

#### Legacy Functions

| Command            | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| p                  | pause/resume                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| s[top]             | stop                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| skip <number\>     | skip \`number\`th song                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| n[ext]             | skip to next song                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| p[rev]             | skip to previous song                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| play <number\>     | play track                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| m                  | mute/unmute                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| m? \| ism[ute]     | checks if song is mute/unmute, displays 1 if player is muted, 0 otherwise                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| seek <timeobject\> | seek to time given in \`timeobject\`, correct format for this is given below. <br> (song play/pause status stays same) <br><br> &nbsp;&nbsp;&nbsp;&nbsp; Valid/Supported Formats for timeobject <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; `<hh>:<mm>:<ss>` <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; For settings any of the above values to zero, just skip them: <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; E.g. to set timeobject as `00:03:00`, you also write `:3:` or even `3:` <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; `<mm>:<ss>` <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; `<seconds>` (number of seconds as a positive integer) <br><br> \*Note: Provided \`timeobject\` is converted to seconds for internal use in this program <br> E.g. seek 0 resets the song to the beginning |
| reset              | Same as seek 0, seeks current song to start, (song play/pause status stays same)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |

#### Beta Functions

| Commands                                                         | Description                                                                                  |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| play ((q "queue_name" \| seq "seq_name" \| <number\>) <space\>)+ | play custom sequence of queues/sequences/tracks                                              |
| (v \| vol)                                                       | display current player volume as percentage                                                  |
| (v \| vol) <percentage\>                                         | set player volume to provided percentage                                                     |
| (v \| vol) (up \| down)                                          | (increase \| decrease) volume percentage by "volumestep" param in settings (default = 5)     |
| (v \| vol) (min \| max)                                          | set volume percentage to (minimum \| maximum)                                                |
| mvol                                                             | display current main system volume as percentage                                             |
| mvol <percentage\>                                               | set main system volume to provided percentage                                                |
| mvol (up \| down)                                                | (increase \| decrease) main system volume by "mainvolumestep" param in settings (default=10) |
| mvol (min \| max)                                                | set main system volume percentage to (minimum \| maximum)                                    |
| replay l[ast]                                                    | Replay last played song from start                                                           |
| autonext                                                         | Play next song automatically after the current song ends\*                                   |

**Note:**  
\> autonext:

- Not applicable if a ([play-]queue \| sequence) is currently playing
- If no more songs are left in directory, it will play the first song from the library
- If none of the dir contain any supported song files

<hr><br>

### Playing

#### Legacy Functions

\*NOTE: All play commands override current song/queue

| Commands                      | Description                                                    |
| ----------------------------- | -------------------------------------------------------------- |
| play all                      | Play all songs in alp order                                    |
| play all shuffle              | Play all songs in random order                                 |
| play all shuffle repeat       | Play all songs in random order and repeat until repeat cleared |
| play all shuffle repeat o     | once                                                           |
| play all shuffle repeat c     | clear                                                          |
| play <ftype\>                 | Play all ftype songs in alp order                              |
| play <filepath\>              | Play file from path                                            |
| play (<filepaths\> <space\>)+ | Play files from paths one-by-one in order                      |

#### Beta Functions

| Commands             | Description                                                           |
| -------------------- | --------------------------------------------------------------------- |
| play q qname         | Play queue named \`qname\`                                            |
| /play "search query" | Search for query in Spotify, play the song in the first search result |

<hr><br>

### Queueing

#### Legacy Functions (play-queue)

| Command                                             | Description                                                                                                                                                                                                                                                                                        |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| play (<n1\> <space\>)+                              | Play all provided songs in alp order                                                                                                                                                                                                                                                               |
| add (<number\> <space\>)+                           | Adds song at `number` to end of play-queue                                                                                                                                                                                                                                                         |
| add (<number\> <space\>)+ @ (<position\> <space\>)+ | Adds song at provided number, positon pairs in play-queue, <br> if any number is out of range or invalid, that number, position pair is ignored, <br> if all number, position pairs are out of range or invalid, then addition to play-queue is aborted entirely with an appropriate error message |

E.g.

| Commands   | Description                                                                                                                                                                                |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| play 6 2 4 | Queue and Play (ORDER MATTERS): <br> Play songs 6, 2 and 4 in that order <br> Displays names of songs in a newly issued play-queue <br> Displays "current play-queue over" after it's over |
| clear      | Clear all songs except now-playing from the current play-queue                                                                                                                             |

```
# Note:
#     Queue inside the play functions isn't a named queue and it ISN'T saveable
#     Also, this queue will instantly be broken and lost if a queue command is issued
#     To safeguard against the accidental unwanted override of the current play-queue, you will be prompted to either:
#         1> override current play-queue and start a queue instead
#         2> append new queue to current play-queue
#         3> continue playing current play-queue
```

#### Beta Functions

Following 2 functions work same as for \`play (<n1\> <space\>)+\`  
(Queue names with spaces must be in quotes/double quotes)

| Commands                      | Description                                                                                                                                      |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| q n myqname                   | Create a new empty saveable queue named \`myqname\`                                                                                              |
| q n myqname (<n1\> <space\>)+ | Create a new saveable queue named \`myqname\` with all provided songs in order <br> (Repeated names will throw an error and will not be allowed) |

A new queue may start automatically when an individual song/queue ends (Can be edited in config.yml file)

| Commands                           | Description                                      |
| ---------------------------------- | ------------------------------------------------ |
| q a <number\> [qname]              | add \`number\`th item from global songs to queue |
| q r <number\> [qname]              | remove \`number\`th item from current queue      |
| q <number\> [qname] [result count] | show \`number\`th item in current queue          |
| q qname                            | prints 0 if queue is non existent, else 1        |

<hr><br>

### Finding / Searching songs

| Commands                                                   | Description                                                                                    |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| ['f' \| 'find'] "Search Query" [<results_count\>\|all]     | Find locally, 10 results by default. Shows all results if "all" is mentioned                   |
| ['/f' \| '/find'] "Search Query" [<results_count\>\|all]   | Find online from Spotify, 10 results by default. Shows all results if "all" is mentioned       |
| ['rf' \| 'rfind'] "Search Query" [<results_count\>\|all]   | Regex find locally, 10 results by default. Shows all results if "all" is mentioned             |
| ['/rf' \| '/rfind'] "Search Query" [<results_count\>\|all] | Regex find online from Spotify, 10 results by default. Shows all results if "all" is mentioned |

<hr><br>

## Beta Functions (Other than aforementioned)

### Sequencing (Operating on a collection of queues)

| Commands           | Description                                                                                                                                                                                                          |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| seq qname1 qname2+ | Minimum 2 queues required to form a sequence                                                                                                                                                                         |
| seq n myqname      | Create a new saveable sequence named \`myqname\` <br> names with spaces must be in quotes/double quotes <br> A queue may start automatically when an individualsong/sequence ends (Can be edited in config.yml file) |
| seq a <number\>    | add \`number\`th item from global songs to sequence                                                                                                                                                                  |
| seq r <number\>    | remove \`number\`th item from current sequence                                                                                                                                                                       |
| seq <number\>      | show \`number\`th item in current sequence                                                                                                                                                                           |

**Note**  
\> BTS, a new queue is created (marked as a \`sequence\` object to differentiate it from an actual \`queue\` objects, in case of name collisions).  
\> This larger "queue" contains other provided queues which were appended to it using the appropriate commands while creation of the sequence.  
\> This larger queue is marked as a sequence and is treated as one.

<hr><br>

### Cueing

**Note**
A kind of advanced seek pointer for songs
This "seek" position can be taken from current position or set manually
This "seek" position can be saved for later use
This "seek" position can also be applied to any another song whenever you want

**Save cue object for later**

| Commands              | Description                                                                                                                                      |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| cue set <timeobject\> | Set cue object to provided timeobject                                                                                                            |
| cue set .             | Set cue object to current time in current song                                                                                                   |
| cue set 0             | Set cue object to start of song                                                                                                                  |
| cue [ftype] <num\>    | Apply cue to provided song (Only one song at a time). <br> Now, whenever you play this song, it will automatically start from the set cue object |
| cue clear all         | To remove currently set cue from all songs                                                                                                       |
| cue clear songs+      | To remove currently set cue from provided songs                                                                                                  |
| cue list              | See the list of songs which have been cued to a certain timeobject <br> (i.e. cue has been applied to them but has not been cleared)             |

### Shuffling

| Commands            | Description                                                                                      |
| ------------------- | ------------------------------------------------------------------------------------------------ |
| shuffle [qname]     | If qname provided, then the songs from that q are shuffled. Otherwise, the current q is shuffled |
| shuffle nr [qrname] | Same as \`shuffle [qname]\`, but songs which have already been played are not repeated           |

### Repeating

_Note:_ re[p[eat]] means re|rep|repeat.  
So re = rep = repeat and can be used interchangeably

| Commands             | Description                                                         |
| -------------------- | ------------------------------------------------------------------- |
| re[p[eat]] c\|clear  | Currently playing object (song/queue) is marked to no longer repeat |
|                      |                                                                     |
| re[p[eat]]           | Currently playing object song is repeated/looped indefinitely       |
| re[p[eat]] o\|once   | Currently playing object song is repeated/looped once               |
|                      |                                                                     |
| re[p[eat]] t         | Currently playing track/song is repeated/looped indefinitely        |
| re[p[eat]] t o\|once | Currently playing track/song is repeated/looped once                |
|                      |                                                                     |
| re[p[eat]] q         | Currently playing queue is repeated/looped indefinitely             |
| re[p[eat]] q o\|once | Currently playing queue is repeated/looped once                     |
|                      |                                                                     |
| re[p[eat]] s         | Currently playing sequence is repeated/looped indefinitely          |
| re[p[eat]] s o\|once | Currently playing sequence is repeated/looped once                  |

### Looping Region

| Commands                             | Description                                                 |
| ------------------------------------ | ----------------------------------------------------------- |
| loop <timeobject 1\> <timeobject 2\> | Loop current song from \`timeobject 1\` to \`timeobject 2\` |
| loop c\|clear                        | Loop current song from \`timeobject 1\` to \`timeobject 2\` |

### Basic Song info

| Commands       | Description                                         |
| -------------- | --------------------------------------------------- |
| info           | Show detailed metadata info of current song         |
| info <number\> | Show detailed metadata info of song at given number |

| Commands           | Description                                                                               |
| ------------------ | ----------------------------------------------------------------------------------------- |
| /bpm               | Get BPM of current song from internet and/or from calculation/analysis                    |
| /bpm <number\>     | Get BPM of song at provided number from internet and/or from calculation/analysis         |
| /key               | Get key of current song from internet and/or from calculation/analysis                    |
| /key <number\>     | Get key of song at provided number from internet and/or from calculation/analysis         |
| /bpm key           | Get BPM and key of current song from internet and/or from calculation/analysis            |
| /bpm key <number\> | Get BPM and key of song at provided number from internet and/or from calculation/analysis |

| Commands          | Description                                                                                       |
| ----------------- | ------------------------------------------------------------------------------------------------- |
| bpm               | Get BPM of current song from saved song metadata, or return error if not found                    |
| bpm <number\>     | Get BPM of song at provided number from saved song metadata, or return error if not found         |
| key               | Get key of current song from saved song metadata, or return error if not found                    |
| key <number\>     | Get key of song at provided number from saved song metadata, or return error if not found         |
| bpm key           | Get BPM and key of current song from saved song metadata, or return error if not found            |
| bpm key <number\> | Get BPM and key of song at provided number from saved song metadata, or return error if not found |

| Commands             | Description                                                                                         |
| -------------------- | --------------------------------------------------------------------------------------------------- |
| desc[ribe] <number\> | Display mood, danceability, energy, and other such important parameters for song at provided number |

### Other Functions

lib x <directory_path\> | Load supported format songs from directory_path and extend to the currenty loaded library |
lib l <directory_path\> | Change currenty loaded library by given directory |

Songs will have special indications if

- They are new (default = Songs with a creation date within last month) [can be changed in the settings]
- They have never been played before
- They have been played only a few times (default = (<=5)) [can be changed in the settings]
- They have been played a lot of times (default = (>=50) ) [can be changed in the settings]
- They have never been played completely from start to end
- They have never been played for more than a threshold time (default = 30 sec) [can be changed in the settings]

Record and highlight library changes (modfications (metadata only), deletions, additions, new favs, new recents)
Save your trends and worldwide trends (genres and songs) in different dirs for every month alongwith related detailed stats...
Tag your songs with either predefined or custom tags

**Lyrics**: lyr[ics]  
**Stars**: star `<starscount>` <br> &nbsp;&nbsp;&nbsp;&nbsp;`<starcount>` must be 1, 2, 3, 4 or 5. Anything else will result in an error  

**Effects**  
**Note**  
Applies any of the following effects to current song  
One effect is applied at a time (Self-explantory commands have been chosen for effects)  

- `fadein|fi` (Only applicable for song start, to apply type `(fadein|fi) <song_number>`, to apply this effect to the next song, whenever it starts playing, do `(fadein|fi) next`)
- `fadeout|fo` (To apply instantly, just write `fadeout|fo`, to apply at the end, do `(fadeout|fo) .`)

<br>

- `fastforward|ff`
- `rewind`
- `flange`
- `phase`
- `detunelfo`
- `stutter`
- `nightcore|nc`
- `vaporwave|vw`

| Commands                                  | Description                                      |
| ----------------------------------------- | ------------------------------------------------ |
| schedule <timeobject\> -switch            | Schedule a music session for `timeobject`        |
| schedule <timeobject\> s[cript] <script\> | Schedule a music session script for `timeobject` |

<hr><br>

### Misc / Advanced / Power Commands

| Commands                                                                        | Description                                                                                                                  |
| ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| dirs edit                                                                       | Edit directories where songs are taken from (i.e. sources.log) <br> opening it in vscode > npp > default notepad for editing |
| refresh                                                                         | refresh file in sources.log dirs, check dirs in log.log also                                                                 |
| double numbering                                                                | global_number, ftype_number                                                                                                  |
| loglevel (none\|0) \| (fatal\|1) \| (error\|warn\|2) \| (info\|3) \| (debug\|4) | Logging                                                                                                                      |

`# silent (true | false): Switch on-screen interaction on/off`

**Config Commands**

| Commands                      | Description                                                    |
| ----------------------------- | -------------------------------------------------------------- |
| config edit                   | Open config file for editing in vscode > npp > default notepad |
| config set <new_config_path\> | Set file as config file                                        |
| config reset                  | Reset configuration                                            |
| config help                   | Shows help regarding config                                    |

**Power Commands**

| Commands | Description                          |
| -------- | ------------------------------------ |
| %cs      | Capture this session                 |
| %rs      | Repeat last session                  |
| %del     | Delete song(s) by number/path/etc... |
| %%       | Open file with all help statements   |

**Favouriting**

| Commands | Description                   |
| -------- | ----------------------------- |
| favs     | special queue for "fav songs" |
| fav a    | special queue for "fav songs" |
| fav      | special queue for "fav songs" |

**Recent Songs**

| Commands | Description                               |
| -------- | ----------------------------------------- |
| recent   | special queue for "recently played songs" |

**Analysis and Stats**

Syntax: `(secs | times | ints) <number>`

- mostlistened (song|artist) [alltime|thismonth|today|yesterday]
- stats:
  | Command | Options |
  |-|-|
  | secs | (`today` \| `date <date>` \| `month <month>` \| `year <year>`) `[ song \| artist ]` `[ partial \| complete ]` |
  | times | (`today` \| `date <date>` \| `month <month>` \| `year <year>`) `[ song \| artist]` `[ partial \| complete ] ` |
  | ints | intervals of songs you listened to most |
- history
<!-- -  -->

**Exporting/Importing Settings**

| Commands                 | Description                                                                                                             |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| export settings          | Exports settings to C:\Users\<Admin\>\Desktop\marianna*exported_settings*<username\>.yml                                |
| export settings filepath | Exports settings to provided path as a yml file                                                                         |
| import settings          | Import settings from C:\Users\<Admin\>\Desktop\marianna*exported_settings*<username\>.yml if available, else show error |
| import settings filepath | Import settings from filepath if it is valid, else show error                                                           |

**Exporting/Importing Settings**

| Command | Description |
|-|-|
| b[ackup] directory*path | create songs backup in specified directory if exists, else show error|
| b[ackup] -n | create songs backup in new directory at C:\Users\<Admin\>\Desktop/mariana_library_backup*<username\> if not exists, else ask user to either rewrite default backup directory or create backup in a custom directory |

## Command Line Flags
Usage: py main.py [option]

### Basic Flags

| Commands                          | Description                                               |
| --------------------------------- | --------------------------------------------------------- |
| -h                                | Show help                                                 |
|                                   |                                                           |
| -a                                | Random auto run                                           |
| -p "path_1" "path_2" ... "path_n" | Play songs from provided paths one after another and exit |
| -q "queue name"                   | Play songs saved in queue named "queue name"              |
| -f                                | Play favs                                                 |
| -r                                | Replay recents in order of old to new                     |
| -r -n2o                           | Replay recents in order of new to old                     |

### Flags that Override Settings

| Commands                                          | Description                                                                                   |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| -nd \| --no-decorate                              | Do not print anything which is not absolutely essential (hide banner, loading status, etc...) |
| -nr \| --no-reload                                | Do not reload all files in source directory trees, i.e. fast bootup...                        |
| -ll=<log_level> \| --log-level=<log_level>        | set the log level                                                                             |
| -H                                                | make any and all output hidden (including fatal errors)                                       |
| -t=<theme_name>                                   | set color theme, set (theme = none) for plain no-color output                                 |
| -v=<initial_volume_value>                         | set initial volume on startup (override presaved volume in settings)                          |
| -s                                                | sleep (or sleep and exit depending on settings) after "time" seconds                          |
| -l -o                                             | Open library in default text editor                                                           |
| -l -e                                             | Edit library directly from CLI                                                                |
| -l -p                                             | Show path of lib file                                                                         |
| -b=<output_file_path> f[iles] \| s[ettings] \| \| | backup                                                                                        |
| -b -l                                             | list all backup file paths saved in history                                                   |
| -c -e                                             | Edit settings directly from CLI                                                               |
| -c -p                                             | Print settings config path                                                                    |
| -c -o                                             | Open settings config in default text editor                                                   |
| --clear-recents [-y]                              | Deletes recent songs data (optional -y for skipping confirmation)                             |
| --clear-history [-y]                              | Deletes all action history (optional -y for skipping confirmation)                            |
| --clear-data [-y]                                 | Deletes recent songs data (optional -y for skipping confirmation)                             |

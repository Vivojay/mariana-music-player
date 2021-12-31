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

**Lyrics**: lyrics | lyr | l  
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
|-|-|
|||
| b[ackup] directory*path | create songs backup in specified directory if exists, else show error|
| b[ackup] -n | create songs backup in new directory at C:\Users\<Admin\>\Desktop/mariana_library_backup*<username\> if not exists, else ask user to either rewrite default backup directory or create backup in a custom directory |

## Command Line Flags

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
| -R                                | Replay recents in order of new to old                     |

### Flags that Override Settings

| Commands                                   | Description                                                                                   |
| ------------------------------------------ | --------------------------------------------------------------------------------------------- |
| -nd \| --no-decorate                       | Do not print anything which is not absolutely essential (hide banner, loading status, etc...) |
| -t=<theme_name>                            | set color theme, set theme = none for plain no color output                                   |
| -ll=<log_level> \| --log-level=<log_level> | set log level                                                                                 |
| -v=<initial_volume_value>                  | set initial volume on startup                                                                 |
| -H                                         | make any and all output hidden (including fatal errors)                                       |
| -s                                         | sleep (or sleep and exit depending on settings) after "time" seconds                          |

### Standalone Flags (Non Chainable)

| Commands                                          | Description                                                        |
| ------------------------------------------------- | ------------------------------------------------------------------ |
| --clear-recents [-y]                              | Deletes recent songs data (optional -y for skipping confirmation)  |
| --clear-history [-y]                              | Deletes all action history (optional -y for skipping confirmation) |
| --clear-data [-y]                                 | Deletes recent songs data (optional -y for skipping confirmation)  |
| --clear-quickload [-y]                            | Deletes recent songs data (optional -y for skipping confirmation)  |
| --clear-quickload [-y]                            | Deletes recent songs data (optional -y for skipping confirmation)  |
| -c -e                                             | Open settings config for editing                                   |
| -c -p                                             | Print settings config path                                         |
| -c -e                                             | Open settings config for editing                                   |
| -b=<output_file_path> f[iles] \| s[ettings] \| \| | backup                                                             |
| -b -l                                             | list all backup file paths saved in history                        |

```
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
EXTRA DEV STUFF
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
Easter Eggs (Fun stuff)
Make into an executable release -> Host on GitHub
COLOUR OUTPUT
IMPLEMENT QUEUE PLAYING
Currently beta features are switched on by default and cannot be opted out of; Change this...

MIGRATE ENTIRELY TO python-vlc FOR PLAYING SONGS OF ANY KIND(CODEC)...

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
  key:	meaning	 abs(play_count) rel (%)
	0:	never	 0				 0%
	1:	least	 -				 0-4%
	2:	less	 4-15			 4-10%
	3:	moderate 15-100			 10-42%
	4:	more	 100-inf		 42-80%
	5:	most	 -				 80-100%

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

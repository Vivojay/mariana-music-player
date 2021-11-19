## Disclaimer
Please also read the TODO notebook for tasks you need to do, debugging needed, the features required + other stuff

<br>


## About Help
EBNF metasyntax is used for syntax formatting here.  
Lines written after a \````#```\` symbol are not of any importance, they are stale unimplemented features or future ideas.

Show commands shows files matching query in 4 columns by default.  
This can be changed in the config file.

All searches are fuzzy

|Song Info Type | Default Info Provided|
|-|-|
**default minimal** | name of song, ...
**default basic** | \_, \_, \_, ...
**default detailed** | name of song, ...

|Command|Description|
|-|-|
this \| that         |  Option between values
optional_ie_0_or_1?  |  Optional value
zero_or_more*        |  Value may occur zero or more times
one_or_more+         |  Value may occur one or more times

<br>


## Controls/Commands
### General
|Command|Description|
|-|-|
all |                                                                         display all sound files
<number\> |                                                                    show name of \`number\`th song
|Command|Description|
e[xit] \| q[uit] |                                                              stop and exit after confirming, show warning if song is still playing
e[xit] \| q[uit] y |                                                            stop and exit w/o confirmation, show warning if song is still playing
|Command|Description|
. <filepath\> |                                                                check if \`filepath\` is of a valid supported song file
open |                                                                       open current song file in Windows File Explorer
open <filepath\> |                                                             open file at \`filepath\` in Windows File Explorer if it is a valid supported song file 
|Command|Description|
vis |                                                                         switch to hide interactive output/feedback from player on command success or failure
path <n\> |                                                                    show path of provided audio file
now |                                                                         show now playing
help |                                                                       show concise help (only the most important commands) with a link for more detailed help
restart |                                                                    restart/reboot the player

#### Enable/Disable beta features
|Command|Description|
|-|-|
beta on\|off |                                                             Enable/Disable beta features respectively
beta list |                                                               List beta features consicely
beta list* |                                                               List beta features in detail

#### Beta Functions
|Command|Description|
|-|-|
.<number\> |                                                                   show info of \`number\`th song, including: <br>&nbsp;&nbsp;&nbsp;&nbsp;- Song name <br>&nbsp;&nbsp;&nbsp;&nbsp;- Artist name <br>&nbsp;&nbsp;&nbsp;&nbsp;- Play length <br>&nbsp;&nbsp;&nbsp;&nbsp;- Your rating <br>&nbsp;&nbsp;&nbsp;&nbsp;- Favourited or not <br>&nbsp;&nbsp;&nbsp;&nbsp;- Recently played or not <br>&nbsp;&nbsp;&nbsp;&nbsp;- File type <br>&nbsp;&nbsp;&nbsp;&nbsp;- Shows the path of containing folder | |

*Note: More detailed info can be found using the \`info\` command

<br>

### Music Controls Overview
#### Legacy Functions
|Command|Description|
|-|-|
p |                                                                     pause/resume
s[top] |                                                                stop
skip <number\> |                                                         skip \`number\`th song
n[ext] |                                                                skip to next song
p[rev] |                                                                skip to previous song
play <number\> |                                                         play track
m |                                                                     mute/unmute
seek <timeobject\> |                                                     seek to time given  in \`timeobject\`, correct format for this is given below. <br> (song play/pause status stays same) <br><br> &nbsp;&nbsp;&nbsp;&nbsp; Valid/Supported Formats for timeobject <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; `<hh>:<mm>:<ss>` <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; For settings any of the above values to zero, just skip them: <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; E.g. to set timeobject as `00:03:00`, you also write `:3:` or even `3:` <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; `<mm>:<ss>` <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; `<seconds>` (number of seconds as a positive integer) <br><br> *Note: Provided \`timeobject\` is converted to seconds for internal use in this program <br> E.g. seek 0 resets the song to the beginning
reset | Same as seek 0, seeks current song to start, (song play/pause status stays same)

#### Beta Functions
|Commands|Description|
|-|-|
play ("queue_name"\|"seq_name"\|<number\>)+   |  play custom sequence of queues/sequences/tracks
v\|vol <percentage\>                        |  set player volume to provided percentage
v\|vol                                      |  show current player volume as percentage
main system volume                         |  mvol

### Playing
#### Legacy Functions
|Commands|Description|
|-|-|
play all                           |   Play all songs in alp order
play all shuffle                   |   Play all songs in random order
play all shuffle repeat            |   Play all songs in random order and repeat until repeat cleared
play all shuffle repeat o|once     |   Play all songs in random order and repeat once
play all shuffle repeat c|clear    |   Play all songs in random order and repeat until repeat cleared
play <ftype\>                      |   Play all ftype songs in alp order
play <filepath\>                   |   Play file from path
play <filepaths\>+                 |   Play files from paths one-by-one in order

#### Beta Functions
|Commands|Description|
|-|-|
play q qname                      |     Play queue named \`qname\`
/play "search query"              |     Search for query in Spotify, play the song in the first search result

<br>

### Queueing
#### Legacy Functions (play-queue)
|||
|-|-|
play (<n1\>+) | Play all provided songs in alp order

E.g.

|Commands|Description|
|-|-|
play 6 2 4 |                            Queue and Play (ORDER MATTERS): <br> Play songs 6, 2 and 4 in that order <br> Displays names of songs in a newly issued play-queue <br> Displays "current play-queue over" after it's over
clear |                                   Clear all songs except now-playing from the current play-queue

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
Following 2 functions work same as for \`play (<n1\>+)\`  
(Queue names with spaces must be in quotes/double quotes)  

|Commands|Description|
|-|-|
q n myqname |                            Create a new empty saveable queue named \`myqname\`
q n myqname (<n1\>+) |                    Create a new saveable queue named \`myqname\` with all provided songs in order <br> (Repeated names will throw an error and will not be allowed)

A new queue may start automatically when an individual song/queue ends (Can be edited in config.yml file)

|Commands|Description|
|-|-|
q a <number\> [qname] |                    add \`number\`th item from global songs to queue
q r <number\> [qname] |                   remove \`number\`th item from current queue
q <number\> [qname] [result count] |      show \`number\`th item in current queue
q qname |                                prints 0 if queue is non existent, else 1

<br>

### Finding / Searching songs

|Commands|Description|
|-|-|
['f' \| 'find'] "Search Query" [<results_count\>\|all] |               Find locally, 10 results by default. Shows all results if "all" is mentioned
['/f' \| '/find'] "Search Query" [<results_count\>\|all] |            Find online from Spotify, 10 results by default. Shows all results if "all" is mentioned

<br>

### Beta Features (Other than aforementioned)
#### Sequence (Collection of queues)

|Commands|Description|
|-|-|
seq qname1 qname2+ |                                                      Minimum 2 queues required to form a sequence
seq n myqname |                                                           Create a new saveable sequence named \`myqname\` <br> names with spaces must be in quotes/double quotes <br> A queue may start automatically when an individualsong/sequence ends (Can be edited in config.yml file)
seq a <number\> |                                                          add \`number\`th item from global songs to sequence
seq r <number\> |                                                         remove \`number\`th item from current sequence
seq <number\> |                                                           show \`number\`th item in current sequence
    
**Note**
    BTS, a new queue is created (marked as a \`sequence\` object to differentiate from actual \`queue\` objects, in case of name collisions).
    This larger "queue" contains all other provided queues which were appended in it using appropriate commands while creation of sequence.
    This larger queue is marked as a sequence and is treated as one.
    
<br>

#### Cueing
**Note**
    A kind of advanced seek pointer for songs
    This "seek" position can be taken from current position or set manually
    This "seek" position can be saved for later use
    This "seek" position can also be applied to any another song whenever you want

**Save cue object for later**

|Commands|Description|
|-|-|
cue set <timeobject\> | Set cue object to provided timeobject
cue set .             | Set cue object to current time in current song
cue set 0             | Set cue object to start of song
cue [ftype] <num\> | Apply cue to provided song (Only one song at a time). <br> Now, whenever you play this song, it will automatically start from the set cue object
cue clear all |                                                       To remove currently set cue from all songs
cue clear songs+ |                                                   To remove currently set cue from provided songs
cue list |                                                           See the list of songs which have been cued to a certain timeobject <br> (i.e. cue has been applied to them but has not been cleared)

**Shuffling**

|Commands|Description|
|-|-|
shuffle [qname] |                                                         If qname provided, then the songs from that q are shuffled. Otherwise, the current q is shuffled
shuffle nr [qrname] |                                                     Same as \`shuffle [qname]\`, but songs which have already been played are not repeated

**Repeating**  
*Note:* re[p[eat]] means re|rep|repeat.  
So re = rep = repeat and can be used interchangeably

|Commands|Description|
|-|-|
re[p[eat]] c\|clear |                                                     Currently playing object (song/queue) is marked to no longer repeat
|||
re[p[eat]] |                                                             Currently playing object song is repeated/looped indefinitely
re[p[eat]] o\|once |                                                      Currently playing object song is repeated/looped once
|||
re[p[eat]] t |                                                           Currently playing track/song is repeated/looped indefinitely
re[p[eat]] t o\|once |                                                    Currently playing track/song is repeated/looped once
|||
re[p[eat]] q |                                                           Currently playing queue is repeated/looped indefinitely
re[p[eat]] q o\|once |                                                    Currently playing queue is repeated/looped once
|||
re[p[eat]] s |                                                           Currently playing sequence is repeated/looped indefinitely
re[p[eat]] s o\|once |                                                    Currently playing sequence is repeated/looped once

**Looping Region**

|Commands|Description|
|-|-|
loop <timeobject 1\> <timeobject 2\> |                                      Loop current song from \`timeobject 1\` to \`timeobject 2\`
loop c\|clear |                                                           Loop current song from \`timeobject 1\` to \`timeobject 2\`

**Basic Song info**

|Commands|Description|
|-|-|
info | Show detailed metadata info of current song
info <number> | Show detailed metadata info of song at given number

|Commands|Description|
|-|-|
/bpm|                                                                        Get BPM of current song from internet and/or from calculation/analysis
/bpm <number\> |                                                               Get BPM of song at provided number from internet and/or from calculation/analysis
/key |                                                                        Get key of current song from internet and/or from calculation/analysis
/key <number\> |                                                              Get key of song at provided number from internet and/or from calculation/analysis
/bpm key |                                                                    Get BPM and key of current song from internet and/or from calculation/analysis
/bpm key <number\> |                                                           Get BPM and key of song at provided number from internet and/or from calculation/analysis

|Commands|Description|
|-|-|
bpm |                                                                         Get BPM of current song from saved song metadata, or return error if not found
bpm <number\> |                                                               Get BPM of song at provided number from saved song metadata, or return error if not found
key |                                                                        Get key of current song from saved song metadata, or return error if not found
key <number\> |                                                               Get key of song at provided number from saved song metadata, or return error if not found
bpm key |                                                                    Get BPM and key of current song from saved song metadata, or return error if not found
bpm key <number\> |                                                           Get BPM and key of song at provided number from saved song metadata, or return error if not found

**Lyrics**: lyrics|lyr|l  
**Stars**: star <starscount\> <br> &nbsp;&nbsp;&nbsp;&nbsp;<starcount\> must be 1, 2, 3, 4 or 5. Anything else will result in error

**Effects**
**Note**
Applies any of the following effects to current song
One effect is applied at a time (Self-explantory commands have been chosen for effects)

- `fadein|fi`
- `fadeout|fo`

<br>

- `fastforward|ff`  
- `rewind`
- `flange`
- `phase`
- `detunelfo`
- `stutter`
- `nightcore|nc`
- `vaporwave|vw`

### Misc / Advanced / Power Commands

|Commands|Description|
|-|-|
dirs edit |                                                                       Edit directories where songs are taken from (i.e. sources.log) <br> opening it in vscode > npp > default notepad for editing
refresh |                                                                         refresh file in sources.log dirs, check dirs in log.log also
double numbering |                                                                global_number, ftype_number
loglevel (none\|0) \| (fatal\|1) \| (error\|warn\|2) \| (info\|3) \| (debug\|4) | Logging

`# silent (true | false)                                                       Switch on-screen interaction on/off`

**Config Commands**

|Commands|Description|
|-|-|
config edit |                                                             Open config file for editing in vscode > npp > default notepad
config set <new_config_path\> |                                            Set file as config file
config reset |                                                            Reset configuration
config help |                                                             Shows help regarding config

**Power Commands**

|Commands|Description|
|-|-|
%cs |                                                                    Capture this session
%rs |                                                                    Repeat last session
%del |                                                                    Delete song(s) by number/path/etc...
%% |                                                                     Open file with all help statements

**Favouriting**

|Commands|Description|
|-|-|
favs |                                                                        special queue for "fav songs"
fav a |                                                                      special queue for "fav songs"
fav |                                                                        special queue for "fav songs"

**Recent Songs**

|Commands|Description|
|-|-|
recent |                                                                      special queue for "recently played songs"

**Analysis and Stats**

- mostlistened (song|artist) [alltime|thismonth|today|yesterday]
- stats:
    - Options:
        - secslistened (today|date <date>|month <month>|year <year>) [song|artist] [partial|complete]
        - timeslistened (today|date <date>|month <month>|year <year>) [song|artist] [partial|complete]

- history

## Command Line Flags

|Commands|Description|
|-|-|
-h                                              | Show help
|||
-a                                              | Random auto run
-p "path_1" "path_2" ... "path_n"               | Play songs from provided paths one after another and exit
-q "queue name"                                 | Play songs saved in queue named "queue name"
-f                                              | Play favs
-r                                              | Replay recents in order of old to new
-R                                              | Replay recents in order of new to old


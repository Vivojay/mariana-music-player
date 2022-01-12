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

<br>

## Controls/Commands

### General

| Command   | Description                    |
| --------- | ------------------------------ |
| all       | display all sound files        |
| <number\> | show name of \`number\`th song |

| Command          | Description                                                           |
| ---------------- | --------------------------------------------------------------------- |
| e[xit] \| quit   | stop and exit after confirming, show warning if song is still playing |
| e[xit] \| quit y | stop and exit w/o confirmation, show warning if song is still playing |

| Command          | Description                                                                             |
| ---------------- | --------------------------------------------------------------------------------------- |
| . <filepath\>    | check if \`filepath\` is of a valid supported song file                                 |
| open             | open current song file in Windows File Explorer                                         |
| open <filepath\> | open file at \`filepath\` in Windows File Explorer if it is a valid supported song file |

| Command   | Description                            |
| --------- | -------------------------------------- |
| path <n\> | show path of audio file at given index |
| now       | show currently playing song name       |

### Music Controls Overview

#### Legacy Functions

| Command                                                                                      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| p                                                                                            | pause/resume                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| s[top]                                                                                       | stop                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| play <number\>                                                                               | play track                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| m                                                                                            | mute/unmute                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| seek <timeobject\> <br> **WARNING: Only works for mp3 songs and online streaming as of now** | seek to time given in \`timeobject\`, correct format for this is given below. <br> (song play/pause status stays same) <br><br> &nbsp;&nbsp;&nbsp;&nbsp; Valid/Supported Formats for timeobject <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; `<hh>:<mm>:<ss>` <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; For settings any of the above values to zero, just skip them: <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; E.g. to set timeobject as `00:03:00`, you also write `:3:` or even `3:` <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; `<mm>:<ss>` <br> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; `<seconds>` (number of seconds as a positive integer) <br><br> \*Note: Provided \`timeobject\` is converted to seconds for internal use in this program <br> E.g. seek 0 resets the song to the beginning |
| reset                                                                                        | Same as seek 0, seeks current song to start, (song play/pause status stays same)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |

#### Beta Functions

### Volume

| Commands                            | Description                              |
| ----------------------------------- | ---------------------------------------- |
| v \| vol \| volume <percentage\>    | set player volume to provided percentage |
| v \| vol \| volume                  | show current player volume as percentage |
| mv \| mvol \| mvolume <percentage\> | set system volume to provided percentage |
| mv \| mvol \| mvolume               | show system volume as percentage         |

### Finding / Searching songs

| Commands                                                 | Description                                                  |
| -------------------------------------------------------- | ------------------------------------------------------------ |
| ['f' \| 'find'] "Search Query" [<results_count\> \| all] | Find locally, 10 results by default. Shows all results if "all" is mentioned |

<br>

## Settings
### Functional Settings
- display items count
- maximum youtube-search results count
- loglevel
- visible

### Non Functional Settings
The following settings are never used.
They are available for possible future usage
- show banner
- show about

#### download
**download quality**  
It is defined for two kinds of downloads

**Audio Only:**       Sets the quality of audio-only downloads  
**Video with Audio:** Sets the quality of video downloads (videos are always downloaded with audio)

A value of 0 for either of these parameters means you want the WORST QUALITY download by default  
A value of 1 for either of these parameters means you want the BEST QUALITY download by default

\*NOTE: You may override the download quality directly in the player as well...  

### display items count
**general:** number of items to display (general purpose)
**youtube-search results:** number of items to display in YouTube search results




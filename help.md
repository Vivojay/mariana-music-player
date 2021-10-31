# About Help

*EBNF metasyntax is used for syntax formatting here*
All searches are fuzzy

Show commands shows files matching query in 4 columns by default.
This can be changed in the config file.

play next `[<ftype>]`: plays next song from list of all ftype songs
play next: plays next song from list of all songs

h: switch to hide song info
default info provided: name of song

if stopped, play/pause should give error: song is stopped
if dir is empty: show message: "No songs found, please check root dir or change it using the 'root' commmand"



| Syntax                | Description                                                  |
| --------------------- | ------------------------------------------------------------ |
| `this | that`         | Option between this or that, only one of the allowed choices can be selected |
| `optional_ie_0_or_1?` | Optional value                                               |
| `zero_or_more*`       | Value may occur zero or more times                           |
| `one_or_more+`        | Value may occur one or more times                            |

If help or config file is not available or is corrupted, prompt user to download required files from github or use default
If default file is not available or is corrupted, prompt user to download required files from github or close program, play beep at the end

Controls/Commands
==================================================================================================================================================================
    General
        <number>                                                                    show info of `number`th song
        <filepath>                                                                  check if `filepath` is of a valid supported song file
        exit                                                                        stop and exit
    
    Music Controls Overview
        Legacy Functions
            p                                                                       pause/resume
            s[top]                                                                  stop
            skip <number>                                                           skip `number`th song
            n[ext]                                                                  skip to next song
            p[rev]                                                                  skip to previous song
            play ("queue_name")+                                                    play custom sequence of queues
            player volume                                                           vol
            m                                                                       mute/unmute
            seek <timeobject>                                                       seek to time given in `timeobject`, correcet format for this is given below
                Valid/Supported Formats for timeobject
                    <hh>:<mm>:<ss>
                    For settings any of the above values to zero, just skip them:
                        E.g. to set timeobject as 00:03:00, you also write :3: or even 3:
                    <mm>:<ss>
                    <seconds>                       number of seconds as a positive integer
    
                    Note: Provided `timeobject` is converted to seconds for internal use in this program
    
            Beta Functions
                main system volume                                                      mvol
    
    Playing
        Legacy Functions
            play all                                Play all songs in alp order
            play all shuffle                        Play all songs in random order
            play all shuffle repeat                 Play all songs in random order and repeat order
            play ftype                              Play all ftype songs in alp order
            play q qname                            Play queue named `qname`
            play <filepath>                         Play file from path
            play <filepaths>+                       Play files from paths one-by-one in order
    
        Beta Functions
            /play "search query"                    Search for query in Spotify, play the song in the first search result
    
    Queueing
        Legacy Functions
            play (<n1>*) | ([ftype1 <n2>*]+)        Play all ftype songs in alp order
            E.g.
                play 3                                  Play a song from entire list (global list) - Here `3` is the global song index
                play wav 2                              Play wav file number 2
    
                play wav 1 4 5                          Queue and Play
                                                            wav files 1, 4 and 5 (ORDER MATTERS)
    
                play 2 3 wav 1 2 7                      Queue and Play (ORDER MATTERS)
                                                            global files 2 and 3 and wav files 1, 2 and 7
                play 4 2 mp3 31 8                       Queue and Play (ORDER MATTERS)
                                                            global files 4 and 2
                                                            wav files 31, 8
                play wav 1 mp3 5                        Queue and Play (ORDER MATTERS)
                                                            wav file 1
                                                            mp3 file 5
    
                play 6 2 wav 1 4 5 mp3 12 23 1          Queue and Play (ORDER MATTERS)
                                                            global files 2 and 3
                                                            wav files 1, 4 and 5
                                                            mp3 12, 23 and 1
    
        Beta Functions
            q n myqname                             Create a new saveable queue named `myqname`, names with spaces must be in quotes/double quotes
    
            A queue may start automatically when an individual song/queue ends (Can be edited in config.yml file)
            q a <number>                            add `number`th item from global songs to queue
    
            q r <number>                            remove `number`th item from current queue
            q <number>                              show `number`th item in current queue


    Finding / Searching songs
        ['f'|'find'] "Search Query" [<results_count>]               Find locally, 10 results by default
        ['/f'|'/find'] "Search Query" [<results_count>]             Find online from Spotify, 10 results by default

==================================================================================================================================================================
    Beta Features (Other than aforementioned)
        Enable/Disable beta features
            beta on|off                                                             Enable/Disable beta features respectively
            beta list                                                               List beta features

        Sequence
            seq n myqname                                                           Create a new saveable sequence named `myqname`,
                                                                                    names with spaces must be in quotes/double quotes
    
            A queue may start automatically when an individualsong/sequence ends (Can be edited in config.yml file)
            seq a <number>                                                          add `number`th item from global songs to sequence
    
            seq r <number>                                                          remove `number`th item from current sequence
            seq <number>                                                            show `number`th item in current sequence
    
        Cueing
            Note
                A kind of advanced seek pointer for songs
                This "seek" position can be taken from current position or set manually
                This "seek" position can be saved for later use
                This "seek" position can also be applied to any another song whenever you want
    
            Save cue object for later
                cue set <timeobject>                                                Set cue object to provided timeobject
                cue set .                                                           Set cue object to current time in current song
                cue set 0                                                           Set cue object to start of song
    
                cue [ftype] <num>                                                   Apply cue to provided song (Only one song at a time)
                                                                                    Now, whenever you play this song, it will automatically start from the set cue object
    
                cue clear all                                                       To remove currently set cue from all songs
                cue clear songs+                                                    To remove currently set cue from provided songs
    
                cue list                                                            See the list of songs which have been cued to a certain timeobject
                                                                                    (i.e. cue has been applied to them but has not been cleared)
    
        Shuffling
        Repeating
        Looping Region
    
        Effects
            Note
                Applies any of the following effects to current song
                One effect is applied at a time
    
            fastforward|ff
            rewind
            flange
            phase
            detunelfo
            stutter
            nightcore|nc
            vaporwave|vw
    
    Misc / Advanced / Power Commands
        dirs edit                                                                   Edit directories where songs are taken from
                                                                                    opening it in vscode > npp > default notepad for editing
    
        refresh                                                                     refresh file in log.log dirs, check dirs in log.log also
        double numbering                                                            global_number, ftype_number
    
        loglevel (none|0) | (fatal|1) | (error|warn|2) | (info|3) | (debug|4)       Logging
        silent (true | false)                                                       Switch on-screen interaction on/off
    
        Config Commands
            config edit                                                             Open config file for editing in vscode > npp > default notepad
            config set <new_config_path>                                            Set file as config file
            config reset                                                            Reset configuration
            config help                                                             Shows help regarding config
    
        Power Commands
            %cs                                                                     Capture this session
            %rs                                                                     Repeat last session
            %del                                                                    Delete song(s) by number/path/etc...
            %%                                                                      Open file with all help statements
    
        favs                                                                        special queue for "fav songs"
        recent                                                                      special queue for "recently played songs"
    
        Analysis and Stats
            mostlistened (song|artist) [alltime|thismonth|today|yesterday]
            stats:
                Options:
                    secslistened (today|date <date>|month <month>|year <year>) [song|artist] [partial|complete]
                    timeslistened (today|date <date>|month <month>|year <year>) [song|artist] [partial|complete]
    
            history


queue: (sequence of songs)
    view
    edit
    add to
    remove from


Show
    ftype num                                   Show `num`th song of `ftype` file type
    num                                         Show `number`th song
    all                                         Show all songs
    search <space sep search terms>             Show all songs matching search

Play
    play all                                    Play all songs in alp order
    play all shuffle                            Play all songs in random order
    play all shuffle repeat                     Play all songs in random order and repeat order
    play ftype                                  Play all ftype songs in alp order

Repeat
    play mp3 3                                  Plays 3rd mp3 file
    play mp3 3 repeat                           Play 3rd mp3 song on repeat

Search
    play <search terms>                         Play all song matching search on repeat
    play <search terms> repeat                  Play all song matching search on repeat
    play <search terms> 3 repeat                Play 3rd song matching search on repeat

Search and repeat
    play mp3 <search terms>                     Plays first song matching mp3 search
    play mp3 <search terms> repeat              Plays first song matching mp3 search on repeat
    play mp3 <search terms> 3 repeat            Plays 3rd song matching mp3 search on repeat


<ftype> <num>|<>

-h                                              Show help

-a                                              Random auto run
-p "path_1" "path_2" ... "path_n"               Play songs from provided paths one after another and exit
-q "queue name"                                 Play songs saved in queue named "queue name"
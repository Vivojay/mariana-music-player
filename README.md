# Mariana Music Player (In development)

## About
Feature rich command-line music player. \
Can play songs of [supported file types](some/path) and perform basic music control operations \
alongwith some [advanced controls and manipulations](some/other/path)

## Technical
This program uses the pygame module for playing, pausing, muting and stopping songs.

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

## Usage
Install PyPI modules from pip using `pip install -r requirements.txt`
Run `main.py` from command line with desired arguments, for more details, [look here](rick/roll).

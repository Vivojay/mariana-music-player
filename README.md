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
Install PyPI modules from pip using `pip install -r requirements.txt` \
Run `main.py` from command line with desired arguments, for more details, [look here](rick/roll).

## Errors
### 1
**Invoked via:** `lyr` command
Pic: ![image](https://user-images.githubusercontent.com/67545205/156342876-18e20aec-7eab-485b-a6c6-ed18fd1077c8.png)

**Err log:**
```
Exception ignored in: <function _compointer_base.__del__ at 0x00000174829A6820>
Traceback (most recent call last):
  File "C:\Users\Vivo Jay\Desktop\mplayer-4\.virtenv\lib\site-packages\comtypes\__init__.py", line 912, in __del__
    self.Release()
  File "C:\Users\Vivo Jay\Desktop\mplayer-4\.virtenv\lib\site-packages\comtypes\__init__.py", line 1166, in Release
    return self.__com_Release()
OSError: exception: access violation writing 0x0000000000000001
Exception ignored in: <function _compointer_base.__del__ at 0x00000174829A6820>
Traceback (most recent call last):
  File "C:\Users\Vivo Jay\Desktop\mplayer-4\.virtenv\lib\site-packages\comtypes\__init__.py", line 912, in __del__
    self.Release()
  File "C:\Users\Vivo Jay\Desktop\mplayer-4\.virtenv\lib\site-packages\comtypes\__init__.py", line 1166, in Release
    return self.__com_Release()
OSError: exception: access violation writing 0x0000000000000001
Exception ignored in: <function _compointer_base.__del__ at 0x00000174829A6820>
Traceback (most recent call last):
  File "C:\Users\Vivo Jay\Desktop\mplayer-4\.virtenv\lib\site-packages\comtypes\__init__.py", line 912, in __del__
    self.Release()
  File "C:\Users\Vivo Jay\Desktop\mplayer-4\.virtenv\lib\site-packages\comtypes\__init__.py", line 1166, in Release
    return self.__com_Release()
OSError: exception: access violation writing 0x0000000000000001
```

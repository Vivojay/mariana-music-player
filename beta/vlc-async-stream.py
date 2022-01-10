import pafy
import os
import sys
import ctypes

PY_ARCH = (8 * ctypes.sizeof(ctypes.c_voidp))
VLC_ARCH = None

def set_media(_type=None, vidurl=None, audurl=None):

    try: media_player(action='stop')
    except Exception: pass

    player = vlc.Instance()
    player.log_unset()

    if _type.startswith("radio"):
        radio_type = _type.split("/")[1]
        media = player.media_new(f"https://s2-webradio.antenne.de/{radio_type}")
        load_media_object(player=player, media=media)

    elif _type == "yt_video":
        if vidurl:
            vid = pafy.new(vidurl)
            aud = vid.getbestaudio()
            audurl = aud.url
        if audurl:
            media = player.media_new(audurl)
            load_media_object(player=player, media=media)
        else:
            raise ValueError

    elif _type == "audio":
        if audurl:
            media = player.media_new(audurl)
            load_media_object(player=player, media=media)
    else:
        print("Media type not provided")
    
    return audurl

def load_media_object(player, media):
    global vlc_media_player

    media_list = player.media_list_new()
    media_list.add_media(media)

    vlc_media_player = player.media_list_player_new()
    vlc_media_player.set_media_list(media_list)


def vlc_import():
    global VLC_ARCH, PY_ARCH, vlc
    possible_vlc_paths = [
        r'C:\Program Files (x86)\VideoLAN\VLC', # 32 bit VLC
        r'C:\Program Files\VideoLAN\VLC', # 64 bit VLC
    ]

    for index, path in enumerate(possible_vlc_paths):
        if os.path.isdir(path):
            if 'vlc.exe' in os.listdir(path):
                VLC_ARCH = 32*(index+1)
                try:
                    _=os.add_dll_directory(path)
                    import vlc
                    if not os.path.isdir('temp'): os.mkdir('temp')
                    with open('temp/hasvlc.tmp', 'w') as _: pass
                    break
                except OSError:
                    sys.exit("Error finding VLC Media Player, install if you don't already have it...")
                except ImportError:
                    sys.exit("VLC module was not found. Please install all required modules using 'py -m pip install -r requirements.txt'")

    else:
        print(VLC_ARCH, PY_ARCH)
        print("Please install VLC Media Player if you haven't already.")
        print("If you already have VLC Media Player installed, please enter the path of its install directory (containing \"vlc.exe\" file) in the config file, under the heading \"VLC PATH\"\n\n")

    if VLC_ARCH:
        if VLC_ARCH != PY_ARCH:
            sys.exit("ERROR: Detected incompatible architecture of VLC Media Player. Please uninstall your current installation of VLC Media Player app and download the {0} bit version instead.\Visit https://www.videolan.org/ to download: ".format(PY_ARCH))


def media_player(action=None, playing_time=None):
    global vlc_media_player

    if action == 'pausetoggle':
        if bool(vlc_media_player.get_state()): vlc_media_player.pause()
        else: vlc_media_player.play()

    elif action == 'play':
        vlc_media_player.play()

    elif action == 'stop':
        vlc_media_player.stop()

    elif action == 'resync': # Only for radio (and redditsessions?)...
        cur_state = bool(vlc_media_player.get_state())
        
        vlc_media_player.stop()
        vlc_media_player.play()
        if cur_state: # Song was not playing before
            vlc_media_player.pause()


def main():
    pass


vlc_import()

if __name__ == '__main__':
    main()

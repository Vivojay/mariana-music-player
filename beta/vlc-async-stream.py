import pafy
import os
import sys
import ctypes

from ruamel.yaml import YAML
from url_validate import id_if_url_is_of_yt_format

yaml = YAML(typ='safe')

PY_ARCH = (8 * ctypes.sizeof(ctypes.c_voidp))
VLC_ARCH = None
VLC_PATH = None
SETTINGS = None

def set_media(_type=None, vidurl=None, audurl=None, localpath=None):

    # `localpath` may be a single path or a list of absolute paths to local media

    try: media_player(action='stop')
    except Exception: pass

    player = vlc.Instance()
    player.log_unset()

    if _type.startswith("radio"):
        radio_type = _type.split("/")[1]
        load_media_object(player=player,
        				  mrls_list=[f"https://s2-webradio.antenne.de/{radio_type}"])

    elif _type == "yt_video":
        if vidurl:
            vid = pafy.new(vidurl)
            aud = vid.getbestaudio()
            audurl = aud.url
        if not audurl:
            raise ValueError

        load_media_object(player=player, mrls_list=[audurl,])

    elif _type == "audio":
        if audurl:
            if id_if_url_is_of_yt_format(audurl):
                audurl = f'http://www.youtube.com/watch?v={id_if_url_is_of_yt_format(audurl)}'
                audurl = pafy.new(audurl).getbest().url # Get media url (i.e. url with best audio + video)
            load_media_object(player=player, mrls_list=[audurl,])

    elif _type == 'local':
        if not isinstance(localpath, list): localpath = [localpath]
        load_media_object(player=player, mrls_list=localpath)

    else:
        print("Media type not provided")

    return audurl

def load_media_object(player, mrls_list):
    global vlc_media_player

    media_list = player.media_list_new()

    for mrl in mrls_list:
        media = player.media_new(mrl)
        media_list.add_media(media)

    vlc_media_player = player.media_list_player_new()
    vlc_media_player.set_media_list(media_list)

def get_bit(exe_file_abs_path):
    import win32file
    exe_file_abs_path = exe_file_abs_path.replace('\\', '/')
    if os.path.exists(exe_file_abs_path):
        exe_arch = win32file.GetBinaryType(exe_file_abs_path)
        return 32 if exe_arch == win32file.SCS_32BIT_BINARY else 64
    else:
        return None

def vlc_import():
    global VLC_ARCH, PY_ARCH, SETTINGS, vlc
    possible_vlc_paths = [
        r'C:\Program Files (x86)\VideoLAN\VLC', # 32 bit VLC
        r'C:\Program Files\VideoLAN\VLC', # 64 bit VLC
    ]

    with open('settings/settings.yml', 'r', encoding='utf-8') as fp:
        SETTINGS = yaml.load(fp)

    VLC_PATH = SETTINGS.get('vlc path')

    if VLC_PATH: possible_vlc_paths.insert(0, VLC_PATH)

    for index, path in enumerate(possible_vlc_paths):
        if os.path.isdir(path) and 'vlc.exe' in os.listdir(path):
            VLC_ARCH = get_bit(os.path.join(path, 'vlc.exe'))
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
        print("If you already have VLC Media Player installed, please enter the path of its install directory (containing \"vlc.exe\" file) in the settings file (settings/settings.yml), under the heading \"vlc path\"\n")

        if VLC_PATH:
            print("\nVLC path may not have been set correctly in the settings file, try setting it to null\n\n")
        else:
            print()

    if VLC_ARCH and VLC_ARCH != PY_ARCH:
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

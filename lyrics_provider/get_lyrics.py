
import os
import re
import toml
import tkinter as tk

curdir = os.path.dirname(__file__)
os.chdir(curdir)

import lyrics_provider.detect_song

from tkinter import ttk
from ruamel.yaml import YAML

os.chdir(curdir)
os.chdir('..')
from logger import SAY

yaml = YAML(typ='safe')

def get_settings():
    try:
        with open("settings/system.toml", encoding="utf-8") as file:
            SYSTEM_SETTINGS = toml.load(file)
    except IOError:
        SYSTEM_SETTINGS = None

    try:
        with open("settings/settings.yml", encoding="utf-8") as file:
            SETTINGS = yaml.load(file)
    except IOError:
        SETTINGS = None
    
    SUPPORTED_FILE_TYPES = SYSTEM_SETTINGS["system_settings"]["supported_file_types"]
    LYRICS_SETTINGS = SETTINGS['lyrics']

    return SUPPORTED_FILE_TYPES, LYRICS_SETTINGS

SUPPORTED_FILE_TYPES, LYRICS_SETTINGS = get_settings()
FOOT_TEXT = "Lyrics Powered by Musixmatch"
os.chdir(curdir)

def atoi(text):
    return int(text) if text.isdigit() else text

def natural_keys(text):
    '''
    alist.sort(key=natural_keys) sorts in human order
    http://nedbatchelder.com/blog/200712/human_sorting.html
    (See Toothy's implementation in the comments)
    '''
    return [ atoi(c) for c in re.split(r'(\d+)', text) ]

def get_lyrics(max_wait_lim,
               get_related,
               songfile=None,
               weblink=None,
               isYT=False):

    """
    `lyr`: An intermediate string which is processed into `text_to_be_displayed`
    `head_text` and `text_to_be_displayed` are the important final results
    which are then returned as a tuple
    """
    global SUPPORTED_FILE_TYPES
    SUPPORTED_FILE_TYPES, _ = get_settings()

    head_text = "Lyrics N/A"
    text_to_be_displayed = "(Lyrics not available)"

    if weblink:
        SONG_INF=lyrics_provider.detect_song.get_weblink_audio_info(max_wait_lim=max_wait_lim, weblink=weblink, isYT=isYT)
    elif songfile:
        if not songfile.endswith(tuple(SUPPORTED_FILE_TYPES)):
            return (text_to_be_displayed, head_text)
        SONG_INF=lyrics_provider.detect_song.get_song_info(songfile, get_related=get_related)
    else:
        SONG_INF = {}

    if SONG_INF is None: SONG_INF = {}

    if SONG_INF != {}:
        head_text = SONG_INF['display_name']
        lyr = SONG_INF.get('lyrics')
        if lyr:
            lyr = '\n'.join(lyr)
            text_to_be_displayed = lyr

    return (text_to_be_displayed, head_text)

def create_lyrics_html():
    try:
        with open('temp/lyrics.txt', 'r', encoding='utf-8') as fp:
            cached_lyrics = fp.read()

        cached_lyrics_lines = cached_lyrics.split('-'*80)

        head_text = cached_lyrics_lines[1].strip()
        head_text = f"<h1 class = 'main'>{head_text}</h1>"

        lyrics_lines = cached_lyrics_lines[2].strip().splitlines()
        lyrics_lines = [f"<p>{line}</p>" if line else "</div>\n\n<br>\n\n<div>" for line in lyrics_lines]

        prefix = [
                    '<!DOCTYPE html>',
                    '<html>',
                    '<head>',
                    '    <meta charset="UTF-8">',
                    '    <meta name="viewport" content="width=device-width, initial-scale=1.0">',
                    '    <link rel="stylesheet" href="../res/style.css">',
                    '    <link rel="preload" href="Elsie-Regular.ttf" as="font" type="font/ttf" crossorigin>',
                    '    <link rel="preconnect" href="https://fonts.googleapis.com">',
                    '    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
                    '    <link href="https://fonts.googleapis.com/css2?family=Arima+Madurai:wght@500&display=swap" rel="stylesheet">',
                    '</head>',
        ]

        lyrics_lines = prefix + ['\n', head_text, '\n<hr>\n\n<div>'] + lyrics_lines + ['</html>']
        lyrics = '\n'.join(lyrics_lines)

        with open('temp/lyrics.html', 'w', encoding='utf-8') as fp:
            fp.write(lyrics)

        return 0
    except OSError:
        return 1


def show_window(max_wait_lim,
                show_window,
                get_related,
                refresh_lyrics = True,
                visible=True,
                songfile=None,
                weblink=None,
                isYT=False):

    PROVIDED_WALLPAPER_NAMES = os.listdir('res/lyrics-wallpapers')
    PROVIDED_WALLPAPER_NAMES.sort(key=natural_keys)

    if refresh_lyrics:
        text_to_be_displayed, head_text = get_lyrics(songfile=songfile,
                                                     get_related=get_related,
                                                     weblink=weblink,
                                                     isYT=isYT,
                                                     max_wait_lim=max_wait_lim)

        # Create CSS file from default.css and the provided lyrics wallpaper image name (from settings file)

        with open("res/default.css", 'r', encoding='utf-8') as default_css_file:
            default_css = default_css_file.read()

        body_css = 'body {\n'
        DEFAULT_BG_PATH = 'lyrics-wallpapers/DEFAULT.jpg'
        _, LYRICS_SETTINGS = get_settings()

        # Using a solid color wallpaper
        if LYRICS_SETTINGS['use solid color bg']:
            body_css += '  background-color: {0};\n'.format(LYRICS_SETTINGS['solid color bg']['color'])

        # Using an image wallpaper
        else:
            # Initialize lyrics bg image path to the DEFAULT wallpaper (DEFAULT.jpg)
            lyrics_bg_image_abs_path = DEFAULT_BG_PATH
            lyrics_bg_image_dir = LYRICS_SETTINGS['webview wallpaper']['wallpaper folder']

            # Wallpaper directory is explicitly provided
            if lyrics_bg_image_dir and os.path.isdir(lyrics_bg_image_dir):
                lyrics_bg_image_file = LYRICS_SETTINGS['webview wallpaper']['wallpaper name or number']
                if not lyrics_bg_image_file.endswith('.jpg'):
                    lyrics_bg_image_file += '.jpg'

                if lyrics_bg_image_file:
                    lyrics_bg_image_file = os.path.join(lyrics_bg_image_dir, lyrics_bg_image_file)
                    if os.path.isfile(lyrics_bg_image_file):
                        lyrics_bg_image_abs_path = os.path.join(lyrics_bg_image_dir, lyrics_bg_image_file)
                    else:
                        SAY(visible=visible,
                            display_message = 'You entered invalid wallpaper file name. Reverting to default',
                            log_message = 'Wallpaper file name invalid, reverting to default',
                            log_priority = 2)

            # Wallpaper directory implicitly reverted to default
            else:
                lyrics_bg_image_dir = 'lyrics-wallpapers'
                lyrics_bg_image_file = LYRICS_SETTINGS['webview wallpaper']['wallpaper name or number']

                if type(lyrics_bg_image_file) == int:
                    lyrics_bg_image_index = int(lyrics_bg_image_file)
                    if lyrics_bg_image_index-1 in range(len(PROVIDED_WALLPAPER_NAMES)):
                        lyrics_bg_image_file = PROVIDED_WALLPAPER_NAMES[lyrics_bg_image_file]
                    else:
                        SAY(visible=visible,
                            display_message = 'You entered wallpaper number {0}. Try again with a number between 1 and {1}.'\
                                              '\nReverting to default'.format(lyrics_bg_image_index, 1, len(PROVIDED_WALLPAPER_NAMES)),
                            log_message = 'Wallpaper index out of bounds, reverting to default',
                            log_priority = 2)

                if lyrics_bg_image_file:
                    if not lyrics_bg_image_file.endswith('.jpg'):
                        lyrics_bg_image_file += '.jpg'

                    os.chdir(curdir)
                    os.chdir('../res')
                    if os.path.isfile(os.path.join(lyrics_bg_image_dir, lyrics_bg_image_file)):
                        lyrics_bg_image_abs_path = os.path.join(lyrics_bg_image_dir, lyrics_bg_image_file)
                    os.chdir('..')


            body_css += \
                '  background-image: linear-gradient(to right, rgba(0, 0, 0, 0.9), rgba(0, 0, 0, 0.3), rgba(255, 255, 255, 0.2)),\n'\
                '  url("{0}");\n\n'\
                \
                '  background-size: cover;\n'\
                '  background-repeat: no-repeat;\n'\
                '  background-position: center bottom;\n'\
                '  background-attachment: fixed;'.format(lyrics_bg_image_abs_path.replace('\\', '/'))
        
        body_css += '\n}'

        default_css += body_css

        with open("res/style.css", 'w', encoding='utf-8') as css_file:
            css_file.write(default_css)

        # try:
        # os.path.isdir('../temp/')
        with open('temp/lyrics.txt', 'w', encoding='utf-8') as fp:
            fp.write('-'*80+'\n')
            fp.write(head_text+'\n')
            fp.write('-'*80+'\n\n')
            fp.write(text_to_be_displayed+'\n')
        # except Exception:
        #     raise

        _ = create_lyrics_html() # TODO - Do something with the value (0 or 1) ?

    else:
        try:
            with open('temp/lyrics.txt', 'r', encoding='utf-8') as fp:
                cached_lyrics = fp.read()
            cached_lyrics_lines = cached_lyrics.split('-'*80)
            head_text = cached_lyrics_lines[1].strip()
            text_to_be_displayed = cached_lyrics_lines[2].strip()

        except Exception:
            head_text = "Lyrics N/A"
            text_to_be_displayed = "(Lyrics not available)"

    if not show_window: return None

    root = tk.Tk()
    root.resizable(True, False)
    root.geometry("550x270")
    root.title("Mariana - Lyrics Window")

    os.chdir(curdir)
    os.chdir('..')

    # Icon for lyrics window
    p1 = tk.PhotoImage(file = 'res/lyrics_icon.png')
    root.iconphoto(False, p1)

    # Apply the grid layout
    root.grid_columnconfigure(0, weight=1)
    root.grid_rowconfigure(0, weight=1)
    root.resizable=((0, 0)) # Disable window resizing

    head = tk.Label(root, text=head_text, font=("Segoe UI Bold", 14))
    foot = tk.Label(root, text=FOOT_TEXT, font=("Arial Italic", 10), fg='brown')

    head.grid(row=0, column=0, sticky='new')
    foot.grid(row=2, column=0, sticky='sew')

    # Create the text widget
    text = tk.Text(root, height=10)

    text.delete(1.0, "end")
    text.insert('end', '\n'+text_to_be_displayed)

    text.config(state='disabled', font = ("Segoe UI", 11))
    text.grid(row=1, column=0, sticky='new')

    # A previous plan (Using the MusixMatch API to get time-synced "rich lyrics"??)
    # location = settings['general']['current_location']
    # if location == 'JP': # Japan users have an agreement with Musixmatch to NOT BE ALLOWED TO COPY / PASTE LYRICS using their API
    #     text.bindtags((str(text), str(root), "all"))

    # Create a scrollbar widget and set its command to the text widget
    scrollbar = ttk.Scrollbar(root, orient='vertical', command=text.yview)
    scrollbar.grid(row=1, column=1, sticky='ns')

    # Communicate back to the scrollbar
    text['yscrollcommand'] = scrollbar.set

    root.mainloop()

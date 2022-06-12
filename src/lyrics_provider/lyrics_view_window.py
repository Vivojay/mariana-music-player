import tkinter as tk

import os
import lyrics_provider.detect_song

from tkinter import ttk


def show_window(songfile=None, weblink=None, isYT=False):
    root = tk.Tk()
    root.resizable(True, True)
    root.geometry("550x270")
    root.title("Mariana Lyrics Window")

    # Apply the grid layout
    root.grid_columnconfigure(0, weight=1)
    root.grid_rowconfigure(0, weight=1)
    root.resizable = (0, 0)  # Disable window resizing

    if weblink:
        SONG_INF = lyrics_provider.detect_song.get_weblink_audio_info(weblink, isYT=isYT)
    elif songfile:
        SONG_INF = lyrics_provider.detect_song.get_song_info(songfile)
    else:
        SONG_INF = []

    if SONG_INF != []:
        headtext = SONG_INF["display_name"]
        lyr = SONG_INF.get("lyrics")
        if lyr:
            lyr = "\n".join(lyr)
            text_to_be_displayed = lyr
        else:
            headtext = "Lyrics N/A"
            text_to_be_displayed = "(Lyrics not available)"
    else:
        headtext = "Lyrics N/A"
        text_to_be_displayed = "(Lyrics not available)"

    foottext = "Lyrics Powered by Musixmatch"

    head = tk.Label(root, text=headtext, font=("Segoe UI Bold", 14))
    foot = tk.Label(root, text=foottext, font=("Arial Italic", 10), fg="brown")

    head.grid(row=0, column=0, sticky="new")
    foot.grid(row=2, column=0, sticky="sew")

    # Create the text widget
    text = tk.Text(root, height=10)

    text.delete(1.0, "end")
    text.insert("end", "\n" + text_to_be_displayed)

    text.config(state="disabled", font=("Segoe UI", 11))
    text.grid(row=1, column=0, sticky="new")

    # location = settings['general']['current_location']
    # if location == 'JP': # Japan users have an agreement with Musixmatch to NOT BE ALLOWED TO COPY / PASTE LYRICS using their API
    #     text.bindtags((str(text), str(root), "all"))

    # Create a scrollbar widget and set its command to the text widget
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=text.yview)
    scrollbar.grid(row=1, column=1, sticky="ns")

    # Communicate back to the scrollbar
    text["yscrollcommand"] = scrollbar.set

    root.mainloop()


if __name__ == "__main__":
    show_window(r"D:\FL Utils\Downloaded Songs")

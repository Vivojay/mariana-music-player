import sys
import json
import tkinter as tk

from tkinter import ttk

def spawn_lyrics_window(text_to_be_displayed, head_text, foot_text):

    root = tk.Tk()
    root.resizable(True, False)
    root.geometry("550x270")
    root.title("Mariana - Lyrics Window")

    # Icon for lyrics window
    p1 = tk.PhotoImage(file = '../res/lyrics_icon.png')
    root.iconphoto(False, p1)

    # Apply the grid layout
    root.grid_columnconfigure(0, weight=1)
    root.grid_rowconfigure(0, weight=1)
    root.resizable=((0, 0)) # Disable window resizing

    head = tk.Label(root, text=head_text, font=("Segoe UI Bold", 14))
    foot = tk.Label(root, text=foot_text, font=("Arial Italic", 10), fg='brown')

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

if __name__ == "__main__":
    ARGS = sys.argv[1:]
    lyrics_spawn_params_str = ARGS[0]

    spawn_lyrics_window(**json.loads(lyrics_spawn_params_str))

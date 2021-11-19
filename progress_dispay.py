import os, sys
from tkinter import *

# cd to working dir
curDir=os.path.dirname(__file__)
# curDir=sys.argv[0]
os.chdir(curDir)

def display_msg(title='Message', message='', _background='#222', _foreground='white'):
    root=Tk()
    root.geometry('400x200')
    root.config(background=_background)
    root.title(title)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    message_label=Label(
        text=message,
        font=('Segoe UI Semibold', 12),
        background=_background,
        foreground=_foreground,
    )

    message_label.grid(row=0, column=0, sticky='news')
    root.mainloop()

if __name__ == '__main__':
    if len(sys.argv) > 1:
        display_msg('Hello', ' '.join(sys.argv[1:]))
    else:
        display_msg('Hello')

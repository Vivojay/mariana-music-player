
# IPrint -> Interactive Print
# Dynamic and playful prints...
# Still working on making it better

# package program
# convert to exe
# coloured program outputs
# make /yl and /r <radio_index> work


cols = [
    ('NAVY_BLUE', 'white'),
    ('DARK_BLUE', 'white'),
    ('BLUE_3A', 'white'),
    ('BLUE_3B', 'white'),
    ('BLUE_1', 'white'),
    ('DODGER_BLUE_2', 'white'),
    ('DODGER_BLUE_3', 'white'),
    ('DEEP_SKY_BLUE_3B', 'white'),
    ('DEEP_SKY_BLUE_1', 'white'),
    ('DEEP_SKY_BLUE_2', 'white'),
]

from multiprocessing import Process
from colored import fg as _fg, bg as _bg, attr, back

def IPrint(text=""):
    print(text)
def loading(text=""): pass
def Coloured(text="", fg="white", bg="black", multi=False, disableprint=False):
    bg = bg.lower()
    fg = fg.lower()
    if multi:
        pass
    else:
        if disableprint:
            return(f"{_bg(bg)}{_fg(fg)}{text}{attr('reset')}")
        else:
            print(f"{_bg(bg)}{_fg(fg)}{text}{attr('reset')}")

def rainbow_print(text, colours):
    LC = len(colours)
    for index, letter in enumerate(text):
        bg, fg = colours[index%LC]
        print(Coloured(letter, bg = bg, fg = fg, disableprint=1), end='')
    print()

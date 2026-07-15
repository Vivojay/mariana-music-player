import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

APP_DIR = Path(__file__).resolve().parent

def notify(txt = "", Time=10000):

    dimensions = (350, 350)

    root = tk.Tk()
    root.after(Time, root.destroy)

    img = Image.open(APP_DIR / "res" / "welcome_banner.png")

    img = img.resize(dimensions)
    tkimage = ImageTk.PhotoImage(img)
    MedusaPic = tk.Label(root, image=tkimage)
    MedusaPic.configure(anchor="center")
    MedusaPic.pack(expand=True)

    w, h = dimensions
    ws = root.winfo_screenwidth()
    hs = root.winfo_screenheight()
    # calculate position x, y
    x = (ws / 2) - (w / 2)
    y = (hs / 2) - (h / 2)
    root.geometry('%dx%d+%d+%d' % (w, h, x, y))

    root.overrideredirect(True)
    root.resizable(0, 0)
    root.wm_attributes("-topmost", 1)
    root.configure(background='black')

    root.mainloop()

if __name__ == "__main__":
    notify()

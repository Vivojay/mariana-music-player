# Python Logging System

"""
format_style:
    1:  brief
        (<log_level_in_words>)                                  => <log_message>\n

    2:  detailed
        (<log_level_in_words>) <DD>-<Mon>-<YYYY> <HH>:<MM>:<SS> => <log_message>\n
"""

import os
import terminal_colors as colored
from pathlib import Path
from mariana.paths import runtime_paths

from datetime import datetime as dt

# From res/data
logleveltypes = {
    0: "none",
    1: "fatal",
    2: "warn",
    3: "info",
    4: "debug"
}


def NOW():
    return dt.strftime(dt.now(), '%d-%b-%Y %H:%M:%S')

def SAY(
    visible,
    log_priority, # Default value is defined in main.py
    display_message = None, # Displayed on app
    log_message: str = '', # Saved to log file
    out_file = None, # Log file path
    format_style: int = 2,
):
    global loglevel, logleveltypes

    if visible and display_message:
        print(colored.fg('magenta_3a')+\
              display_message+\
              colored.attr('reset'))

    out_file = Path(out_file) if out_file else runtime_paths().logs / 'general.log'
    llt = logleveltypes[log_priority]
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    writemodes = ['w', 'a']
    writemode = writemodes[os.path.exists(out_file)]

    if log_priority == 1: # Fatal crash logs must be saved in logs/appcrashes.log also...
        crash_path = Path(out_file).with_name('appcrashes.log')
        with crash_path.open(['w', 'a'][crash_path.is_file()], encoding="utf-8") as crash_log_file:
            crash_log_file.write(f"({NOW()}) => {log_message}\n")

    if log_priority:
        with open(out_file, writemode, encoding="utf-8") as logfile:
            if format_style == 0:
                formatted_log_message = f"({NOW()}) => {log_message}\n"
            elif format_style == 1:
                formatted_log_message = f"({llt}) {' '*20} => {log_message}\n"
            elif format_style == 2:
                formatted_log_message = f"({llt}) {NOW()} => {log_message}\n"
            else:
                raise ValueError("InvalidLogformat_styleError")

            if format_style in range(0, 3):
                logfile.write(formatted_log_message)

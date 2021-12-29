# Python Logging System

"""
format_style:
    1:  brief
        (<log_level_in_words>)                                  => <log_message>\n

    2:  detailed
        (<log_level_in_words>) <DD>-<Mon>-<YYYY> <HH>:<MM>:<SS> => <log_message>\n
"""

import os
import colored

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
    out_file = 'logs/generallogs.log', # Log file path
    format_style: int = 2,
):
    global loglevel, logleveltypes

    if visible and display_message:
        print(colored.fg('magenta_3a')+\
              display_message+\
              colored.attr('reset'))

    llt = logleveltypes[log_priority]
    writemodes = ['w', 'a']
    writemode = writemodes[os.path.exists(out_file)]

    if log_priority == 1: # Fatal crash logs must be saved in logs/appcrashes.log also...
        with open("logs/appcrashes.log", ['w', 'a'][os.path.isfile("logs/appcrashes.log")]) as crash_log_file:
            crash_log_file.write()

    if log_priority:
        with open(out_file, writemode) as logfile:
            if format_style == 1:
                formatted_log_message = f"({llt}) {' '*20} => {log_message}\n"
            elif format_style == 2:
                formatted_log_message = f"({llt}) {NOW()} => {log_message}\n"
            else:
                raise "InvalidLogformat_styleError"

            if format_style in range(1, 3):
                logfile.write(formatted_log_message)

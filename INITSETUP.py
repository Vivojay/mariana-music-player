# --------------------------------------------------------------------------------------------------------------------------- #
# THIS FILE IS INTENDED TO BE INDEPENDENT (it only requires an internet connection and the git executable installed globally)
# This file can download the entire project (Mariana Player) and guide you with its installation and setup...
# This helps in seamless setup, and you don't need to have the project installed
#
# Even if you have solely this file, you can install the player (no other files required)
# --------------------------------------------------------------------------------------------------------------------------- #


import os
import sys
import json
import subprocess

curdir = os.path.dirname(os.path.realpath(__file__))
default_python_path = os.path.join(os.path.expanduser('~'), r'AppData\Local\Programs\Python\Python39\python.exe')
python_ver_command = "\"import sys; print('.'.join([str(i) for i in list(sys.version_info)[:3]]))\""

RUN_ONCE = os.path.isfile(os.path.join(os.path.expanduser('~'), 'setup.pypaths'))

commands_to_run_2 = [
    # Installing needed python modules
    "py -m pip install -r src/requirements.txt",
    "py -m pip install git+https://github.com/Vivojay/pafy@develop",
    "py -m pip install --no-cache-dir comtypes",
]

def create_runners(prog_dir_path):
    os.chdir(prog_dir_path)
    with open("runner.bat", 'w') as runnerfile:
        runnerfile.write(f'cd "{prog_dir_path}\\src"'+'\n')
        runnerfile.write("..\.virtenv\Scripts\python.exe main.py"+'\n')
    with open("runner.ps1", 'w') as runnerfile:
        runnerfile.write(f'Set-Location "{prog_dir_path}\\src"'+'\n')
        runnerfile.write("..\.virtenv\Scripts\python.exe main.py"+'\n')

def Print(text: str = None):
    global SILENT
    if text and not SILENT: print(text)

if ("--help" in sys.argv) or ("-h" in sys.argv):
    help_menu = '''Usage: py initsetup.py [--no-confirm] [--silent --directory=DIRPATH]
Shorthand Usage: py initsetup.py [-n] [-s -dir=DIRPATH]
*Note: "--silent" flag requires a pairing "--directory" flag to go with it

+--------------------------------------------------------------------------------------------------------------+
|  -h, --help                         |  Show this help                                                        |
|--------------------------------------------------------------------------------------------------------------|
|  -n, --no-confirm                   |  Do not ask for confirmation after running every command during setup  |
|  -s, --silent                       |  Only fatal errors and necessary info and prompts will be displayed    |
|  -dir=DIRPATH, --directory=DIRPATH  |  Only fatal errors and necessary info and prompts will be displayed    |
|                                     |  DIRPATH may be a relative or absolute path to directory...            |
|                                     |  Paths with spaces must use quotes, e.g. -dir="DIRPATH"                |
+--------------------------------------------------------------------------------------------------------------+
'''
    sys.exit(help_menu)

SILENT = ("--silent" in sys.argv) or ("-s" in sys.argv)

if "--no-confirm" in sys.argv or "-n" in sys.argv:
    NO_CONF = True
    Print("NO CONFIRMATION MODE ENABLED...")
else:
    NO_CONF = False
    if " -dir=" in ' '.join(sys.argv):
        dir_name = [i for i in sys.argv if i.startswith('-dir=')][0].lstrip('-dir=')
        PROG_DIR_PATH = dir_name
    elif "--directory=" in ''.join(sys.argv):
        dir_name = [i for i in sys.argv if i.startswith('--directory=')][0].lstrip('--directory=')
        PROG_DIR_PATH = dir_name
    else:
        sys.exit('No directory specified, use -dir=DIRPATH or --directory=DIRPATH')

    if not SILENT:
        print('Setup was run w/o any flags (see run with --help for more info)')
    try:
        perm = input("Running in default mode (Auto mode turned off). Want to continue? [y/n]: ")
    except KeyboardInterrupt:
        sys.exit("\nUser successfully aborted this setup...")
    while True:
        if perm.lower().strip() == 'y':
            Print("[USING DEFAULT SETUP MODE]")
            break
        elif perm.lower().strip() == 'n':
            sys.exit("Shutting down program (Try '--no-confirm' flag for automatic setup w/o confirmations).\nSetup aborted by user...")

        try:
            perm = input("[INVALID RESPONSE, RETRY] Do you want to continue without auto-mode? [y/n]: ")
        except KeyboardInterrupt:
            sys.exit("\nUser successfully aborted this setup...")


if not RUN_ONCE:
    supported_py_vers_installed = []
    pyp = subprocess.run(["py", "--list-paths"], capture_output=1).stdout.decode().split()
    installed_pythons = {}
    for i in range(0, len(pyp)-1, 2):
        py_ver_tuple = tuple(int(i) for i in pyp[i][1:-3].split('.'))
        installed_pythons.update({py_ver_tuple: pyp[i+1]})

    for i in installed_pythons.items():
        if i[0][0] == 3 and i[0][1] < 10:
            supported_py_vers_installed.append(i[1])

    if os.path.exists(default_python_path):
        PYTHON_PATH = default_python_path
        default_python_ver_string = subprocess.run(f'{default_python_path} -c {python_ver_command}', capture_output=1).stdout.decode().strip()
        FINAL_VER = ('.'.join(default_python_ver_string.split('.')[:-1]), default_python_ver_string)
        Print(f"Found compatible python version: {default_python_ver_string}")

    else:
        if any(supported_py_vers_installed):
            PYTHON_PATH = supported_py_vers_installed[0]
            found_python_ver_string = subprocess.run(f'{supported_py_vers_installed[0]} -c {python_ver_command}', capture_output=1).stdout.decode().strip()
            FINAL_VER = ('.'.join(found_python_ver_string.split('.')[:-1]), found_python_ver_string)
            Print(f"Found compatible python version: {found_python_ver_string}")
        else:
            sys.exit("No python version below 3.10 found, please install a compatible python version and rerun this setup.\nAborting this auto setup...")

    Print()
    try:
        if not SILENT:
            PROG_DIR_PATH = input("Please make a new empty directory for this program to install into and\nenter its path here (If directory is non-empty or path is invalid, setup will abort): ")
    except KeyboardInterrupt:
        sys.exit("\nUser successfully aborted this setup...")

    if os.path.isdir(PROG_DIR_PATH):
        if not any(os.scandir(PROG_DIR_PATH)):
            os.chdir(PROG_DIR_PATH)
        else:
            if NO_CONF:
                sys.exit(f"Provided --directory @{PROG_DIR_PATH} is NOT empty. Aborting setup...")
            else:
                sys.exit("This directory is NOT empty. Aborting setup...")
    else:
        sys.exit("This directory does NOT exist. Aborting setup...")

    Print("\nSuccessfully set directory for download.")
    Print(f"  Mariana Music Player will be downloaded to directory @{PROG_DIR_PATH}\n")

    try:
        if not SILENT:
            _ = input(f"Press enter to confirm this one-time setup with python version ({FINAL_VER[0]}), (CTRL+C to abort): ")
    except KeyboardInterrupt:
        sys.exit("\nUser successfully aborted this setup...")

    commands_to_run_1 = [
        # Presetup (Upgrading pip and installing virtualenv (if not already present...))
        "py -m pip install --upgrade pip",
        "py -m pip install --upgrade virtualenv",

        # Downloading git repo to desired dir
        "git clone https://github.com/Vivojay/mariana-music-player",

        # Renaming this program's source dir as "src"
        "move mariana-music-player src",

        # Making and activating python virtualenv with compatible py version
        f'py -m virtualenv -p="{PYTHON_PATH}" .virtenv',
        f'cd "{PROG_DIR_PATH}"',
    ]

    for cmd_index, cmd in enumerate(commands_to_run_1):
        try:
            if not NO_CONF:
                _ = input(f"Current command ([enter] to run, [CTRL+C] to abort setup)\n  -> {cmd}: ")

            if cmd_index == 2:
                if SILENT: subprocess.call(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else: subprocess.call(cmd, shell=True)
            else:
                if SILENT: subprocess.call(cmd, shell=True, stdout=subprocess.DEVNULL)
                else: subprocess.call(cmd, shell=True)

            Print("Loading next...\n")
        except KeyboardInterrupt:
            sys.exit("\nUser successfully aborted this setup...")

    # Create file for later use...
    with open(os.path.join(os.path.expanduser('~'), 'setup.pypaths'), 'w') as f:
        json.dump({
                        "INSTALLED_PYS": supported_py_vers_installed,
                        "PROG_DIR_PATH": os.path.realpath(''),
                        "SETUP_COMPLETE": False,
                }, f)

    ACTIVATION_PATH = os.path.join(os.path.realpath(''), '.virtenv\\Scripts\\activate')

    print('\n\n'+'-'*40)
    print("Please activate the auto-created venv by manually typing:\n")
    print(f'''cd "{os.path.realpath('')}"''')
    print('.virtenv\\Scripts\\activate')
    if NO_CONF and SILENT:
        print(f'py "{__file__}" --silent --no-confirm --directory=\"{PROG_DIR_PATH}\"')
    elif NO_CONF:
        print(f'py "{__file__}" --no-confirm --directory=\"{PROG_DIR_PATH}\"')
    elif SILENT:
        print(f'py "{__file__}" --silent"')
    print('\n'+'-'*40+'\n')

else:
    # Load logged details from prev run...
    with open(os.path.join(os.path.expanduser('~'), 'setup.pypaths')) as f:
        SETUP_INFO = json.load(f)

    if not SETUP_INFO['SETUP_COMPLETE']:
        os.chdir(SETUP_INFO['PROG_DIR_PATH'])

        ACTIVATION_PATH = os.path.join(SETUP_INFO['PROG_DIR_PATH'], '.virtenv\\Scripts\\activate')
        PYTHON_EXECUTABLE = os.path.join(SETUP_INFO['PROG_DIR_PATH'], '.virtenv\\Scripts\\python.exe')

        BAT_PATH = os.path.join(SETUP_INFO['PROG_DIR_PATH'], 'runner.bat')
        PS1_PATH = os.path.join(SETUP_INFO['PROG_DIR_PATH'], 'runner.ps1')

        if sys.executable in SETUP_INFO['INSTALLED_PYS']:
            print(f"You have not activated the venv yet, run: \"{ACTIVATION_PATH}\" (without quotes) to activate it")
            sys.exit("After activating, you then need to rerun this setup program. Aborting setup...")
        else:
            if sys.executable != PYTHON_EXECUTABLE:
                print(f"You have not activated the venv yet, run: \"{ACTIVATION_PATH}\" (without quotes) to activate it")
                sys.exit("After activating, you then need to rerun this setup program. Aborting setup...")
            else:
                for cmd_index, cmd in enumerate(commands_to_run_2):
                    try:
                        if not NO_CONF:
                            _ = input(f"Current command ([enter] to run, [CTRL+C] to abort setup)\n  -> {cmd}: ")
                        if cmd_index == 2:
                            if SILENT: subprocess.call(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            else: subprocess.call(cmd, shell=True)
                        else:
                            if SILENT: subprocess.call(cmd, shell=True, stdout=subprocess.DEVNULL)
                            else: subprocess.call(cmd, shell=True)
                        Print("Loading next...\n")
                    except KeyboardInterrupt:
                        sys.exit("\nUser successfully aborted this setup...")

                SETUP_INFO['SETUP_COMPLETE'] = True
                with open(os.path.join(os.path.expanduser('~'), 'setup.pypaths'), 'w') as f:
                    json.dump(SETUP_INFO, f)

                create_runners(SETUP_INFO['PROG_DIR_PATH'])

                if not SILENT:
                    print("\n\n"+"-"*80)
                    print(f'Setup is complete.\n2 new files, i.e. "runner.bat" and "runner.ps1" have been created in directory: {SETUP_INFO["PROG_DIR_PATH"]}\n\n')
                    print(f'Run either one using ".\\runner.bat" (Recommended) or ".\\runner.ps1"\nto start the music player in one go, whenever you like!\n')

                    print(f"runner.bat will work in both cmd, and powershell\n")

                    print("If you want to run the player in powershell, you need to do a one-time setup*")
                    print("            *(Not Recommended, unless you know what you're doing)")
                    print("  First, open powershell as admin and run: 'Set-ExecutionPolicy Unrestricted' (without quotes)")
                    print("  Then type 'Y' in the confirmation prompt(s) before executing 'runner.ps1'\n")

                    print("All successive runs of 'runner.ps1' in powershell (no need to open as admin)")
                    print(f"can be done normally with '.\\runner.ps1' (without quotes)")
                    print("Bye...")
                    print("\n\n"+"-"*80)
                sys.exit(0)
    else:
        print("Setup is complete, refer to the runner.bat and runner.ps1 files created in the directory where you downloaded the app...")
        sys.exit(f'You may delete this file "@{__file__}" now...')


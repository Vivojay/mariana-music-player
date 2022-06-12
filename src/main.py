
#################################################################################################################################
# Mariana Player v0.4.2

# running app:
#	For very first boot (SETUP):
# 	  Make sure you have python version < 3.10 to run this file (unless compatible llvmlite wheel bins exist...)
# 	  Setup this program in a fresh virtualenv
# 	  Download and pip install unofficial binary for llvmlite wheel compatible with your python version
# 	  Setup compatible architecture of VLC media player, install FFMPEG and add to path...
# 	  Install git scm if not already installed
# 	  Install given git package directly from url using: `pip install git+https://github.com/Vivojay/pafy@develop`
# 	  run `pip install -r requirements.txt`
#
# 	  Firstly, look at help.md before running any py file
# 	  Run this file (main.py) on the very first bootup, nothing else (no flags, just to test bare minimum run)...
# 	  You are good to go...
#     *Note: If you encounter errors, look for online help as the current help file doesn't have common problem fixes yet
#
#	All successive boots (RUNNING NORMALLY):
#	  just run this file (main.py) with desired flags (discussed in help.md)
#	  and enjoy... (and possibly debug...)

# This app may take a LOT of time to load at first... (main culprit: librosa)
# Hence the loading prompt...
# Prompts like these will be made better and more
# dynamic using the IPrint (custom) and multiprocess modules

# Editor's Note: Make sure to brew a nice coffee beforehand... :)
#################################################################################################################################

from utils import *
visible = True

def showversion():
    global visible, ABOUT
    if visible and ABOUT:
        try:
            print(colored.fg('aquamarine_3')+\
                  f"v {ABOUT['ver']['maj']}.{ABOUT['ver']['min']}.{ABOUT['ver']['rel']}"+\
                  colored.attr('reset'))
            print()
        except Exception:
            pass


def showbanner():
    global visible
    banner_lines = []
    if visible:
        try:
            with open('about/banner.banner', encoding='utf-8') as file:
                banner_lines = file.read().splitlines()
                maxlen = len(max(banner_lines, key=len))
                if maxlen % 10 != 0:
                    maxlen = (maxlen // 10 + 1) * 10 # Smallest multiple of 10 >= maxlen,
                                                     # Since 10 is the length of cols...
                                                     # So lines will be printed with full olor range
                                                     # and would be more visually pleasing...
                banner_lines = [(x + ' ' * (maxlen - len(x))) for x in banner_lines]
                for banner_line in banner_lines:
                    IPrint.rainbow_print(banner_line, IPrint.cols+IPrint.cols[::-1])
        except IOError:
            pass

    showversion()

def run():
    global disable_OS_requirement, visible, USER_DATA

    if disable_OS_requirement and visible and sys.platform != 'win32':
        print("WARNING: OS requirement is disabled, performance may be affected on your Non Windows OS")

    USER_DATA['default_user_data']['stats']['log_ins'] += 1
    save_user_data()

    pygame.mixer.init()
    showbanner()
    mainprompt()


def startup():
    global disable_OS_requirement

    try: os.system('color 0F') # Needed?!? idk
    except Exception: pass

    try: first_startup_greet(FIRST_BOOT)
    except Exception: pass

    if not disable_OS_requirement:
        if sys.platform != 'win32':
            sys.exit('ABORTING: This program may not work on'
            'Non-Windows Operating Systems (hasn\'t been tested)')
        else: run()
    else: run()


if __name__ == '__main__':
    if FATAL_ERROR_INFO:
        print(f"FATAL ERROR ENCOUNTERED: {FATAL_ERROR_INFO}")
        print("Exiting program...")
        sys.exit(1) # End program...gracefully...
    else:
        startup()
else:
    print(' '*30, end='\r')  # Get rid of the current '\r'...

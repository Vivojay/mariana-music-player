import os
import sys
from ruamel.yaml import YAML

yaml = YAML(typ='safe')

curdir=os.path.dirname(__file__)
os.chdir(curdir)

def fbs(about): # First boot setup
    greet_string = f"Welcome to Mariana Player v{about['ver']['maj']}.{about['ver']['min']}.{about['ver']['rel']}"
    print("\n\n")
    print(f"{'='*(len(greet_string)+8)}")
    print(f"||  {' '*len(greet_string)}  ||")
    print(f"||  {greet_string}  ||")
    print(f"||  {' '*len(greet_string)}  ||")
    print(f"{'='*(len(greet_string)+8)}")

    locally_stored_permission = input("Do you have any locally stored/downloaded music files? (y/n): ").lower().strip()
    while locally_stored_permission not in ['y', 'n', 'yes', 'no']:
        locally_stored_permission = input("[INVALID RESPONSE] Do you have any locally stored/downloaded music files? (y/n): ").lower().strip()

    if locally_stored_permission in ['yes', 'y']:
        locally_stored_permission = True
    else:
        locally_stored_permission = False

    local_file_dirs = []

    if locally_stored_permission:
        print("Please enter absolute path of your music directories one by one:")
        print("(When done, just write \"xxx\")\n")
        n=0
        while True:
            n+=1
            local_file_dir = input(f"  Enter directory path {n} ('xxx' to exit): ").lower().strip()
            if local_file_dir != 'xxx':
                if os.path.isdir(local_file_dir): local_file_dirs.append(local_file_dir)
                else: print("This directory does not exist, please retry...")
            else:
                print()
                print(f"Saving directory paths in your library\n  @location: {os.path.join(curdir, 'lib.lib')}!")
                break
            
            local_file_dir = list(set(local_file_dir))
            
            with open("lib.lib", 'a') as libfile:
                for _dir in local_file_dirs:
                    libfile.write(_dir+'\n')
    
    else:
        print("Ok, done!")

    run_now = input("\n\nWould you like to run Mariana Player now? (y/n) ").lower().strip()
    while run_now not in ['y', 'n', 'yes', 'no']:
        run_now = input("[INVALID RESPONSE] Want to run Mariana Player now? (y/n) ").lower().strip()

    about['first_boot'] = False
    with open('about/about.info', 'w') as about_file:
        yaml.dump(about, about_file)

    if run_now in ['no', 'n']:
        sys.exit(0)

import os
import stat
import toml
from pathlib import Path
from mariana.paths import runtime_paths

APP_DIR = Path(__file__).resolve().parent
curdir = str(APP_DIR)
HTTP_TIMEOUT = (10, 60)

def download_cloud_mariana_samples(about):
    import sys
    import requests
    import zipfile

    from tqdm.auto import tqdm
    from ruamel.yaml import YAML
    from beta.mediadl import setup_dl_dir

    yaml = YAML(typ='safe')

    SYSTEM_SETTINGS = about
    with runtime_paths().settings.open(encoding='utf-8') as u_data_file:
        SETTINGS = yaml.load(u_data_file)

    dl_dir_setup_code = setup_dl_dir(SETTINGS, SYSTEM_SETTINGS)
    if dl_dir_setup_code in range(4):
        return dl_dir_setup_code
    output_zip_path = os.path.join(dl_dir_setup_code, 'mariana_samples.zip')

    if sys.platform == 'win32':
        output_zip_path = output_zip_path.replace('/', '\\')
    else:
        output_zip_path = output_zip_path.replace('\\', '/')

    # Mariana Cloud Music Collection (zip file) is located at: https://www.dropbox.com/s/s2cgmuwadkrsjl7/Mariana%20Cloud%20Music%20Collection.zip?dl=1
    mariana_samples_url = 'https://www.dropbox.com/s/s2cgmuwadkrsjl7/Mariana%20Cloud%20Music%20Collection.zip?dl=1'

    resp = requests.get(mariana_samples_url, stream=True, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    total = int(resp.headers.get('content-length') or 178238582)

    print('', end='', flush=True)
    with open(output_zip_path, 'wb') as file, tqdm(
        # desc=output_zip_path,
        desc='',
        total=total,
        unit='iB',
        unit_scale=True,
        unit_divisor=1024,
        ncols=60,
    ) as bar:
        for data in resp.iter_content(chunk_size=1024):
            size = file.write(data)
            bar.update(size)

    if not zipfile.is_zipfile(output_zip_path):
        raise zipfile.BadZipFile("The sample download was not a valid zip archive")
    samples_dir = Path(dl_dir_setup_code) / 'mariana_music_samples'
    samples_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip_path, 'r') as zip_ref:
        samples_root = samples_dir.resolve()
        for member in zip_ref.infolist():
            member_path = (samples_root / member.filename).resolve()
            if not member_path.is_relative_to(samples_root) or stat.S_ISLNK(member.external_attr >> 16):
                raise zipfile.BadZipFile(f"Unsafe path in sample archive: {member.filename}")
        zip_ref.extractall(samples_dir)

    try:
        os.remove(output_zip_path)
    except Exception:
        pass


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
                if os.path.isdir(local_file_dir):
                    local_file_dirs.append(local_file_dir)
                else:
                    print("This directory does not exist, please retry...")
            else:
                print()
                print(f"Saving directory paths in your library\n  @location: {runtime_paths().library_file}!")
                break
            
            local_file_dirs = list(set(local_file_dirs))

            with runtime_paths().library_file.open('a', encoding='utf-8') as libfile:
                for _dir in local_file_dirs:
                    libfile.write(_dir+'\n')


    sample_songs_download_permission = input("Would you like to download a signature collection of 25 sample songs by Mariana\n(SPACE REQUIRED: 170MB)? (y/n): ").lower().strip()
    while sample_songs_download_permission not in ['y', 'n', 'yes', 'no']:
        sample_songs_download_permission = input("[INVALID RESPONSE] Would you like to download a signature Mariana music collection? (y/n): ").lower().strip()

    if sample_songs_download_permission in ['yes', 'y']:
        sample_songs_download_permission = True
    else:
        sample_songs_download_permission = False

    if sample_songs_download_permission:
        download_cloud_mariana_samples(about)

    print("\nOk, done!")

    run_now = input("\n\nWould you like to run Mariana Player now? (y/n) ").lower().strip()
    while run_now not in ['y', 'n', 'yes', 'no']:
        run_now = input("[INVALID RESPONSE] Want to run Mariana Player now? (y/n) ").lower().strip()

    about['first_boot'] = False
    try:
        with open('settings/system.toml', 'w') as about_file:
            toml.dump(about, about_file)
    except Exception:
        pass

    if run_now in ['no', 'n']:
        print("Mariana Player has been installed successfully for you...")
    
    return (run_now in ['no', 'n']) # True:  DO NOT RUN player
                                    # False: Continue to run player...

#################################################################################################################################
#
#           Mariana Player v0.7.0 dev
#     (Read help.md for help on commands)
#
#    Supported runtime: 64-bit Windows and CPython 3.12.
#    Install the locked dependencies from requirements.txt and run `python main.py`.
#    FFmpeg and FFprobe should be available on PATH for online media and metadata features.

# This app may take a LOT of time to load at first...
# Hence the loading prompt...

# Editor's Note: Make sure to brew a nice coffee beforehand... :)
#################################################################################################################################


# IMPORTS BEGIN #

import threading
import time

_BOOT_TOTAL = 31


def _boot_progress(step, label=''):
    """Render one in-place, text-and-bar startup progress update."""
    width = 24
    completed = max(0, min(width, round(width * step / _BOOT_TOTAL)))
    bar = '#' * completed + '-' * (width - completed)
    print(
        f"Loaded {step}/{_BOOT_TOTAL} [{bar}] {step / _BOOT_TOTAL:>4.0%} {label:<18}",
        end='\r',
        flush=True,
    )


APP_BOOT_START_TIME = time.time();                  _boot_progress(1, 'core')

import os;                                          _boot_progress(2, 'paths')
# import itertools;                                   print("Loaded 3/31",  end='\r')

import re;                                          _boot_progress(3, 'matching')
import sys;                                         _boot_progress(4, 'runtime')
_boot_progress(5, 'runtime')
import random as rand;                              _boot_progress(6, 'selection')
import importlib;                                   _boot_progress(7, 'extensions')
import terminal_colors as colored;                  _boot_progress(8, 'terminal')
import subprocess as sp;                            _boot_progress(9, 'processes')
import shutil
import restore_default;                             _boot_progress(10, 'configuration')
_boot_progress(11, 'configuration')
import json;                                        _boot_progress(12, 'storage')
import webbrowser;                                  _boot_progress(13, 'web links')
import tempfile
from pathlib import Path

from mariana.tls import enable_system_trust_store

SYSTEM_TRUST_STORE_ENABLED = enable_system_trust_store()

# import concurrent.futures;                          print("Loaded 15/31", end='\r')

import sounddevice;                                 _boot_progress(14, 'audio devices')
# from scipy.io.wavfile import read;                  print("Loaded 15/31", end='\r')
from getpass import getpass;                        _boot_progress(15, 'prompts')
from url_validate import id_if_url_is_of_yt_format, url_is_valid; _boot_progress(16, 'URL validation')
from tabulate import tabulate as tbl;               _boot_progress(17, 'tables')
from ruamel.yaml import YAML;                       _boot_progress(18, 'settings')
from collections.abc import Iterable;               _boot_progress(19, 'collections')
from logger import SAY;                             _boot_progress(20, 'logging')
from first_boot_welcome_screen import notify;       _boot_progress(21, 'first run')
from config_manager import load_system_settings, load_user_settings, save_user_settings
from mariana.albums import AlbumCatalog, AlbumError
from mariana.broadcast import BroadcastError, BroadcastState, IcecastBroadcaster
from mariana.commands import (
    DOWNLOAD_TYPOS,
    SEARCH_COMMANDS,
    SearchAction,
    normalize_command,
    parse_search,
    search_rows,
)
from mariana.command_parser import CommandSyntaxError, split_command
from mariana.credentials import CredentialError, CredentialStore
from mariana.database import MarianaDatabase
from mariana.desktop_control import DesktopControl
from mariana.download import DownloadError, download_media
from mariana.download_jobs import DownloadJobError, DownloadManager
from mariana.identity import AcoustIDClient, IdentificationService, LRCLIBClient, MusicBrainzClient
from mariana.library import LibraryCatalog, LibraryError
from mariana.library_service import LibraryProfilerService
from mariana.loudness import LoudnessError, RSGainAnalyzer
from mariana.media_details import flattened_details, short_filename
from mariana.media_removal import MediaRemovalError, MediaRemovalService
from mariana.models import (
    IdentityStatus,
    MediaCapabilities,
    MediaRef,
    MediaSource,
    PlaybackState,
    QueueStrategy,
    truncate_display_cells,
)
from mariana.output_devices import OutputDeviceError, default_output_device
from mariana.paths import initialize_runtime_paths
from mariana.platform import open_path, reveal_path
from mariana.playlists import PlaylistError, PlaylistStore
from mariana.preferences import MediaPreferences, PreferenceState
from mariana.presence import PresenceCoordinator, PresencePrivacyMode
from mariana.queueing import PersistentQueue, QueueError
from mariana.radio import RadioCatalog, RadioError
from mariana.sleep_timer import SleepAction, SleepTimer, parse_duration
from mariana.sources import FailureCode, MediaFailure
from mariana.station import StationError, StationManager
from mariana.station_discovery import StationDiscovery, StationSeedError
from mariana.setup import SetupStateError, SetupStateStore
from mariana.tool_setup import discover_media_tools, persist_media_tools, setup_media_tools
from mariana.toolchain import ToolchainError, ToolchainManager, find_javascript_runtime
from mariana.user_state import load_user_data, write_user_data_atomic
from mariana.version import __version__
from mariana.integrations.discord_presence import DiscordPresencePublisher
from recommendation_engine import Candidate, RecommendationEngine
from runtime_check import check_runtime, format_runtime_report
from beta.mediadl import media_DL
from beta.youtube_media import YouTubeError, media_info, parse_browser_profile, resolve_stream, youtube_error_message
_boot_progress(22, 'media services')

online_streaming_ext_load_error = 0
comtypes_load_error = False # Made available after fix from comtypes issue #244, #180
                            # Previously: comtypes_load_error = True
lyrics_ext_load_error = 0
REDDIT_RETIRED_MESSAGE = (
    "Reddit live sessions (RPAN) have been retired and are no longer available in Mariana Player."
)

# try:
#     import librosa
#     print("Loaded 23/31",  end='\r') # Time taking import (Sometimes, takes ages...)
# except ImportError:
#     print("[WARN] Could not load music computation extension...")
#     print("[WARN] ...Skipped 23/31")

CURDIR = os.path.dirname(os.path.realpath(__file__))
os.chdir(CURDIR)
RUNTIME_PATHS = initialize_runtime_paths()
SOUND_CACHE_PATH = RUNTIME_PATHS.state('data', 'snd_files.json')
LYRICS_TEXT_PATH = RUNTIME_PATHS.temporary / 'lyrics.txt'
LYRICS_HTML_PATH = RUNTIME_PATHS.temporary / 'lyrics.html'

from beta import ffmpeg_player as vas

_boot_progress(23, 'playback')

try:
    YT_query = importlib.import_module("beta.YT_query")
    _boot_progress(24, 'YouTube')
except ImportError:
    # raise
    if not online_streaming_ext_load_error:
        print("[INFO] Could not load online streaming extension...")
    print("[INFO] ...Skipped 25/31")

try:
    from beta.IPrint import IPrint, blue_gradient_print, cols, loading
    _boot_progress(25, 'display')
except ImportError:
    lyrics_ext_load_error = 1
    print("[INFO] Could not load coloured print extension...")
    print("[INFO] ...Skipped 26/31")

try:
    from lyrics_provider import get_lyrics
    _boot_progress(26, 'lyrics')
except ImportError:
    print("[INFO] Could not load lyrics extension...")
    if not lyrics_ext_load_error:
        print("[INFO] ...Could not load online streaming extension...")
    print("[INFO] ...Skipped 27/31")

print("[INFO] Reddit/RPAN commands are retained as retired aliases")

from lyrics_provider.detect_song import get_song_info

_boot_progress(27, 'identification')


try:
    from mariana.platform import get_master_volume, set_master_volume
    _boot_progress(28, 'system volume')
except Exception:
    comtypes_load_error = True
    SAY(visible=False, # global var `visible` hasn't been defined yet...
        log_message="comtypes load failed",
        display_message="", # ...because we don't want to display anything on screen to the user
        log_priority=2)

_boot_progress(29, 'platform')

try:
    from beta.podcasts import get_latest_podbean_data
    from beta.podcasts import vendors as pod_vendors
    _boot_progress(30, 'podcasts')
except Exception:
    print("[INFO] Could not load podcast extension...")
    print("[INFO] ...Skipped 31/31")

_boot_progress(31, 'ready')
print()

# IMPORTS END #


# TODO - Replace `err`s with `SAY`s
# TODO - Rename SAY to `err` or `errlogger`... in whole codebase?
# TODO - Add option to display type of error in display_message parameter of `SAY`
#        to print kind of log [ (debg)/(info)/(warn)/(fatl) ] ??

yaml = YAML(typ='safe')  # Allows for safe YAML loading

webbrowser.register_standard_browsers()

RUNTIME_PATHS.logs.mkdir(parents=True, exist_ok=True)

def create_required_files_if_not_exist(*files):
    for file in files:
        if not os.path.isfile(file):
            path = Path(file)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w', encoding="utf-8") as _:
                pass


def clear_terminal():
    """Clear the visible terminal, scrollback, and cursor position consistently."""
    print('\033[2J\033[3J\033[H', end='', flush=True)

create_required_files_if_not_exist(
    RUNTIME_PATHS.logs / 'history.log',
    RUNTIME_PATHS.logs / 'general.log',
)

SYSTEM_SETTINGS = load_system_settings()
SETUP_STORE = SetupStateStore(RUNTIME_PATHS)
try:
    FIRST_BOOT = SETUP_STORE.load().status != 'complete'
except SetupStateError:
    FIRST_BOOT = True
if os.environ.get('MARIANA_E2E') == '1' and os.environ.get('MARIANA_E2E_FIRST_BOOT') != '1':
    FIRST_BOOT = False

ISDEV = SYSTEM_SETTINGS['isdev'] # Useful as a test flag for new features

try:
    with RUNTIME_PATHS.library_file.open(encoding='utf-8') as logfile:
        paths = logfile.read().splitlines()
        paths = [path for path in paths if not path.startswith('#')]
        paths = list(set(paths))
except OSError:
    if not FIRST_BOOT:
        sys.exit("[INFO] Could not find lib.lib file, '\
                'please create one and add desired source directories. '\
                'Aborting program\n")


def first_startup_greet(is_first_boot):
    global FIRST_BOOT, SOFT_FATAL_ERROR_INFO

    if is_first_boot:
        try:
            import first_boot_setup
            if SOFT_FATAL_ERROR_INFO := first_boot_setup.fbs(
                about=SYSTEM_SETTINGS,
                store=SETUP_STORE,
            ):
                SOFT_FATAL_ERROR_INFO = "User skipped startup"
            FIRST_BOOT = SETUP_STORE.load().status != 'complete'
            refresh_runtime_configuration(show_report=True)
            reload_sounds(quick_load = False)
        except ImportError:
            sys.exit('[ERROR] Critical guide setup-file missing, please consider reinstalling this file or the entire program\nAborting Mariana Player. . .')

try:
    USER_DATA, invalid_user_data_backup = load_user_data(
        RUNTIME_PATHS.user_data,
        RUNTIME_PATHS.resource('user', 'user_data.yml'),
    )
    if invalid_user_data_backup is not None:
        print(
            '[WARNING] Recovered empty or invalid user statistics; '
            f'the previous file was retained at {invalid_user_data_backup}'
        )
except OSError:
    SAY(visible=True,
        display_message = f'Encountered missing program file @{RUNTIME_PATHS.user_data}',
        log_message = 'User data file not found',
        log_priority = 1) # Log fatal crash
    sys.exit(1) # Fatal crash


SETTINGS = load_user_settings()
YT_query.configure(
    browser_profile=SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile')
)

MEDIA_TOOLS = SETTINGS.get('media tools', {})
if MEDIA_TOOLS.get('javascript bin'):
    os.environ['MARIANA_JAVASCRIPT_RUNTIME'] = str(MEDIA_TOOLS['javascript bin'])
AUTOPLAY_ENABLED = bool(SETTINGS.get('playback', {}).get('autoplay', True))
TOOLCHAIN = ToolchainManager(RUNTIME_PATHS)
DATABASE = MarianaDatabase(RUNTIME_PATHS.database)
DATABASE.migrate_legacy_play_counts(RUNTIME_PATHS.user_data)
PREFERENCES = MediaPreferences(DATABASE)
REPLAYGAIN_SETTINGS = {
    **SETTINGS.get('replaygain', {}),
    **DATABASE.get_state('replaygain', {}),
}
LIVE_LEVELING_SETTINGS = {
    **SETTINGS.get('radio', {}).get('live leveling', {}),
    **DATABASE.get_state('radio_live_leveling', {}),
}
QUEUE = PersistentQueue(DATABASE)
RADIO = RadioCatalog(DATABASE)
IDENTITY = IdentificationService(
    DATABASE,
    acoustid=AcoustIDClient(SETTINGS.get('identification', {}).get('acoustid api key')),
    musicbrainz=MusicBrainzClient(),
    lrclib=LRCLIBClient(),
    fpcalc_bin=MEDIA_TOOLS.get('fpcalc bin'),
)
RECOMMENDER = RecommendationEngine(
    DATABASE,
    exploration=SETTINGS.get('recommendations', {}).get('exploration', 0.10),
    mmr_lambda=SETTINGS.get('recommendations', {}).get('mmr diversity', 0.75),
    blocked=lambda stable_id: PREFERENCES.get(stable_id) == PreferenceState.BLOCKED,
)
ALBUMS = AlbumCatalog(
    DATABASE,
    musicbrainz=IDENTITY.musicbrainz,
    browser_profile=SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile'),
)
DOWNLOADS = DownloadManager(
    DATABASE,
    ffmpeg_bin=MEDIA_TOOLS.get('ffmpeg bin'),
    browser_profile=SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile'),
    on_update=lambda payload: DESKTOP_CONTROL.emit('download', payload),
)
vas.configure(
    ffmpeg_bin=MEDIA_TOOLS.get('ffmpeg bin'),
    crossfade_seconds=SETTINGS.get('playback', {}).get('crossfade seconds', 0),
    catalog=RADIO,
    browser_profile=SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile'),
    replaygain=REPLAYGAIN_SETTINGS,
    live_leveling=LIVE_LEVELING_SETTINGS,
)
get_lyrics.configure(IDENTITY, vas.controller)
DESKTOP_CONTROL = DesktopControl()
DISCORD_PRESENCE = DiscordPresencePublisher(
    os.environ.get('MARIANA_DISCORD_APPLICATION_ID')
    or SYSTEM_SETTINGS.get('system_settings', {}).get('discord_application_id')
)
try:
    PRESENCE_MODE = PresencePrivacyMode(
        SETTINGS.get('integrations', {}).get('discord', {}).get('presence', {}).get('mode', 'off')
    )
except ValueError:
    PRESENCE_MODE = PresencePrivacyMode.OFF
PRESENCE = PresenceCoordinator(
    vas.controller.snapshot,
    DISCORD_PRESENCE,
    mode=PRESENCE_MODE,
)
BROADCASTER = IcecastBroadcaster.from_settings(
    SETTINGS.get('broadcast', {}),
    ffmpeg_bin=MEDIA_TOOLS.get('ffmpeg bin'),
    credentials=CredentialStore(),
    on_update=lambda status: DESKTOP_CONTROL.emit('broadcast', status.to_dict()),
)
vas.controller.add_program_sink(BROADCASTER.offer)
vas.controller.add_metadata_sink(BROADCASTER.metadata)
SLEEP_TIMER = SleepTimer(
    vas.controller,
    on_update=lambda status: DESKTOP_CONTROL.emit('sleep', status.to_dict()),
)
STATION = StationManager(
    DATABASE,
    QUEUE,
    StationDiscovery(
        DATABASE,
        RECOMMENDER,
        browser_profile=SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile'),
    ),
    on_update=lambda payload: DESKTOP_CONTROL.emit('station', payload),
    pause_playback=vas.controller.pause,
    resume_playback=vas.controller.resume,
)
COMMAND_BUSY = threading.Event()
YOUTUBE_DOWNLOAD_JOBS: set[threading.Thread] = set()
YOUTUBE_DOWNLOAD_JOBS_LOCK = threading.Lock()


def start_youtube_download(download_parameters: dict) -> threading.Thread:
    """Run one yt-dlp job without launching another Mariana executable."""
    media_kind = "audio" if download_parameters.get("typ") == 0 else "video"

    def worker() -> None:
        try:
            status = media_DL(**download_parameters)
            if status == 4:
                SAY(
                    visible=globals().get("visible", True),
                    display_message=f"YouTube {media_kind} download completed.",
                    log_message=f"YouTube {media_kind} download completed",
                    log_priority=3,
                )
            elif status != 5:
                failures = {
                    0: "The configured download folder does not exist.",
                    1: "No download folder is configured.",
                    2: "The download-folder configuration is incomplete.",
                    3: "Mariana could not create its download directory.",
                }
                message = failures.get(status, f"YouTube {media_kind} download failed with status {status}.")
                SAY(
                    visible=globals().get("visible", True),
                    display_message=message,
                    log_message=message,
                    log_priority=2,
                )
        except Exception as error:
            message = f"YouTube {media_kind} download failed: {error}"
            SAY(
                visible=globals().get("visible", True),
                display_message=message,
                log_message=message,
                log_priority=2,
            )
        finally:
            with YOUTUBE_DOWNLOAD_JOBS_LOCK:
                YOUTUBE_DOWNLOAD_JOBS.discard(threading.current_thread())

    thread = threading.Thread(
        target=worker,
        name=f"mariana-youtube-{media_kind}-download",
        daemon=True,
    )
    with YOUTUBE_DOWNLOAD_JOBS_LOCK:
        YOUTUBE_DOWNLOAD_JOBS.add(thread)
    thread.start()
    return thread


# Variables
APP_BOOT_END_TIME = time.time()
EXIT_INFO = 0
FATAL_ERROR_INFO = None
SOFT_FATAL_ERROR_INFO = None
RECENTS_QUEUE = []
YOUTUBE_PLAY_TYPE = None

isplaying = False
currentsong = None  # No audio playing initially
ismuted = False
lyrics_saved_for_song = False
currentsong_length = None

songindex = -1

lyrics_window_note = "[Please close the lyrics window to continue issuing more commands...]"
current_media_type = None

RUNTIME_REPORT = check_runtime(
    MEDIA_TOOLS.get('ffmpeg bin'),
    MEDIA_TOOLS.get('fpcalc bin'),
    MEDIA_TOOLS.get('rsgain bin'),
)
if not FIRST_BOOT:
    for runtime_message in format_runtime_report(RUNTIME_REPORT):
        print(f"[{runtime_message}]")
if RUNTIME_REPORT.errors and not FIRST_BOOT:
    FATAL_ERROR_INFO = "; ".join(RUNTIME_REPORT.errors)

"""
NO SUCH THING AS current_media_player now

random audio (optional repeat, no repeat by default)
log data about each audio path
    timestamp of play (int --> in unix time??)
    list of tags (str List)
    favourited? (bool)
    corrupted? (bool)
    blacklisted? (bool)
    duration played (int --> in ms)

    # Maybe
    estimated bpm
    estimated key/scale
"""

# Log levels from logger.py -> [Only for REF]
# logleveltypes = {0: "none", 1: "fatal", 2: "warn", 3: "info", 4: "debug"}

# From settings
enforce_os_requirement = SYSTEM_SETTINGS['system_settings']['enforce_os_requirement']

# Supported file extensions
# Progress is derived from PCM frames emitted to the output device.
supported_file_types = SYSTEM_SETTINGS["system_settings"]['supported_file_types']
max_wait_limit_to_get_song_length = SYSTEM_SETTINGS['system_settings']['max_wait_limit_to_get_song_length']
MAX_RECENTS_SIZE = SYSTEM_SETTINGS["system_settings"]['max_recents_size']

visible = SETTINGS['visible']
loglevel = SETTINGS.get('loglevel')
DEFAULT_EDITOR = SETTINGS.get('editor path')
FALLBACK_RESULT_COUNT = SETTINGS['display items count']['general']['fallback']
MAX_RESULT_COUNT = SETTINGS['display items count']['general']['maximum']
max_yt_search_results_threshold = SETTINGS['display items count']['youtube-search results']['maximum']

LIBRARY_SETTINGS = SETTINGS.get('library', {})


def _managed_library_roots():
    enabled = DATABASE.get_state(
        'library_include_downloads',
        SETTINGS.get('include music folder in library', True),
    )
    configured = SETTINGS.get('download', {}).get('downloads folder')
    if not enabled or not configured:
        return []
    root = Path(configured).expanduser()
    if SETTINGS.get('download', {}).get('make a separate mariana folder within "downloads folder"'):
        root /= SYSTEM_SETTINGS['system_settings']['mariana_dl_dir']
    return [(root, 'downloads')]


LIBRARY = LibraryCatalog(
    DATABASE,
    library_file=RUNTIME_PATHS.library_file,
    supported_extensions=supported_file_types,
    ffmpeg_bin=MEDIA_TOOLS.get('ffmpeg bin'),
    fpcalc_bin=MEDIA_TOOLS.get('fpcalc bin'),
    identity_service=IDENTITY,
    online_enrichment=LIBRARY_SETTINGS.get('online enrichment', False),
    rsgain_bin=MEDIA_TOOLS.get('rsgain bin') or TOOLCHAIN.resolve('rsgain'),
    analyze_loudness=bool(REPLAYGAIN_SETTINGS.get('enabled') and REPLAYGAIN_SETTINGS.get('analyze missing', True)),
    managed_roots=_managed_library_roots,
)


def refresh_runtime_configuration(*, show_report=False):
    """Apply setup-time tool paths to already-created services in this process."""
    global SETTINGS, MEDIA_TOOLS, RUNTIME_REPORT, FATAL_ERROR_INFO, AUTOPLAY_ENABLED
    global visible, loglevel, DEFAULT_EDITOR

    refreshed = load_user_settings()
    SETTINGS.clear()
    SETTINGS.update(refreshed)
    MEDIA_TOOLS = SETTINGS.setdefault('media tools', {})
    if MEDIA_TOOLS.get('javascript bin'):
        os.environ['MARIANA_JAVASCRIPT_RUNTIME'] = str(MEDIA_TOOLS['javascript bin'])
    AUTOPLAY_ENABLED = bool(SETTINGS.get('playback', {}).get('autoplay', True))
    visible = SETTINGS.get('visible', True)
    loglevel = SETTINGS.get('loglevel', 3)
    DEFAULT_EDITOR = SETTINGS.get('editor path')
    browser_profile = SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile')
    YT_query.configure(browser_profile=browser_profile)
    vas.configure(
        ffmpeg_bin=MEDIA_TOOLS.get('ffmpeg bin'),
        crossfade_seconds=SETTINGS.get('playback', {}).get('crossfade seconds', 0),
        catalog=RADIO,
        browser_profile=browser_profile,
        replaygain=REPLAYGAIN_SETTINGS,
        live_leveling=LIVE_LEVELING_SETTINGS,
    )
    IDENTITY.fpcalc_bin = MEDIA_TOOLS.get('fpcalc bin')
    LIBRARY.ffmpeg_bin = MEDIA_TOOLS.get('ffmpeg bin')
    LIBRARY.fpcalc_bin = MEDIA_TOOLS.get('fpcalc bin')
    LIBRARY.rsgain = RSGainAnalyzer(MEDIA_TOOLS.get('rsgain bin'))
    RUNTIME_REPORT = check_runtime(
        MEDIA_TOOLS.get('ffmpeg bin'),
        MEDIA_TOOLS.get('fpcalc bin'),
        MEDIA_TOOLS.get('rsgain bin'),
    )
    FATAL_ERROR_INFO = '; '.join(RUNTIME_REPORT.errors) if RUNTIME_REPORT.errors else None
    if show_report:
        for runtime_message in format_runtime_report(RUNTIME_REPORT):
            print(f'[{runtime_message}]')
    return RUNTIME_REPORT


def ensure_managed_tool_migration():
    """Offer one versioned, default-yes repair for installations predating the full bundle."""
    bundle = 'official-tools-2026.07.1'
    marker = DATABASE.get_state('managed_tool_prompt_version')
    status = discover_media_tools(SETTINGS)
    javascript = find_javascript_runtime(MEDIA_TOOLS.get('javascript bin'))
    if status.complete and javascript:
        DATABASE.set_state('managed_tool_prompt_version', bundle)
        return status
    if marker == bundle or os.environ.get('MARIANA_E2E') == '1':
        return status
    print('\nMariana can install the missing verified media tools now (FFmpeg, fpcalc, rsgain, and Deno).')
    answer = input('Automatically download and configure them? [Y/n]: ').strip().casefold()
    while answer not in {'', 'y', 'yes', 'n', 'no'}:
        answer = input('Please enter Y or N [Y]: ').strip().casefold()
    if answer in {'n', 'no'}:
        DATABASE.set_state('managed_tool_prompt_version', bundle)
        IPrint("Skipped for this version; run 'tools setup' whenever you are ready.", visible=visible)
        return status
    try:
        TOOLCHAIN.install_recommended(progress=lambda message: IPrint(message, visible=visible))
        status = discover_media_tools(SETTINGS)
        if not status.complete or not find_javascript_runtime():
            raise ToolchainError('one or more installed executables failed validation')
        persist_media_tools(status, SETTINGS, paths=RUNTIME_PATHS)
        DATABASE.set_state('managed_tool_prompt_version', bundle)
        refresh_runtime_configuration(show_report=True)
        IPrint('Managed media tools are ready.', visible=visible)
        return status
    except (ToolchainError, OSError) as error:
        IPrint(
            f'Managed tool installation failed: {error}. It will be offered again; '
            "use 'tools setup' for manual paths.",
            visible=visible,
        )
        return status
vas.controller.loudness_repository = LIBRARY.loudness
LIBRARY_SERVICE = LibraryProfilerService(
    LIBRARY,
    playback_state=lambda: vas.controller.snapshot().state,
    watch=LIBRARY_SETTINGS.get('watch', True),
    reconcile_seconds=LIBRARY_SETTINGS.get('reconcile hours', 6) * 60 * 60,
    network_poll_seconds=LIBRARY_SETTINGS.get('network poll seconds', 600),
    probe_workers=LIBRARY_SETTINGS.get('probe workers', 2),
    deep_workers=LIBRARY_SETTINGS.get('deep workers', 1),
)
MEDIA_REMOVAL = MediaRemovalService(DATABASE, LIBRARY, QUEUE, vas.controller)
MEDIA_REMOVAL.recover()

if not loglevel:
    restore_default.restore('loglevel', SETTINGS)
    loglevel = SETTINGS.get('loglevel')

# From last session info
cached_volume = 1  # Set as a factor between 0 to 1 times of max volume player volume

def OrderedSet(iterable):
    result = []
    [result.append(i) for i in iterable if i not in result]
    return result


# Flattens list of any depth
def flatten(values):
    for el in values:
        if isinstance(el, Iterable) and not isinstance(el, (str, bytes)):
            yield from flatten(el)
        else:
            yield el


# Function to extract files from folders recursively
def audio_file_gen(Dir, ext):
    for root, _dirs, files in os.walk(Dir):
        for filename in files:
            if os.path.splitext(filename)[1] == ext:
                yield os.path.join(root, filename)


def reload_sounds(quick_load = True, full = False):
    global _sound_files, _sound_files_names_only, _sound_files_names_enumerated, paths

    # NOTE: 'data/snd_files.json' is the relpath to the quick-loads file

    lib_found = True

    # Definition for quick-load
    if quick_load:
        indexed_paths = LIBRARY.paths()
        if indexed_paths:
            _sound_files = indexed_paths
        elif SOUND_CACHE_PATH.is_file():
            with SOUND_CACHE_PATH.open(encoding="utf-8") as fp:
                _sound_files = json.load(fp)

        else: # Revert to full load (i.e. NOT resorting to quick_load becuase data/snd_files.json is unavailable)
            quick_load = False

    # Definition for full-load (non quick-load)
    if not quick_load: # (This may be used either as the first-time load or as a fallback for a failed quick-load)
        if RUNTIME_PATHS.library_file.is_file():
            LIBRARY.scan('full' if full else 'changed')
            paths = [root['path'] for root in LIBRARY.roots() if root['available']]
            _sound_files = LIBRARY.paths()

            with SOUND_CACHE_PATH.open('w', encoding='utf-8') as fp:
                json.dump(_sound_files, fp)

        else:
            lib_found = False
            SAY(visible=visible,
                log_message="Library file suddenly made unavailable",
                display_message="Library file suddenly vanished -_-",
                log_priority=2)


    if lib_found:
        _sound_files_names_only = [os.path.splitext(os.path.split(i)[1])[0] for i in _sound_files]
        _sound_files_names_enumerated = [(i+1, j) for i, j in enumerate(_sound_files_names_only)]
        QUEUE.sync_library_defaults(LIBRARY.media_refs())

        if FIRST_BOOT:
            with SOUND_CACHE_PATH.open('w', encoding='utf-8') as fp:
                json.dump(_sound_files, fp)

reload_sounds(quick_load = not FIRST_BOOT) # First boot requires quick_load to be disabled,
                                           # other boots can do away with quick_loads :)
PREFERENCES.migrate_legacy(RUNTIME_PATHS.state('data', 'track-infos.yml'), LIBRARY)

if _sound_files_names_only == []:
    if loglevel in [3, 4]:
        IPrint("[INFO] All source directories are empty, you may and add more source directories to your library", visible=visible)
        IPrint("[INFO] To edit this library file (of source directories), refer to the `help.md` markdown file.", visible=visible)

def recents_queue_save(inf):
    """
    inf = {
        'yt_play_type': int,
        'type': int,
        'identity': (song_info_as_tuple) OR 'some/absolute/file/path',
    }
    inf is a dict of "yt_play_type" (applicable only for YT streams), "identity" and "type" of audio
    "identity" is a kind of unique locater for a audio. It can be a streaming url
    or the filepath of a locally streamed audio (as a string)

    Songs are pushed to the RECENTS_QUEUE and when it is full
    the oldest audios are removed first to clear space for the new ones

    RECENTS_QUEUE has a fixed size (determined by settings.yml)
    (max allowed value = 10,000,000 (1 Million) items)
    """

    global RECENTS_QUEUE, MAX_RECENTS_SIZE

    if current_media_type is None: # Playing local
        inf = [None, -1, inf]
    else:
        if current_media_type == 0:
            inf = [YOUTUBE_PLAY_TYPE, current_media_type, inf]
        else:
            inf = [None, current_media_type, inf]

    # Clear atleast 1 space for the new item
    if len(RECENTS_QUEUE) == MAX_RECENTS_SIZE:
        del RECENTS_QUEUE[0]

    # Store item in the newly cleared space
    RECENTS_QUEUE.append(inf)


def open_in_youtube(local_song_file_path):
    if local_song_detected_name := get_song_info(
        local_song_file_path, get_title_only=True
    ):
        _, youtube_search_query_url = YT_query.search_youtube(search=local_song_detected_name)
        webbrowser.open(youtube_search_query_url)
        return 0
    else:
        SAY(visible=visible,
            display_message = 'Could not detect the current audio',
            log_message = 'Could not detect the current audio',
            log_priority = 3)
        return 1


def _media_from_argument(argument):
    if argument.isnumeric() and int(argument) in range(1, len(_sound_files) + 1):
        return MediaRef(MediaSource.LOCAL, str(Path(_sound_files[int(argument) - 1]).resolve()))
    if Path(argument).is_file():
        return MediaRef(MediaSource.LOCAL, str(Path(argument).resolve()))
    if argument.startswith(('http://', 'https://')):
        source = MediaSource.YOUTUBE if any(host in argument for host in ('youtube.com', 'youtu.be')) else MediaSource.URL
        return MediaRef(source, argument, resolver_data={'youtube': source == MediaSource.YOUTUBE})
    raise QueueError(f'Not a library index, local path, or media URL: {argument}')


def _preference_media(media):
    if media and media.source == MediaSource.LOCAL:
        info = LIBRARY.info(media.original_uri)
        if info:
            return MediaRef(
                MediaSource.LOCAL,
                info['canonical_path'],
                stable_id=info['library_id'],
                title=(info.get('metadata') or {}).get('title'),
                artist=(info.get('metadata') or {}).get('artist'),
                album=(info.get('metadata') or {}).get('album'),
                provenance='library',
            )
    return media


def _play_queue_item(item):
    global currentsong, current_media_type, isplaying, currentsong_length
    media = item.media
    items = QUEUE.items()
    position = next((index for index, queued in enumerate(items) if queued.queue_id == item.queue_id), -1)
    neighbors = [
        items[index].media
        for index in (position - 1, position + 1)
        if index in range(len(items))
    ]
    profile = LIBRARY.loudness.get(media.stable_id)
    media.resolver_data['album_context'] = bool(
        profile
        and profile.complete_album
        and media.album
        and any(neighbor.album == media.album and neighbor.artist == media.artist for neighbor in neighbors)
    )
    try:
        if media.source == MediaSource.LOCAL:
            play_local_default_player(media.original_uri, _songindex=None, is_queue=True, media=media)
        else:
            vas.supervisor.play(media)
            _set_current_media_state(media)
    except Exception:
        RECOMMENDER.record_event(media, 'failure')
        action = QUEUE.mark_failure(item.queue_id)
        if action == 'retry':
            return _play_queue_item(item)
        if action == 'skip':
            next_item = QUEUE.next()
            if next_item:
                return _play_queue_item(next_item)
        raise
    RECOMMENDER.record_event(media, 'start')
    _prefetch_after(item)


def _set_current_media_state(media):
    global currentsong, current_media_type, isplaying, currentsong_length
    currentsong = media.title or media.original_uri
    currentsong_length = media.duration or -1
    current_media_type = {
        MediaSource.YOUTUBE: 0,
        MediaSource.URL: 1,
        MediaSource.PODCAST: 1,
        MediaSource.RADIO: 2,
        MediaSource.RECOMMENDATION: 0,
    }.get(media.source)
    isplaying = True


def _prefetch_after(item):
    if not AUTOPLAY_ENABLED:
        return
    items = QUEUE.items()
    try:
        position = next(index for index, queued in enumerate(items) if queued.queue_id == item.queue_id)
        repeat_mode = QUEUE.state().get('repeat_mode')
        candidate = None
        if repeat_mode == 'one':
            candidate = item
        elif position + 1 < len(items):
            candidate = items[position + 1]
        elif repeat_mode == 'all' and items:
            candidate = items[0]
        if candidate and candidate.media.capabilities.finite:
            vas.controller.prefetch(candidate.media)
    except Exception:
        pass


def _on_queue_item_complete(media):
    RECOMMENDER.record_event(media, 'completion')
    STATION.mark_played(media)
    current = QUEUE.current()
    if current is None or current.media.stable_id != media.stable_id:
        RECOMMENDER.retrain_if_due()
        return
    if not AUTOPLAY_ENABLED:
        RECOMMENDER.retrain_if_due()
        return
    next_item = QUEUE.next()
    if next_item is None and QUEUE.state().get('autofill'):
        recommendations = RECOMMENDER.recommend(
            limit=1,
            recent=[Candidate(media)],
            exclude_ids={item.media.stable_id for item in QUEUE.items()},
        )
        if recommendations:
            next_item = QUEUE.add(recommendations[0].media)
            QUEUE.jump(len(QUEUE.items()) - 1)
    if next_item is None:
        RECOMMENDER.retrain_if_due()
        return
    snapshot = vas.controller.snapshot()
    if snapshot.media and snapshot.media.stable_id == next_item.media.stable_id:
        _set_current_media_state(next_item.media)
        RECOMMENDER.record_event(next_item.media, 'start')
        _prefetch_after(next_item)
    else:
        _play_queue_item(next_item)


vas.controller.on_complete = _on_queue_item_complete


def _command_option(arguments, name, *, required=False):
    values = list(arguments)
    if name not in values:
        if required:
            raise ValueError(f'Missing required option: {name}')
        return None, values
    index = values.index(name)
    if index + 1 >= len(values) or values[index + 1].startswith('--'):
        raise ValueError(f'Option {name} requires a value')
    value = values[index + 1]
    del values[index:index + 2]
    return value, values


def _command_flag(arguments, name):
    values = list(arguments)
    enabled = name in values
    if enabled:
        values.remove(name)
    return enabled, values


def _one_based_position(value):
    if value is None:
        return None
    try:
        position = int(value)
    except ValueError as error:
        raise ValueError('Position must be a positive integer') from error
    if position < 1:
        raise ValueError('Position must be a positive integer')
    return position - 1


def _print_queue_tree(nodes, *, playlist=False):
    rows = []

    def visit(values, depth=0):
        for node in values:
            if node['type'] == 'group':
                group = node['group']
                if playlist:
                    name = group.get('name') or 'Group'
                    strategy = group.get('strategy', 'custom')
                    atomic = bool(group.get('atomic', True))
                    priority = int(group.get('priority', 0))
                else:
                    name = group.name
                    strategy = group.strategy.value
                    atomic = group.atomic
                    priority = group.priority
                rows.append((node['path'], '  ' * depth + f'[{name}]', strategy, priority, 'atomic' if atomic else 'open'))
                visit(node.get('children', []), depth + 1)
            else:
                item = node['item']
                media = MediaRef.from_dict(item['media']) if playlist else item.media
                priority = int(item.get('priority', 0)) if playlist else item.priority
                rows.append((node['path'], '  ' * depth + (media.title or media.original_uri), '', priority, 'media'))

    visit(nodes)
    IPrint(tbl(rows, headers=('Path', 'Node', 'Order', 'Priority', 'Policy'), tablefmt='plain') if rows else '(empty)', visible=visible)
    return rows


def _queue_node_payload(node):
    if node['type'] == 'group':
        group = node['group']
        return {
            'type': 'group',
            'id': group.group_id,
            'path': node['path'],
            'name': group.name,
            'kind': group.kind,
            'strategy': group.strategy.value,
            'priority': group.priority,
            'atomic': group.atomic,
            'children': [_queue_node_payload(child) for child in node.get('children', [])],
        }
    item = node['item']
    return {
        'type': 'item',
        'id': str(item.queue_id),
        'path': node['path'],
        'title': item.media.title or item.media.original_uri,
        'artist': item.media.artist,
        'source': item.media.source.value,
        'priority': item.priority,
        'active': bool(QUEUE.current() and QUEUE.current().queue_id == item.queue_id),
    }


def _emit_queue_desktop_state():
    if not getattr(DESKTOP_CONTROL, 'enabled', False):
        return
    DESKTOP_CONTROL.emit(
        'queue',
        {
            'tree': [_queue_node_payload(node) for node in QUEUE.tree()],
            'state': QUEUE.state(),
            'origin': QUEUE.origin(),
            'count': len(QUEUE.items()),
        },
    )
    DESKTOP_CONTROL.emit(
        'playlist',
        {
            'playlists': [
                {
                    'id': playlist.playlist_id,
                    'name': playlist.name,
                    'description': playlist.description,
                    'revision': playlist.revision,
                    'tracks': len(QUEUE.playlists.flattened_media(playlist.tree)),
                }
                for playlist in QUEUE.playlists.list()
            ]
        },
    )


def _album_desktop_payload(album):
    return {
        'id': album.album_id,
        'title': album.title,
        'artist': album.album_artist,
        'release_mbid': album.release_mbid,
        'date': album.date,
        'country': album.country,
        'edition': album.disambiguation,
        'provenance': album.provenance,
        'tracks': [
            {
                'position': track.position,
                'disc': track.disc_number,
                'track': track.track_number,
                'title': track.title,
                'artist': track.artist,
                'duration': track.duration,
                'status': track.resolution_status.value,
            }
            for track in album.tracks
        ],
    }


def _queue_group_command(arguments):
    if not arguments:
        raise QueueError('Usage: queue group create|rename|move|remove|atomic ...')
    action, values = arguments[0].lower(), list(arguments[1:])
    if action == 'create':
        parent, values = _command_option(values, '--parent')
        at, values = _command_option(values, '--at')
        if len(values) != 1:
            raise QueueError('Usage: queue group create "<name>" [--parent <path>] [--at N]')
        group = QUEUE.create_group(values[0], parent=None if parent == 'root' else parent, position=_one_based_position(at))
        IPrint(f'Created queue group: {group.name} [{group.group_id}]', visible=visible)
    elif action == 'rename' and len(values) == 2:
        group = QUEUE.rename_group(values[0], values[1])
        IPrint(f'Renamed queue group: {group.name}', visible=visible)
    elif action == 'move':
        parent, values = _command_option(values, '--parent', required=True)
        at, values = _command_option(values, '--at')
        if len(values) != 1:
            raise QueueError('Usage: queue group move <path> --parent <path|root> [--at N]')
        group = QUEUE.move_group(values[0], parent=None if parent == 'root' else parent, position=_one_based_position(at))
        IPrint(f'Moved queue group: {group.name}', visible=visible)
    elif action == 'remove':
        flatten, values = _command_flag(values, '--flatten')
        recursive, values = _command_flag(values, '--recursive')
        if len(values) != 1 or flatten == recursive:
            raise QueueError('Usage: queue group remove <path> [--flatten|--recursive]')
        group = QUEUE.remove_group(values[0], flatten=flatten, recursive=recursive)
        IPrint(f'Removed queue group: {group.name}', visible=visible)
    elif action == 'atomic' and len(values) == 2 and values[1].lower() in {'on', 'off'}:
        group = QUEUE.set_group_atomic(values[0], values[1].lower() == 'on')
        IPrint(f'Queue group {group.name} is now {"atomic" if group.atomic else "open"}', visible=visible)
    else:
        raise QueueError(f'Invalid queue group command: {action}')


def queue_command(arguments):
    operation = arguments[0].lower() if arguments else 'list'
    if operation == 'list':
        rows = [
            (index + 1, '*' if QUEUE.current() and QUEUE.current().queue_id == item.queue_id else '', item.priority, item.media.title or item.media.original_uri)
            for index, item in enumerate(QUEUE.items())
        ]
        IPrint(tbl(rows, headers=('#', '', 'Priority', 'Media'), tablefmt='plain') if rows else '(queue empty)', visible=visible)
        IPrint(f'Queue source: {QUEUE.origin() or "legacy/custom"}', visible=visible)
    elif operation == 'tree':
        _print_queue_tree(QUEUE.tree())
    elif operation == 'group':
        _queue_group_command(arguments[1:])
    elif operation == 'reset':
        QUEUE.sync_library_defaults(LIBRARY.media_refs(), force=True)
        IPrint(f'Queue reset to {len(QUEUE.items())} library item(s)', visible=visible)
    elif operation in {'add', 'insert'}:
        if operation == 'insert':
            if len(arguments) < 3 or not arguments[1].isdigit():
                raise QueueError('Usage: queue insert <position> <media>')
            position, value = int(arguments[1]) - 1, ' '.join(arguments[2:])
        else:
            if len(arguments) < 2:
                raise QueueError('Usage: queue add <media>')
            position, value = None, ' '.join(arguments[1:])
        item = QUEUE.add(_media_from_argument(value), position=position)
        RECOMMENDER.record_event(item.media, 'manual_queue', candidate=Candidate(item.media))
        IPrint(f'Queued: {item.media.title or item.media.original_uri}', visible=visible)
    elif operation == 'remove':
        QUEUE.remove(int(arguments[1]) - 1)
    elif operation == 'move':
        QUEUE.move(int(arguments[1]) - 1, int(arguments[2]) - 1)
    elif operation == 'swap':
        QUEUE.swap(int(arguments[1]) - 1, int(arguments[2]) - 1)
    elif operation == 'jump':
        _play_queue_item(QUEUE.jump(int(arguments[1]) - 1))
    elif operation in {'next', 'previous'}:
        snapshot = vas.controller.snapshot()
        if operation == 'next' and snapshot.media:
            RECOMMENDER.record_event(
                snapshot.media,
                'early_skip',
                context={'position': snapshot.position, 'duration': snapshot.duration},
            )
            STATION.mark_played(snapshot.media)
        item = QUEUE.next() if operation == 'next' else QUEUE.previous()
        if item:
            _play_queue_item(item)
        else:
            IPrint('(end of queue)', visible=visible)
    elif operation == 'clear':
        QUEUE.clear()
    elif operation == 'shuffle':
        seed = int(arguments[1]) if len(arguments) > 1 else None
        IPrint(f'Shuffle seed: {QUEUE.shuffle(seed)}', visible=visible)
    elif operation == 'order':
        group, values = _command_option(arguments[1:], '--group')
        seed, values = _command_option(values, '--seed')
        if len(values) != 1:
            raise QueueError('Usage: queue order <strategy> [--group <path>] [--seed N]')
        applied_seed = QUEUE.apply_strategy(
            QueueStrategy(values[0].lower()),
            group=group,
            seed=int(seed) if seed is not None else None,
            recommender=RECOMMENDER,
        )
        IPrint(f'Queue order: {values[0]}' + (f' (seed {applied_seed})' if applied_seed is not None else ''), visible=visible)
    elif operation == 'priority':
        if len(arguments) != 3:
            raise QueueError('Usage: queue priority <path> <integer>')
        QUEUE.set_priority(arguments[1], int(arguments[2]))
        IPrint(f'Queue priority set: {arguments[1]} = {arguments[2]}', visible=visible)
    elif operation == 'dedupe':
        if len(arguments) != 2:
            raise QueueError('Usage: queue dedupe identity|uri')
        IPrint(f'Removed {QUEUE.dedupe(arguments[1].lower())} duplicate queue item(s)', visible=visible)
    elif operation == 'repeat':
        QUEUE.set_repeat(arguments[1].lower())
    elif operation == 'consume':
        QUEUE.set_consume(arguments[1].lower() in {'on', 'true', '1'})
    elif operation == 'autofill':
        QUEUE.set_autofill(arguments[1].lower() in {'on', 'true', '1'})
    elif operation == 'save':
        QUEUE.save(' '.join(arguments[1:]))
    elif operation == 'load':
        QUEUE.load(' '.join(arguments[1:]))
    elif operation in {'undo', 'redo'}:
        changed = QUEUE.undo() if operation == 'undo' else QUEUE.redo()
        IPrint('Queue restored' if changed else 'No queue history available', visible=visible)
    else:
        raise QueueError(f'Unknown queue operation: {operation}')
    _emit_queue_desktop_state()


def _playlist_insertion(value):
    if value is None:
        return None, None
    parts = value.split('.')
    if not all(part.isdigit() and int(part) > 0 for part in parts):
        raise PlaylistError('Playlist insertion path must contain positive one-based positions')
    return ('.'.join(parts[:-1]) or None), int(parts[-1]) - 1


def _playlist_import(name, source):
    if source.lower().startswith(('https://www.youtube.com/', 'https://youtube.com/', 'https://youtu.be/')):
        from beta.youtube_media import playlist_entries

        result = playlist_entries(
            source,
            browser_profile=SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile'),
        )
        media = [
            MediaRef(
                MediaSource.YOUTUBE,
                entry['url'],
                title=entry['title'],
                artist=entry.get('artist'),
                duration=entry.get('duration'),
                resolver_data={
                    'youtube': True,
                    'video_id': entry['id'],
                    'playlist_id': result.get('id'),
                    'playlist_index': entry['playlist_index'],
                },
                provenance='youtube-playlist',
            )
            for entry in result['entries']
        ]
        return QUEUE.playlists.create(name, description=f"Snapshot of {result['title']}", tree=PlaylistStore.snapshot_from_media(media))
    return QUEUE.playlists.import_m3u(name, source)


def playlist_command(arguments):
    operation = arguments[0].lower() if arguments else 'list'
    values = list(arguments[1:])
    store = QUEUE.playlists
    if operation == 'list':
        playlists = store.list()
        rows = [(item.name, item.revision, len(store.flattened_media(item.tree)), item.description or '') for item in playlists]
        IPrint(tbl(rows, headers=('Name', 'Revision', 'Tracks', 'Description'), tablefmt='plain') if rows else '(no playlists)', visible=visible)
    elif operation == 'create':
        description, values = _command_option(values, '--description')
        if len(values) != 1:
            raise PlaylistError('Usage: playlist create "<name>" [--description "<text>"]')
        playlist = store.create(values[0], description=description)
        IPrint(f'Created playlist: {playlist.name}', visible=visible)
    elif operation == 'show':
        tree, values = _command_flag(values, '--tree')
        if len(values) != 1:
            raise PlaylistError('Usage: playlist show "<name>" [--tree]')
        playlist = store.get(values[0])
        if tree:
            _print_queue_tree(store.nodes(playlist.playlist_id), playlist=True)
        else:
            rows = [(index + 1, media.artist or '', media.title or media.original_uri) for index, media in enumerate(store.flattened_media(playlist.tree))]
            IPrint(tbl(rows, headers=('#', 'Artist', 'Media'), tablefmt='plain') if rows else '(empty playlist)', visible=visible)
    elif operation == 'rename' and len(values) == 2:
        IPrint(f'Renamed playlist: {store.rename(values[0], values[1]).name}', visible=visible)
    elif operation == 'delete':
        yes, values = _command_flag(values, '--yes')
        if len(values) != 1:
            raise PlaylistError('Usage: playlist delete "<name>" [--yes]')
        if not yes and input(f'Delete playlist "{values[0]}"? (y/N): ').strip().casefold() != 'y':
            IPrint('Playlist deletion cancelled', visible=visible)
            return
        IPrint(f'Deleted playlist: {store.delete(values[0]).name}', visible=visible)
    elif operation == 'clear' and len(values) == 1:
        store.clear(values[0])
        IPrint(f'Cleared playlist: {values[0]}', visible=visible)
    elif operation == 'add':
        at, values = _command_option(values, '--at')
        if len(values) != 3:
            raise PlaylistError('Usage: playlist add "<name>" media|playlist <reference> [--at <path>]')
        parent, position = _playlist_insertion(at)
        if values[1].lower() == 'media':
            playlist = store.add_media(values[0], _media_from_argument(values[2]), parent=parent, position=position)
        elif values[1].lower() == 'album':
            album = ALBUMS.fetch(_album_reference(values[2]))
            snapshot = PlaylistStore.snapshot_from_media(
                [track.media for track in album.tracks if track.media is not None]
            )
            playlist = store.add_snapshot(
                values[0], snapshot, group_name=album.title, parent=parent, position=position,
                kind='album', source_ref=album.album_id,
            )
        elif values[1].lower() == 'playlist':
            source = store.get(values[2])
            playlist = store.add_snapshot(
                values[0], source.tree, group_name=source.name, parent=parent, position=position,
                kind='playlist', source_ref=source.playlist_id,
            )
        else:
            raise PlaylistError('Playlist additions must be media, album, or playlist')
        IPrint(f'Updated playlist: {playlist.name} (revision {playlist.revision})', visible=visible)
    elif operation == 'remove' and len(values) == 2:
        playlist = store.remove_node(values[0], values[1])
        IPrint(f'Updated playlist: {playlist.name} (revision {playlist.revision})', visible=visible)
    elif operation == 'move':
        parent, values = _command_option(values, '--parent', required=True)
        at, values = _command_option(values, '--at')
        if len(values) != 2:
            raise PlaylistError('Usage: playlist move "<name>" <path> --parent <path|root> [--at N]')
        playlist = store.move_node(values[0], values[1], parent=None if parent == 'root' else parent, position=_one_based_position(at))
        IPrint(f'Updated playlist: {playlist.name} (revision {playlist.revision})', visible=visible)
    elif operation == 'order':
        group, values = _command_option(values, '--group')
        seed, values = _command_option(values, '--seed')
        if len(values) != 2:
            raise PlaylistError('Usage: playlist order "<name>" <strategy> [--group <path>] [--seed N]')
        ranks = None
        if values[1].lower() == QueueStrategy.SMART.value:
            media = store.flattened_media(store.get(values[0]).tree)
            ranks = {
                recommendation.media.stable_id: index
                for index, recommendation in enumerate(
                    RECOMMENDER.recommend([Candidate(item) for item in media], limit=len(media))
                )
            }
        playlist = store.order(values[0], values[1], group=group, seed=int(seed) if seed else None, media_ranks=ranks)
        IPrint(f'Updated playlist: {playlist.name} (revision {playlist.revision})', visible=visible)
    elif operation == 'play' and len(values) == 1:
        playlist = store.get(values[0])
        QUEUE.restore_snapshot(playlist.tree, origin=f'playlist:{playlist.playlist_id}')
        item = QUEUE.jump(0) if QUEUE.items() else None
        if item:
            _play_queue_item(item)
        IPrint(f'Loaded playlist: {playlist.name}', visible=visible)
    elif operation == 'queue':
        at, values = _command_option(values, '--at')
        flatten, values = _command_flag(values, '--flatten')
        if len(values) != 1:
            raise PlaylistError('Usage: playlist queue "<name>" [--at next|end|N] [--flatten]')
        playlist = store.get(values[0])
        imported = QUEUE.import_snapshot(
            playlist.tree, name=playlist.name, kind='playlist', source_ref=playlist.playlist_id,
            position=QUEUE.root_insert_position(at), flatten=flatten,
        )
        IPrint(f'Queued {len(imported)} playlist item(s)', visible=visible)
    elif operation == 'import' and len(values) == 2:
        playlist = _playlist_import(values[0], values[1])
        IPrint(f'Imported playlist: {playlist.name} ({len(store.flattened_media(playlist.tree))} tracks)', visible=visible)
    elif operation == 'export' and len(values) == 2:
        IPrint(f'Exported playlist: {store.export_m3u(values[0], values[1])}', visible=visible)
    else:
        raise PlaylistError(f'Invalid playlist command: {operation}')
    _emit_queue_desktop_state()


def _album_reference(value):
    if value != 'current':
        return value
    media = vas.controller.snapshot().media
    if media is None:
        raise AlbumError('No media is currently active')
    reference = media.resolver_data.get('album_id') or media.resolver_data.get('release_mbid')
    if not reference:
        raise AlbumError('The active media has no established album context')
    return str(reference)


def _album_snapshot(album, tracks, *, grouped=True):
    media = [track.media for track in tracks if track.media is not None]
    snapshot = PlaylistStore.snapshot_from_media(media)
    if not grouped:
        return snapshot
    group_id = f'album-{album.album_id}'
    snapshot['groups'] = [
        {
            'group_id': group_id,
            'parent_id': None,
            'name': album.title,
            'kind': 'album',
            'sibling_position': 0,
            'strategy': 'custom',
            'shuffle_seed': None,
            'priority': 0,
            'atomic': True,
            'source_ref': album.album_id,
            'metadata': {
                'release_mbid': album.release_mbid,
                'album_artist': album.album_artist,
                'date': album.date,
            },
        }
    ]
    for item in snapshot['items']:
        item['group_id'] = group_id
    return snapshot


def _album_tracks(reference, *, selector=None, order='release', seed=None, allow_partial=False):
    album = ALBUMS.fetch(_album_reference(reference))
    tracks = ALBUMS.select_tracks(album, selector)
    if order == 'custom' and not selector:
        raise AlbumError('Custom album order requires --tracks <selector>')
    unresolved = [track for track in tracks if track.media is None]
    if unresolved and not allow_partial:
        raise AlbumError(
            f'{len(unresolved)} album track(s) are unresolved; use --allow-partial to continue without them'
        )
    ordered, applied_seed = ALBUMS.order_tracks(
        tracks,
        order,
        seed=seed,
        recommender=RECOMMENDER,
    )
    return album, ordered, applied_seed


def _print_album(album):
    edition = ' / '.join(
        value for value in (album.date, album.country, album.disambiguation) if value
    ) or 'edition unspecified'
    IPrint(
        f'{album.title} — {album.album_artist or "Unknown artist"} ({edition})\n'
        f'Album ID: {album.album_id}; release MBID: {album.release_mbid or "none"}; '
        f'tracks: {len(album.tracks)}; unresolved: {len(album.unresolved_tracks)}',
        visible=visible,
    )


def album_command(arguments):
    operation = arguments[0].lower() if arguments else 'search'
    values = list(arguments[1:])
    if operation == 'search':
        scope, values = _command_option(values, '--scope')
        limit, values = _command_option(values, '--limit')
        query = ' '.join(values).strip()
        albums = ALBUMS.search(query, scope=scope or 'hybrid', limit=int(limit or 10))
        rows = [
            (
                index,
                album.album_artist or '',
                album.title,
                album.date or '',
                album.country or '',
                album.disambiguation or '',
                'local' if 'local-library' in album.provenance else 'online',
            )
            for index, album in enumerate(albums, 1)
        ]
        IPrint(
            tbl(rows, headers=('#', 'Artist', 'Album', 'Date', 'Country', 'Edition', 'Source'), tablefmt='plain')
            if rows else '(no albums found)',
            visible=visible,
        )
        DESKTOP_CONTROL.emit('album', {'view': 'search', 'results': [_album_desktop_payload(album) for album in albums]})
    elif operation == 'show' and len(values) == 1:
        album = ALBUMS.resolve_reference(_album_reference(values[0]))
        _print_album(album)
        DESKTOP_CONTROL.emit('album', {'view': 'album', 'album': _album_desktop_payload(album)})
    elif operation == 'tracks' and len(values) == 1:
        album = ALBUMS.fetch(_album_reference(values[0]))
        rows = [
            (
                f'{track.disc_number}.{track.track_number}',
                track.artist or '',
                track.title,
                round(track.duration) if track.duration is not None else '',
                track.resolution_status.value,
            )
            for track in album.tracks
        ]
        IPrint(tbl(rows, headers=('Track', 'Artist', 'Title', 'Seconds', 'Resolution'), tablefmt='plain'), visible=visible)
        DESKTOP_CONTROL.emit('album', {'view': 'album', 'album': _album_desktop_payload(album)})
    elif operation == 'fetch':
        refresh, values = _command_flag(values, '--refresh')
        if len(values) != 1:
            raise AlbumError('Usage: album fetch <album-ref> [--refresh]')
        album = ALBUMS.fetch(_album_reference(values[0]), refresh=refresh)
        _print_album(album)
        DESKTOP_CONTROL.emit('album', {'view': 'album', 'album': _album_desktop_payload(album)})
    elif operation in {'play', 'queue'}:
        order, values = _command_option(values, '--order')
        selector, values = _command_option(values, '--tracks')
        seed, values = _command_option(values, '--seed')
        allow_partial, values = _command_flag(values, '--allow-partial')
        flatten, values = _command_flag(values, '--flatten')
        at, values = _command_option(values, '--at')
        if len(values) != 1:
            raise AlbumError(
                f'Usage: album {operation} <album-ref> [--order release|shuffle|smart|custom] '
                '[--tracks <selector>] [--seed N] [--allow-partial]'
            )
        if operation == 'play' and (flatten or at is not None):
            raise AlbumError('Album play does not accept --flatten or --at')
        album, tracks, applied_seed = _album_tracks(
            values[0],
            selector=selector,
            order=(order or 'release').lower(),
            seed=int(seed) if seed is not None else None,
            allow_partial=allow_partial,
        )
        snapshot = _album_snapshot(album, tracks, grouped=operation == 'play')
        if operation == 'play':
            QUEUE.restore_snapshot(snapshot, origin=f'album:{album.album_id}')
            item = QUEUE.jump(0) if QUEUE.items() else None
            if item:
                _play_queue_item(item)
        else:
            QUEUE.import_snapshot(
                snapshot,
                name=album.title,
                kind='album',
                source_ref=album.album_id,
                position=QUEUE.root_insert_position(at),
                flatten=flatten,
            )
        IPrint(
            f'Album {operation}: {album.title} ({len([track for track in tracks if track.media])} track(s))'
            + (f'; seed {applied_seed}' if applied_seed is not None else ''),
            visible=visible,
        )
        DESKTOP_CONTROL.emit('album', {'view': 'album', 'album': _album_desktop_payload(album)})
        _emit_queue_desktop_state()
    elif operation == 'save' and len(values) == 2:
        album = ALBUMS.fetch(_album_reference(values[0]))
        playlist = QUEUE.playlists.create(
            values[1],
            description=f'Album snapshot: {album.album_artist or ""} — {album.title}',
            tree=_album_snapshot(album, album.tracks),
        )
        IPrint(f'Saved album as playlist: {playlist.name}', visible=visible)
        DESKTOP_CONTROL.emit('album', {'view': 'album', 'album': _album_desktop_payload(album)})
        _emit_queue_desktop_state()
    else:
        raise AlbumError(f'Invalid album command: {operation}')


def _download_destination(value=None):
    if value:
        return Path(value).expanduser()
    configured = (SETTINGS.get('download') or {}).get('downloads folder')
    destination = Path(configured).expanduser() if configured else Path.home() / 'Music'
    if (SETTINGS.get('download') or {}).get('make a separate mariana folder within "downloads folder"', True):
        folder = ((SYSTEM_SETTINGS.get('system_settings') or {}).get('mariana_dl_dir') or 'Mariana Player')
        destination /= str(folder)
    return destination


def _current_youtube_media():
    if current_media_type == 0 and isinstance(currentsong, (tuple, list)) and len(currentsong) > 1:
        return MediaRef(MediaSource.YOUTUBE, str(currentsong[1]), title=str(currentsong[0]))
    media = vas.controller.snapshot().media
    if media is None:
        raise DownloadJobError('No media is currently active')
    if media.source == MediaSource.LOCAL:
        raise DownloadJobError('The active track is already stored locally and will not be downloaded again')
    if media.source != MediaSource.YOUTUBE:
        raise DownloadJobError('The active media is not a downloadable YouTube track')
    return media


def _confirm_download(message, *, assume_yes=False):
    if assume_yes:
        return True
    answer = input(f'{message} (y/N): ').strip().casefold()
    return answer in {'y', 'yes'}


def _download_album_job(reference, values, *, quality, destination, yes):
    selector, values = _command_option(values, '--tracks')
    missing_only, values = _command_flag(values, '--missing-only')
    allow_partial, values = _command_flag(values, '--allow-partial')
    if values:
        raise DownloadJobError(f'Unknown album download option(s): {" ".join(values)}')
    album = ALBUMS.fetch(_album_reference(reference))
    tracks = ALBUMS.select_tracks(album, selector)
    unresolved = [track for track in tracks if track.media is None]
    if unresolved and not allow_partial:
        raise DownloadJobError(
            f'{len(unresolved)} selected album track(s) are unresolved; use --allow-partial to skip them'
        )
    downloadable = [
        track for track in tracks
        if track.media is not None and track.media.source == MediaSource.YOUTUBE
    ]
    if not downloadable:
        raise DownloadJobError('No selected album tracks require a YouTube download')
    edition = ' / '.join(
        value for value in (album.date, album.country, album.disambiguation) if value
    ) or 'edition unspecified'
    if not _confirm_download(
        f'Download album {album.album_artist or "Unknown artist"} — {album.title} '
        f'({edition}); {len(downloadable)} track(s), {len(unresolved)} unresolved; '
        f'destination {destination}?',
        assume_yes=yes,
    ):
        IPrint('Album download cancelled', visible=visible)
        return None
    metadata = [
        {
            'title': track.title,
            'artist': track.artist,
            'album': album.title,
            'album_artist': album.album_artist,
            'disc_number': track.disc_number,
            'track_number': track.track_number,
            'position': track.position,
            'recording_mbid': track.recording_mbid,
            'release_mbid': track.release_mbid or album.release_mbid,
        }
        for track in downloadable
    ]
    return DOWNLOADS.create(
        [track.media for track in downloadable],
        kind='album',
        quality=quality,
        destination=destination,
        album_id=album.album_id,
        metadata=metadata,
        missing_only=missing_only,
    )


def download_audio_command(arguments):
    values = list(arguments)
    if values and values[0].lower() == 'status':
        if len(values) > 2:
            raise DownloadJobError('Usage: download-ya status [job-id]')
        jobs = DOWNLOADS.status(values[1] if len(values) > 1 else None)
        rows = [
            (
                job['job_id'],
                job['kind'],
                job['state'],
                f"{job['completed_items']}/{job['total_items']}",
                job.get('current_position') or '',
                job.get('error') or '',
            )
            for job in jobs
        ]
        IPrint(
            tbl(rows, headers=('Job', 'Kind', 'State', 'Done', 'Current', 'Error'), tablefmt='plain')
            if rows else '(no download jobs)',
            visible=visible,
        )
        return jobs
    if values and values[0].lower() in {'pause', 'resume', 'cancel'}:
        if len(values) != 2:
            raise DownloadJobError(f'Usage: download-ya {values[0].lower()} <job-id>')
        action = values[0].lower()
        job = getattr(DOWNLOADS, action)(values[1])
        IPrint(f'Download job {job.job_id}: {job.state.value}', visible=visible)
        return job

    album_mode, values = _command_flag(values, '--album')
    track_mode, values = _command_flag(values, '--track')
    quality, values = _command_option(values, '--quality')
    destination_value, values = _command_option(values, '--to')
    yes, values = _command_flag(values, '--yes')
    quality = (quality or 'best').lower()
    destination = _download_destination(destination_value)
    if quality not in {'best', 'worst'}:
        raise DownloadJobError('Download quality must be best or worst')
    if destination.exists() and not destination.is_dir():
        raise DownloadJobError('Download destination must be a directory')
    if album_mode and track_mode:
        raise DownloadJobError('Choose either --album or --track, not both')
    if album_mode:
        reference = values.pop(0) if values and not values[0].startswith('--') else 'current'
        job = _download_album_job(
            reference,
            values,
            quality=quality,
            destination=destination,
            yes=yes,
        )
    else:
        if any(value.startswith('--') for value in values):
            raise DownloadJobError(f'Unknown track download option(s): {" ".join(values)}')
        if len(values) > 1:
            raise DownloadJobError('Usage: download-ya [current|<YouTube-video-URL>] [--track] [options]')
        target = values[0] if values else 'current'
        media = _current_youtube_media() if target == 'current' else MediaRef(MediaSource.YOUTUBE, target)
        if not _confirm_download(
            f'Download YouTube audio {media.title or media.original_uri} to {destination}?',
            assume_yes=yes,
        ):
            IPrint('Audio download cancelled', visible=visible)
            return None
        job = DOWNLOADS.create(
            [media],
            kind='track',
            quality=quality,
            destination=destination,
            metadata=[{'title': media.title, 'artist': media.artist}],
        )
    del track_mode
    if job:
        IPrint(f'Download job queued: {job.job_id}', visible=visible)
    return job


def library_command(arguments):
    operation = arguments[0].lower() if arguments else 'status'
    if operation == 'roots':
        rows = [
            (
                root['path'],
                root.get('origin', 'library-file'),
                root['kind'],
                'online' if root['available'] else 'offline',
                root['error'] or '',
            )
            for root in LIBRARY.sync_roots()
        ]
        IPrint(
            tbl(rows, headers=('Path', 'Origin', 'Kind', 'State', 'Error'), tablefmt='plain')
            if rows else '(no roots)',
            visible=visible,
        )
    elif operation == 'scan':
        mode = arguments[1].lower() if len(arguments) > 1 else 'changed'
        result = LIBRARY.scan(mode)
        reload_sounds(quick_load=True)
        IPrint(
            f'Library scan complete: {result.discovered} discovered, {result.changed} changed, '
            f'{result.unavailable_roots} unavailable roots, {result.errors} errors',
            visible=visible,
        )
    elif operation == 'status':
        status = LIBRARY_SERVICE.status()
        files = status['files']
        service = status['service']
        IPrint(
            f"Library: {files.get('available') or 0} available, {files.get('missing') or 0} missing; "
            f"profiler={'paused' if service['paused'] else 'running' if service['running'] else 'stopped'}",
            visible=visible,
        )
        if status['jobs']:
            IPrint(tbl(
                [(job['stage'], job['status'], job['count']) for job in status['jobs']],
                headers=('Stage', 'State', 'Count'),
                tablefmt='plain',
            ), visible=visible)
    elif operation in {'pause', 'resume'}:
        LIBRARY_SERVICE.pause() if operation == 'pause' else LIBRARY_SERVICE.resume()
        IPrint(f'Library profiler {operation}d', visible=visible)
    elif operation == 'errors':
        errors = LIBRARY.errors()
        IPrint(tbl(
            [(error['library_id'], error['stage'], error['attempts'], error['canonical_path'], error['error_text']) for error in errors],
            headers=('ID', 'Stage', 'Attempts', 'Path', 'Error'),
            tablefmt='plain',
        ) if errors else '(no profiling errors)', visible=visible)
    elif operation == 'retry':
        target = None
        if len(arguments) > 1 and arguments[1].lower() != 'all':
            info = LIBRARY.info(' '.join(arguments[1:]))
            if not info:
                raise LibraryError('Unknown library item')
            target = info['library_id']
        IPrint(f'Reset {LIBRARY.retry(target)} failed profiling jobs', visible=visible)
    elif operation == 'verify':
        result = LIBRARY.verify()
        IPrint(f"Database: {result['database']}; unavailable indexed paths: {len(result['unavailable_paths'])}", visible=visible)
    elif operation == 'clean' and arguments[1:] == ['--missing']:
        IPrint(f'Removed {LIBRARY.clean_missing()} missing library records; media files were not deleted', visible=visible)
    elif operation == 'info' and len(arguments) > 1:
        result = LIBRARY.info(' '.join(arguments[1:]))
        if not result:
            raise LibraryError('Unknown library item')
        IPrint(json.dumps(result, indent=2, ensure_ascii=False, default=str), visible=visible)
    else:
        raise LibraryError(f'Unknown library operation: {operation}')


def _format_sleep_duration(seconds):
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


def sleep_command(arguments):
    if not arguments or arguments[0].lower() == 'status':
        status = SLEEP_TIMER.status()
        if not status.active:
            IPrint('Sleep timer is inactive', visible=visible)
        else:
            IPrint(
                f'Sleep timer: {_format_sleep_duration(status.remaining_seconds)} remaining; '
                f'action={status.action.value}; fade={_format_sleep_duration(status.fade_seconds)}',
                visible=visible,
            )
        return status
    if arguments[0].lower() == 'cancel':
        cancelled = SLEEP_TIMER.cancel()
        IPrint('Sleep timer cancelled' if cancelled else 'Sleep timer was not active', visible=visible)
        return SLEEP_TIMER.status()

    duration = parse_duration(arguments[0])
    action = SleepAction.PAUSE
    fade = None
    index = 1
    if index < len(arguments) and arguments[index].lower() in {'pause', 'stop'}:
        action = SleepAction(arguments[index].lower())
        index += 1
    if index < len(arguments):
        if arguments[index].lower() != 'fade' or index + 2 != len(arguments):
            raise ValueError('Usage: sleep <duration> [pause|stop] [fade <duration>]')
        fade = parse_duration(arguments[index + 1])
    status = SLEEP_TIMER.start(duration, action=action, fade_seconds=fade)
    IPrint(
        f'Sleep timer set for {_format_sleep_duration(duration)}; action={action.value}; '
        f'fade={_format_sleep_duration(status.fade_seconds)}',
        visible=visible,
    )
    return status


def replaygain_command(arguments):
    operation = arguments[0].lower() if arguments else 'status'
    if operation in {'status', 'verify'}:
        snapshot = vas.controller.snapshot()
        media = snapshot.media
        profile = LIBRARY.loudness.get(media.stable_id) if media else None
        analyzer = getattr(LIBRARY, 'rsgain', RSGainAnalyzer(MEDIA_TOOLS.get('rsgain bin')))
        try:
            analyzer_path, analyzer_version = analyzer.verify()
            analyzer_status = f'available ({analyzer_version}; {analyzer_path})'
        except LoudnessError as error:
            analyzer_status = f'unavailable ({error})'
        if operation == 'verify':
            if analyzer_status.startswith('unavailable'):
                raise LoudnessError(analyzer_status)
            IPrint(
                f'ReplayGain analyzer verified: {analyzer_status}. Scans are read-only and never modify media.',
                visible=visible,
            )
            return analyzer_path, analyzer_version
        state = 'on' if vas.controller.replaygain_enabled else 'off'
        profile_status = profile.source if profile else ('not analyzed for current track' if media else 'no active track')
        IPrint(
            f'ReplayGain: {state}; mode={vas.controller.replaygain_mode}; '
            f'preamp={vas.controller.replaygain_preamp_db:g} dB; applied={snapshot.replaygain_db:g} dB; '
            f'profile={profile_status}; analyzer={analyzer_status}',
            visible=visible,
        )
        return snapshot
    if operation == 'on':
        mode = arguments[1].lower() if len(arguments) > 1 else vas.controller.replaygain_mode
        vas.controller.configure_replaygain(enabled=True, mode=mode)
        REPLAYGAIN_SETTINGS.update({'enabled': True, 'mode': mode})
        DATABASE.set_state('replaygain', REPLAYGAIN_SETTINGS)
        LIBRARY_SERVICE.enable_loudness()
        scheduled = LIBRARY.schedule_loudness('changed')
        IPrint(f'ReplayGain enabled in {mode} mode; {scheduled} track(s) scheduled for analysis', visible=visible)
    elif operation == 'off':
        vas.controller.configure_replaygain(enabled=False)
        REPLAYGAIN_SETTINGS['enabled'] = False
        DATABASE.set_state('replaygain', REPLAYGAIN_SETTINGS)
        IPrint('ReplayGain disabled', visible=visible)
    elif operation == 'mode' and len(arguments) == 2:
        mode = arguments[1].lower()
        vas.controller.configure_replaygain(mode=mode)
        REPLAYGAIN_SETTINGS['mode'] = mode
        DATABASE.set_state('replaygain', REPLAYGAIN_SETTINGS)
        IPrint(f'ReplayGain mode: {mode}', visible=visible)
    elif operation == 'preamp' and len(arguments) == 2:
        value = float(arguments[1])
        vas.controller.configure_replaygain(preamp_db=value)
        REPLAYGAIN_SETTINGS['preamp db'] = value
        DATABASE.set_state('replaygain', REPLAYGAIN_SETTINGS)
        IPrint(f'ReplayGain preamp: {value:g} dB', visible=visible)
    elif operation == 'scan':
        mode = arguments[1].lower() if len(arguments) > 1 else 'changed'
        LIBRARY_SERVICE.enable_loudness()
        count = LIBRARY.schedule_loudness(mode)
        IPrint(f'Scheduled loudness analysis for {count} track(s)', visible=visible)
    elif operation == 'rescan' and len(arguments) > 1:
        info = LIBRARY.info(' '.join(arguments[1:]))
        if not info:
            raise LibraryError('Unknown library item')
        LIBRARY.loudness.delete(info['library_id'])
        LIBRARY_SERVICE.enable_loudness()
        LIBRARY.schedule_loudness('full', info['library_id'])
        IPrint(f"Scheduled loudness rescan for {info['canonical_path']}", visible=visible)
    else:
        raise ValueError(
            'Usage: replaygain [on [track|album|auto]|off|status|mode <mode>|preamp <dB>|'
            'scan [changed|full]|rescan <library-id|path>|verify]'
        )


def broadcast_command(arguments):
    operation = arguments[0].lower() if arguments else 'status'
    if operation == 'profiles':
        rows = [
            (profile.name, profile.codec, f'{profile.bitrate_kbps} kbps', profile.station_name)
            for profile in BROADCASTER.profiles.values()
        ]
        IPrint(tbl(rows, headers=('Profile', 'Codec', 'Bitrate', 'Station'), tablefmt='plain') if rows else '(no broadcast profiles)', visible=visible)
    elif operation == 'credentials' and len(arguments) >= 3:
        action, name = arguments[1].lower(), arguments[2]
        if name not in BROADCASTER.profiles:
            raise BroadcastError(f'Unknown broadcast profile: {name}')
        reference = BROADCASTER.profiles[name].reference
        if action == 'set':
            BROADCASTER.credentials.set(reference, getpass(f'Icecast password for {name}: '))
            IPrint(f'Credential stored in the operating-system keychain for {name}', visible=visible)
        elif action == 'delete':
            deleted = BROADCASTER.credentials.delete(reference)
            IPrint('Credential deleted' if deleted else 'No keychain credential was stored', visible=visible)
        elif action == 'status':
            status = BROADCASTER.credentials.status(reference)
            IPrint(
                f'Credential for {name}: {"available" if status["available"] else "missing"}; '
                f'source={status["source"]}; headless override={status["environment"]}',
                visible=visible,
            )
        else:
            raise BroadcastError('Usage: broadcast credentials set|delete|status <profile>')
    elif operation in {'start', 'test'} and len(arguments) == 2:
        if operation == 'start':
            BROADCASTER.start(arguments[1])
            media = vas.controller.snapshot().media
            if media:
                BROADCASTER.metadata(' - '.join(value for value in (media.artist, media.title) if value) or media.title)
            IPrint(f'Broadcast connecting with profile {arguments[1]}', visible=visible)
        else:
            IPrint(
                'Broadcast connection test passed' if BROADCASTER.test(arguments[1]) else 'Broadcast connection test failed',
                visible=visible,
            )
    elif operation == 'stop':
        BROADCASTER.stop()
        IPrint('Broadcast stopped', visible=visible)
    elif operation == 'status':
        status = BROADCASTER.snapshot()
        IPrint(
            f'Broadcast: {status.state.value}; profile={status.profile or "none"}; codec={status.codec or "none"}; '
            f'reconnects={status.reconnects}; dropped blocks={status.dropped_blocks}; '
            f'title={status.title or "none"}; error={status.error or "none"}',
            visible=visible,
        )
        return status
    else:
        raise BroadcastError(
            'Usage: broadcast [profiles|credentials set|delete|status <profile>|test <profile>|'
            'start <profile>|stop|status]'
        )


def prepare_update():
    backup_root = RUNTIME_PATHS.state('backups', f'pre-{__version__}-{int(time.time())}')
    backup_root.mkdir(parents=True, exist_ok=False)
    database_backup = DATABASE.backup(backup_root / 'mariana.db')
    copied = []
    for source in (RUNTIME_PATHS.settings, RUNTIME_PATHS.library_file, RUNTIME_PATHS.user_data):
        if source.is_file():
            destination = backup_root / source.name
            shutil.copy2(source, destination)
            copied.append(destination.name)
    manifest = backup_root / 'manifest.json'
    manifest.write_text(
        json.dumps({'version': __version__, 'database': database_backup.name, 'files': copied}, indent=2),
        encoding='utf-8',
    )
    DESKTOP_CONTROL.emit('update-prepared', {'backup': str(backup_root)})
    IPrint(f'Update backup prepared at {backup_root}', visible=visible)
    return backup_root


def youtube_browser_profile():
    return SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile') or None


def report_youtube_error(error, operation='operation'):
    profile = youtube_browser_profile()
    message = youtube_error_message(error, profile)
    if message is None:
        message = str(error) if isinstance(error, MediaFailure) else f'YouTube {operation} failed: {error}'
    SAY(
        visible=visible,
        display_message=message,
        log_message=f'YouTube {operation} failed: {error}',
        log_priority=2,
    )
    return message


def youtube_auth_command(arguments):
    operation = arguments[0].lower() if arguments else 'status'
    current = youtube_browser_profile()
    if operation == 'status':
        message = f'YouTube browser profile: {current or "not configured (anonymous access)"}'
        IPrint(message, visible=visible)
        return current
    if operation == 'set':
        if len(arguments) < 2:
            raise ValueError('Usage: youtube auth set <browser[:profile]>')
        profile = ' '.join(arguments[1:]).strip().strip('"\'')
        parse_browser_profile(profile)
    elif operation in {'clear', 'off', 'unset'}:
        if len(arguments) != 1:
            raise ValueError('Usage: youtube auth clear')
        profile = None
    elif operation == 'test':
        if len(arguments) != 2:
            raise ValueError('Usage: youtube auth test <YouTube URL>')
        result = resolve_stream(arguments[1], browser_profile=current)
        IPrint(f'YouTube access test passed: {result.get("title") or "media resolved"}', visible=visible)
        return result
    else:
        raise ValueError(
            'Usage: youtube auth [status|set <browser[:profile]>|clear|test <YouTube URL>]'
        )

    sources = SETTINGS.setdefault('sources', {})
    youtube_settings = sources.setdefault('youtube', {})
    previous = youtube_settings.get('browser profile')
    youtube_settings['browser profile'] = profile
    try:
        save_user_settings(SETTINGS, RUNTIME_PATHS.settings)
    except Exception:
        youtube_settings['browser profile'] = previous
        raise
    YT_query.configure(browser_profile=profile)
    vas.set_youtube_browser_profile(profile)
    if profile:
        IPrint(
            f'YouTube browser profile set to {profile}. Cookies are read by yt-dlp only during YouTube commands.',
            visible=visible,
        )
    else:
        IPrint('YouTube browser authentication cleared; anonymous access is active.', visible=visible)
    return profile


def tools_command(arguments):
    operation = arguments[0].lower() if arguments else 'status'
    if operation == 'status':
        status = discover_media_tools(SETTINGS)
        rows = []
        for name in ('ffmpeg', 'ffprobe', 'ffplay', 'fpcalc', 'rsgain'):
            rows.append((name, status.executables.get(name) or 'not found', status.versions.get(name) or 'unavailable'))
        javascript = find_javascript_runtime()
        rows.append((javascript[0] if javascript else 'JavaScript', javascript[1] if javascript else 'not found', 'available' if javascript else 'unavailable'))
        IPrint(tbl(rows, headers=('Tool', 'Resolved path', 'Version'), tablefmt='plain'), visible=visible)
        return rows
    if operation == 'setup':
        status = setup_media_tools(SETTINGS, paths=RUNTIME_PATHS, manager=TOOLCHAIN)
        MEDIA_TOOLS.update(load_user_settings().get('media tools', {}))
        IPrint(
            'Media tools are configured. Restart Mariana if you selected manually installed paths.',
            visible=visible,
        )
        return status
    if operation in {'install', 'repair'}:
        root = TOOLCHAIN.install_recommended(progress=lambda message: IPrint(message, visible=visible))
        IPrint(f'Managed media tools are ready at {root}', visible=visible)
        return root
    raise ValueError('Usage: tools [status|setup|install|repair]')


def setup_command(arguments):
    operation = arguments[0].lower() if arguments else 'status'
    if operation == 'status':
        try:
            state = SETUP_STORE.load()
            IPrint(
                f'Setup: {state.status}; current={state.current_step or "none"}; '
                f'completed={", ".join(state.completed_steps) or "none"}',
                visible=visible,
            )
            return state
        except SetupStateError as error:
            IPrint(f'Setup state is corrupt: {error}', visible=visible)
            return None
    if operation == 'repair':
        backup = SETUP_STORE.repair()
        IPrint(f'Setup state repaired; backup={backup or "none"}. Run "setup resume".', visible=visible)
        return SETUP_STORE.load()
    if operation == 'restart':
        SETUP_STORE.reset()
    elif operation != 'resume':
        raise ValueError('Usage: setup status|resume|restart|repair')
    import first_boot_setup

    skipped = first_boot_setup.fbs(SYSTEM_SETTINGS, SETUP_STORE)
    reload_sounds(quick_load=False)
    if skipped:
        IPrint('Setup completed; playback was not started', visible=visible)
    return SETUP_STORE.load()


def radio_command(arguments):
    operation = arguments[0].lower() if arguments else 'list'
    if operation == 'list':
        stations = RADIO.list(favorites=len(arguments) > 1 and arguments[1] == 'favorites')
        IPrint(tbl([(station.slug, station.name, station.provider) for station in stations], headers=('ID', 'Station', 'Source'), tablefmt='plain'), visible=visible)
    elif operation == 'search':
        stations = RADIO.search(' '.join(arguments[1:]))
        IPrint(tbl([(station.slug, station.name, station.country or '') for station in stations], headers=('ID', 'Station', 'Country'), tablefmt='plain'), visible=visible)
    elif operation == 'play':
        station = RADIO.get(arguments[1])
        endpoint = RADIO.endpoints(station)[0]
        credential = RADIO.credential(station.station_id) or {}
        item = QUEUE.add(
            MediaRef(
                MediaSource.RADIO,
                endpoint,
                title=station.name,
                resolver_data={
                    'station_id': station.station_id,
                    'station_slug': station.slug,
                    'endpoints': RADIO.endpoints(station),
                    'credential_ref': credential.get('reference'),
                    'credential_username': credential.get('username'),
                },
                capabilities=MediaCapabilities(
                    finite=False,
                    live=True,
                    seekable=False,
                    downloadable=False,
                ),
            ),
            allow_duplicate=True,
        )
        QUEUE.jump(len(QUEUE.items()) - 1)
        _play_queue_item(item)
    elif operation == 'add' and len(arguments) > 1:
        station = RADIO.add(arguments[1], ' '.join(arguments[2:]) or None)
        IPrint(f'Added radio station: {station.name} ({station.slug})', visible=visible)
    elif operation == 'info' and len(arguments) == 2:
        station = RADIO.get(arguments[1])
        IPrint(json.dumps({
            'id': station.slug,
            'name': station.name,
            'provider': station.provider,
            'homepage': station.homepage,
            'country': station.country,
            'language': station.language,
            'tags': station.tags,
            'endpoints': RADIO.endpoints(station),
            'last healthy endpoint': station.last_healthy_endpoint,
            'failure count': station.failure_count,
        }, indent=2, ensure_ascii=False), visible=visible)
    elif operation == 'metadata':
        metadata = vas.controller.snapshot().stream_metadata
        IPrint(json.dumps(metadata, indent=2, ensure_ascii=False) if metadata else '(no ICY metadata)', visible=visible)
    elif operation == 'resync':
        vas.controller.restart_live()
        IPrint('Radio resynchronized at the live edge', visible=visible)
    elif operation == 'leveling':
        action = arguments[1].lower() if len(arguments) > 1 else 'status'
        if action in {'on', 'off'}:
            enabled = action == 'on'
            vas.controller.set_live_leveling(enabled)
            LIVE_LEVELING_SETTINGS['enabled'] = enabled
            DATABASE.set_state('radio_live_leveling', LIVE_LEVELING_SETTINGS)
        elif action != 'status':
            raise RadioError('Usage: radio leveling [on|off|status]')
        IPrint(
            f'Radio live leveling: {"on" if vas.controller.live_leveling else "off"}; '
            f'target={vas.controller.live_target_lufs:g} LUFS; '
            f'peak={vas.controller.live_true_peak_dbtp:g} dBTP; LRA={vas.controller.live_lra:g}',
            visible=visible,
        )
    elif operation == 'credentials' and len(arguments) >= 3:
        action, station_name = arguments[1].lower(), arguments[2]
        station = RADIO.get(station_name)
        reference = f'radio:{station.station_id}'
        if action == 'set':
            username = arguments[3] if len(arguments) > 3 else 'source'
            CredentialStore().set(reference, getpass(f'Private-stream password for {station.name}: '))
            RADIO.set_credential(station.station_id, reference, username)
            IPrint(f'Private-stream credential stored for {station.name}', visible=visible)
        elif action == 'delete':
            deleted = CredentialStore().delete(reference)
            IPrint('Credential deleted' if deleted else 'No keychain credential was stored', visible=visible)
        elif action == 'status':
            status = CredentialStore().status(reference)
            IPrint(f'Private-stream credential: {"available" if status["available"] else "missing"}', visible=visible)
        else:
            raise RadioError('Usage: radio credentials set|delete|status <station> [username]')
    elif operation == 'favorite':
        station = RADIO.favorite(arguments[1], not (len(arguments) > 2 and arguments[2].lower() == 'off'))
        IPrint(f'Favorite updated: {station.name}', visible=visible)
    elif operation in {'health', 'refresh'}:
        stations = [RADIO.get(arguments[1])] if len(arguments) > 1 else RADIO.list()
        for station in stations:
            IPrint(RADIO.health(station.station_id, ffmpeg_bin=MEDIA_TOOLS.get('ffmpeg bin'), force=operation == 'refresh'), visible=visible)
    else:
        raise RadioError(f'Unknown radio operation: {operation}')


def recommendation_command(arguments):
    operation = arguments[0].lower() if arguments else 'list'
    snapshot_media = _preference_media(vas.controller.snapshot().media)
    recent = [Candidate(snapshot_media)] if snapshot_media else []
    if operation in {'list', 'show', 'related'}:
        count = int(arguments[1]) if len(arguments) > 1 else 10
        excluded = {snapshot_media.stable_id} if operation == 'related' and snapshot_media else set()
        if operation == 'related' and not snapshot_media:
            raise QueueError('No active media is available for related recommendations')
        results = RECOMMENDER.recommend(limit=count, recent=recent, exclude_ids=excluded)
        IPrint(tbl([(index + 1, result.media.title or result.media.original_uri, '; '.join(result.reasons)) for index, result in enumerate(results)], headers=('#', 'Track', 'Why'), tablefmt='plain'), visible=visible)
    elif operation == 'autofill':
        count = int(arguments[1]) if len(arguments) > 1 else 10
        for result in RECOMMENDER.recommend(
            limit=count,
            recent=recent,
            exclude_ids={item.media.stable_id for item in QUEUE.items()},
        ):
            QUEUE.add(result.media)
    elif operation == 'train':
        model = RECOMMENDER.retrain_if_due(force=True)
        IPrint(f'Active model: {model}', visible=visible)
    else:
        raise QueueError(f'Unknown recommendation operation: {operation}')


def _station_seed(value):
    if value in {None, '', 'current'}:
        media = _preference_media(vas.controller.snapshot().media)
        if not media:
            raise StationError('No current media is available to seed a station')
        return media
    media = _preference_media(_media_from_argument(value))
    if media.source == MediaSource.YOUTUBE:
        profile = SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile')
        details = media_info(media.original_uri, detailed=True, browser_profile=profile)
        categories = [str(item) for item in details.get('categories', [])]
        media.title = details.get('title')
        media.artist = details.get('artist')
        media.album = details.get('album')
        media.duration = details.get('duration')
        media.capabilities = MediaCapabilities(
            finite=not details.get('is_live'),
            live=bool(details.get('is_live')),
            seekable=not details.get('is_live'),
            metadata_available=True,
        )
        media.resolver_data.update({
            'youtube': True,
            'categories': categories,
            'track': details.get('track'),
            'artist': details.get('artist'),
            'is_music': bool(details.get('track') and details.get('artist'))
            or any(item.casefold() == 'music' for item in categories),
        })
    return media


def _station_rows(count=10):
    return [
        (
            index + 1,
            item['media'].title or item['media'].original_uri,
            item['media'].artist or '',
            '; '.join(item['reasons']),
        )
        for index, item in enumerate(STATION.items(count))
    ]


def _wait_for_station_initial(timeout=5.0):
    frames = ('|', '/', '-', '\\')
    deadline = time.monotonic() + timeout
    index = 0
    while time.monotonic() < deadline:
        session = STATION.session()
        if not session or session.state.value != 'loading':
            break
        if visible:
            print(f'\r{frames[index % len(frames)]} Station: {session.progress_message or "loading"}', end='', flush=True)
        index += 1
        time.sleep(0.1)
    if visible:
        print('\r' + (' ' * 80) + '\r', end='', flush=True)
    return STATION.wait_initial(0)


def station_command(arguments):
    operation = arguments[0].casefold() if arguments else 'status'
    if operation == 'start':
        scope = 'hybrid'
        limit = 50
        target_parts = []
        index = 1
        while index < len(arguments):
            token = arguments[index]
            if token == '--scope' and index + 1 < len(arguments):
                scope = arguments[index + 1].casefold()
                index += 2
            elif token == '--limit' and index + 1 < len(arguments):
                limit = int(arguments[index + 1])
                index += 2
            elif token == '--unlimited':
                limit = None
                index += 1
            elif token.startswith('--'):
                raise StationError(f'Unknown station option: {token}')
            else:
                target_parts.append(token)
                index += 1
        seed = _station_seed(' '.join(target_parts) if target_parts else 'current')
        current = vas.controller.snapshot().media
        STATION.start(seed, scope=scope, limit=limit)
        if not current or current.stable_id != seed.stable_id:
            _play_queue_item(QUEUE.current())
        try:
            session = _wait_for_station_initial()
        except KeyboardInterrupt:
            STATION.stop()
            IPrint('\nStation start cancelled; previous queue restored.', visible=visible)
            return None
        IPrint(
            f'Station: {session.state.value}; {session.ready_ahead}/10 ready; '
            f'{session.generated_count}/{session.limit if session.limit is not None else "unlimited"} generated',
            visible=visible,
        )
        rows = _station_rows()
        IPrint(
            tbl(rows, headers=('#', 'Track', 'Artist', 'Why'), tablefmt='plain')
            if rows else '(no recommendations yet)',
            visible=visible,
        )
        return session
    if operation == 'status':
        session = STATION.session()
        if not session:
            IPrint('Station: stopped', visible=visible)
            return None
        IPrint(
            f'Station: {session.state.value}; scope={session.scope}; ready={session.ready_ahead}/10; '
            f'generated={session.generated_count}; limit={session.limit if session.limit is not None else "unlimited"}; '
            f'{session.progress_message or ""}',
            visible=visible,
        )
        return session
    if operation == 'list':
        count = int(arguments[1]) if len(arguments) > 1 else 10
        rows = _station_rows(count)
        IPrint(
            tbl(rows, headers=('#', 'Track', 'Artist', 'Why'), tablefmt='plain') if rows else '(none)',
            visible=visible,
        )
        return rows
    if operation == 'more':
        count = int(arguments[1]) if len(arguments) > 1 else 10
        STATION.more(count)
        try:
            session = _wait_for_station_initial()
        except KeyboardInterrupt:
            STATION.cancel_generation()
            IPrint('\nStation refill cancelled; validated tracks retained.', visible=visible)
            return STATION.session()
        IPrint(f'Station: {session.state.value}; {session.ready_ahead}/10 ready', visible=visible)
        return session
    if operation == 'pause':
        STATION.pause()
    elif operation == 'resume':
        STATION.resume()
        if vas.controller.snapshot().state not in {
            PlaybackState.PLAYING,
            PlaybackState.BUFFERING,
            PlaybackState.CROSSFADING,
        } and QUEUE.current():
            _play_queue_item(QUEUE.current())
    elif operation == 'stop':
        STATION.stop()
    else:
        raise StationError(
            'Usage: station start [current|index|path|youtube-url] [--scope hybrid|local|online] '
            '[--limit N|--unlimited] | status | list [count] | more [count] | pause | resume | stop'
        )
    IPrint({'pause': 'Station paused', 'resume': 'Station resumed', 'stop': 'Station stopped'}[operation], visible=visible)
    return STATION.session()


def preference_command(arguments, state):
    media = _preference_media(vas.controller.snapshot().media)
    if not media:
        raise ValueError('No active media')
    state = PreferenceState(state)
    operation = arguments[0] if arguments else None
    if operation is None:
        current = PREFERENCES.get(media)
    elif operation == '!':
        current = PREFERENCES.toggle(media, state)
    elif operation in {'+', '-'}:
        current = state if operation == '+' else PreferenceState.NEUTRAL
        PREFERENCES.set(media, current)
    else:
        raise ValueError('Usage: fav|bl [!|+|-]')
    IPrint(f'Preference: {current.value}', visible=visible)
    return current


def list_preferences(state, arguments):
    if len(arguments) > 1 or (arguments and not arguments[0].isdigit()):
        raise ValueError('Preference list accepts an optional numeric limit')
    limit = int(arguments[0]) if arguments else MAX_RESULT_COUNT
    entries = PREFERENCES.list(state, limit)
    IPrint(
        tbl(
            [(index + 1, entry.label, entry.uri or '') for index, entry in enumerate(entries)],
            headers=('#', 'Track', 'Location'),
            tablefmt='plain',
        ) if entries else '(none)',
        visible=visible,
    )
    return entries


def set_download_library_inclusion(enabled):
    DATABASE.set_state('library_include_downloads', bool(enabled))
    LIBRARY.sync_roots()
    result = LIBRARY.scan('changed')
    reload_sounds(quick_load=True)
    IPrint(
        f'Download directory {"included in" if enabled else "excluded from"} the library; '
        f'{result.changed} files changed',
        visible=visible,
    )
    return result


def advanced_search_command(tokens):
    request = parse_search(tokens)
    results = search_rows(_sound_files_names_enumerated, request)
    if not results:
        IPrint(colored.fg('hot_pink_1a') + '-- No results found --' + colored.attr('reset'), visible=visible)
        return []
    if request.action == SearchAction.FIRST:
        local_play_commands([None, str(results[0][0])])
    elif request.action == SearchAction.RANDOM:
        local_play_commands([None, str(rand.choice(results)[0])])
    else:
        IPrint(
            f'Found {len(results)} match{("es" if len(results) != 1 else "")}: '
            f'{" ".join(request.query)}',
            visible=visible,
        )
        IPrint(tbl(results, tablefmt='mysql', headers=('#', 'Song')), visible=visible)
    return results


def edit_current_lyrics():
    global DEFAULT_EDITOR
    media = _preference_media(vas.controller.snapshot().media)
    if not media or media.source != MediaSource.LOCAL:
        raise ValueError('Lyrics can be edited only for a currently loaded local file')
    source = Path(media.original_uri)
    if not source.is_file():
        raise ValueError('The current local media file is unavailable')
    sidecar = source.with_suffix('.lrc')
    if not sidecar.exists():
        identity = IDENTITY.identify(media, pcm=vas.controller.fingerprint_pcm())
        result = IDENTITY.lyrics(media, identity)
        content = result.synced or result.plain
        if not content:
            raise ValueError('No lyrics are available to create an LRC sidecar')
        permission = input(f'Create adjacent lyrics file "{sidecar}"? (y/n): ').casefold().strip()
        if permission not in {'y', 'yes'}:
            IPrint('Lyrics edit cancelled', visible=visible)
            return None
        descriptor, temporary_name = tempfile.mkstemp(prefix=f'.{sidecar.name}.', dir=sidecar.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                stream.write(content.rstrip() + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, sidecar)
        finally:
            temporary.unlink(missing_ok=True)
    if DEFAULT_EDITOR:
        sp.Popen([DEFAULT_EDITOR, str(sidecar)], shell=False)
    else:
        open_path(sidecar)
    return sidecar


def recycle_library_media(arguments):
    if not arguments:
        raise MediaRemovalError('Usage: rm|del <library-index|indexed-path>')
    target = MEDIA_REMOVAL.resolve(' '.join(arguments))
    permission = input(f'Move "{target.path}" to the operating-system trash? (y/n): ').casefold().strip()
    if permission not in {'y', 'yes'}:
        IPrint('Media removal cancelled', visible=visible)
        return None
    removed = MEDIA_REMOVAL.remove(target)
    reload_sounds(quick_load=True)
    IPrint(f'Moved to trash: {removed.path}', visible=visible)
    return removed


HELP_GROUPS = (
    ('Playback', 'ls, <number>, .rand, pause, stop, next, prev, seek, progress, now, autonext'),
    ('Queue', 'queue list/tree/group/order, playlist list/create/show/play/queue/import/export'),
    ('Online', '/ys, /yl, station, album search/play/queue, radio, podcast, rss, download-ya'),
    ('Library', 'library status/scan/info, find, rfind, lfind, reload, rename short'),
    ('Details', 'media info/probe/fingerprint/identify, lyrics, replaygain status'),
    ('App', 'theme, discord presence, tools status/setup, sleep, history, cls, exit'),
)


def help_command(arguments):
    """Display a deliberately short command map; detailed docs remain one command away."""
    topic = arguments[0].casefold() if arguments else None
    rows = HELP_GROUPS
    if topic and topic not in {'all', 'full'}:
        rows = tuple(row for row in HELP_GROUPS if row[0].casefold().startswith(topic))
        if not rows:
            raise ValueError(f'Unknown help topic: {topic}')
    IPrint(tbl(rows, headers=('Commands', 'Common forms'), tablefmt='plain'), visible=visible)
    IPrint("Use 'help <group>' to narrow this list; README.md documents every command family.", visible=visible)
    return rows


def autoplay_command(arguments):
    global AUTOPLAY_ENABLED
    operation = arguments[0].casefold() if arguments else 'status'
    if operation == 'status':
        IPrint(f'Auto-next: {"on" if AUTOPLAY_ENABLED else "off"} (queue/library order)', visible=visible)
        return AUTOPLAY_ENABLED
    if operation not in {'on', 'off'} or len(arguments) != 1:
        raise ValueError('Usage: autoplay|autonext [on|off|status]')
    previous = AUTOPLAY_ENABLED
    AUTOPLAY_ENABLED = operation == 'on'
    playback_settings = SETTINGS.setdefault('playback', {})
    playback_settings['autoplay'] = AUTOPLAY_ENABLED
    try:
        save_user_settings(SETTINGS, RUNTIME_PATHS.settings)
    except Exception:
        AUTOPLAY_ENABLED = previous
        playback_settings['autoplay'] = previous
        raise
    if not AUTOPLAY_ENABLED:
        vas.controller.clear_prefetch()
    IPrint(f'Auto-next {operation}', visible=visible)
    return AUTOPLAY_ENABLED


def discord_command(arguments):
    if not arguments or arguments[0].casefold() != 'presence':
        raise ValueError('Usage: discord presence off|app|track|session|status|refresh')
    operation = arguments[1].casefold() if len(arguments) == 2 else None
    if operation is None or len(arguments) != 2:
        raise ValueError('Usage: discord presence off|app|track|session|status|refresh')
    if operation == 'status':
        status = DISCORD_PRESENCE.status()
        detail = f'; {status.failure_code.value}: {status.message}' if status.failure_code else ''
        IPrint(
            f'Discord presence: mode={PRESENCE.mode.value}; local RPC={status.state.value}{detail}',
            visible=visible,
        )
        return status
    if operation == 'refresh':
        if PRESENCE.mode == PresencePrivacyMode.OFF:
            IPrint('Discord presence is off; choose app, track, or session first.', visible=visible)
            return DISCORD_PRESENCE.status()
        PRESENCE.start()
        PRESENCE.refresh()
        IPrint('Discord Rich Presence refresh requested.', visible=visible)
        return DISCORD_PRESENCE.status()
    try:
        selected = PresencePrivacyMode(operation)
    except ValueError as error:
        raise ValueError('Usage: discord presence off|app|track|session|status|refresh') from error

    presence_settings = SETTINGS.setdefault('integrations', {}).setdefault('discord', {}).setdefault('presence', {})
    previous = presence_settings.get('mode', 'off')
    presence_settings['mode'] = selected.value
    try:
        save_user_settings(SETTINGS, RUNTIME_PATHS.settings)
    except Exception:
        presence_settings['mode'] = previous
        raise
    if selected != PresencePrivacyMode.OFF:
        PRESENCE.start()
    PRESENCE.set_mode(selected)
    IPrint(f'Discord presence mode set to {selected.value}.', visible=visible)
    return selected


THEME_PRESETS = {
    'aurora': 'Mariana Aurora',
    'windows': 'Windows Terminal Acrylic',
    'kitty': 'Kitty / Catppuccin',
    'gruvbox': 'Gruvbox Dark',
}


def theme_command(arguments):
    appearance = SETTINGS.setdefault('appearance', {})
    current = str(appearance.get('terminal theme') or 'aurora')
    operation = arguments[0].casefold() if arguments else 'current'
    if operation in {'list', 'ls'}:
        IPrint(tbl([(key, value, '*' if key == current else '') for key, value in THEME_PRESETS.items()],
                   headers=('Preset', 'Name', ''), tablefmt='plain'), visible=visible)
        return current
    if operation in {'current', 'status'}:
        IPrint(f'Theme: {current} ({THEME_PRESETS.get(current, "custom")})', visible=visible)
        return current
    if operation not in THEME_PRESETS or len(arguments) != 1:
        raise ValueError(f'Usage: theme [{"|".join(THEME_PRESETS)}|list|current]')
    previous = appearance.get('terminal theme')
    appearance['terminal theme'] = operation
    try:
        save_user_settings(SETTINGS, RUNTIME_PATHS.settings)
    except Exception:
        appearance['terminal theme'] = previous
        raise
    DESKTOP_CONTROL.emit('theme', {'name': operation})
    IPrint(f'Theme changed to {THEME_PRESETS[operation]}', visible=visible)
    return operation


def _media_info(arguments):
    snapshot = vas.controller.snapshot()
    target = ' '.join(arguments).strip()
    media = snapshot.media
    if target and target not in {'current', 'now'}:
        info = LIBRARY.info(target)
        if not info:
            raise ValueError(f'Indexed media was not found: {target}')
        media = MediaRef(
            MediaSource.LOCAL,
            info['canonical_path'],
            stable_id=info['library_id'],
            title=info['metadata'].get('title'),
            artist=info['metadata'].get('artist'),
            album=info['metadata'].get('album'),
            duration=info['metadata'].get('duration'),
            provenance='library',
        )
        return media, info
    if media is None:
        raise ValueError('No media is currently active; pass a library index or indexed path')
    if media.source == MediaSource.LOCAL:
        info = LIBRARY.info(media.original_uri)
        if info:
            return media, info
    return media, {
        'library_id': media.stable_id,
        'canonical_path': media.original_uri,
        'state': snapshot.state.value,
        'metadata': {
            'source': media.source.value,
            'title': media.title,
            'artist': media.artist,
            'album': media.album,
            'duration': media.duration or snapshot.duration,
            'provenance': media.provenance,
            'stream_title': snapshot.stream_title,
        },
    }


def media_command(arguments):
    operation = arguments[0].casefold() if arguments else 'info'
    target_arguments = [value for value in arguments[1:] if value != '--full']
    media, info = _media_info(target_arguments)
    if operation in {'info', 'probe', 'metadata'}:
        rows = flattened_details(info)
        if media.source == MediaSource.LOCAL and Path(media.original_uri).is_file():
            stat = Path(media.original_uri).stat()
            rows.extend((('Filesystem created/changed', time.ctime(stat.st_ctime)),
                         ('Filesystem modified', time.ctime(stat.st_mtime))))
        IPrint(tbl(rows, tablefmt='plain'), visible=visible)
        return info
    if operation == 'fingerprint':
        fingerprint = info.get('fingerprint')
        if not fingerprint:
            IPrint(
                "No saved Chromaprint fingerprint is available yet. Run 'library scan changed'; "
                "the profiler will calculate it when fpcalc is installed.",
                visible=visible,
            )
            return None
        value = str(fingerprint) if '--full' in arguments else f'{len(str(fingerprint))} characters'
        IPrint(f'Chromaprint ({info.get("fingerprint_duration") or "unknown"} s): {value}', visible=visible)
        return fingerprint
    if operation == 'identify':
        if info.get('fingerprint'):
            identity = IDENTITY.identify_fingerprint(
                media,
                float(info.get('fingerprint_duration') or media.duration or 0),
                str(info['fingerprint']),
            )
        else:
            identity = IDENTITY.identify(media, pcm=vas.controller.fingerprint_pcm())
        rows = [(key.replace('_', ' ').title(), value) for key, value in identity.to_dict().items()
                if value not in (None, '', [], {})]
        IPrint(tbl(rows, tablefmt='plain'), visible=visible)
        if identity.status != IdentityStatus.IDENTIFIED:
            IPrint('No confident identity was guessed; the reported status is intentional.', visible=visible)
        return identity
    raise ValueError('Usage: media [info|probe|metadata|fingerprint|identify] [current|index|path] [--full]')


def rename_command(arguments):
    global currentsong
    if not arguments or arguments[0].casefold() != 'short':
        raise ValueError('Usage: rename short [current|library-index|indexed-path] [--dry-run|--yes]')
    flags = {value for value in arguments[1:] if value.startswith('--')}
    target = ' '.join(value for value in arguments[1:] if not value.startswith('--')) or 'current'
    media, info = _media_info([target])
    if media.source != MediaSource.LOCAL or info.get('state') != 'available':
        raise ValueError('Only an available, indexed local media file can be renamed')
    source = Path(info['canonical_path'])
    filename = short_filename(source, info.get('metadata') or {})
    destination = source.with_name(filename)
    IPrint(f'Rename preview:\n  {source.name}\n  -> {destination.name}', visible=visible)
    if '--dry-run' in flags:
        return destination
    if '--yes' not in flags:
        permission = input('Apply this rename? (y/n): ').casefold().strip()
        if permission not in {'y', 'yes'}:
            IPrint('Rename cancelled', visible=visible)
            return None
    snapshot = vas.controller.snapshot()
    if snapshot.media and snapshot.media.stable_id == media.stable_id:
        stopsong()
    renamed = LIBRARY.rename(info['library_id'], filename)
    if currentsong and os.path.normcase(os.path.abspath(str(currentsong))).casefold() == os.path.normcase(
        os.path.abspath(str(source))
    ).casefold():
        currentsong = str(renamed)
    reload_sounds(quick_load=True)
    IPrint(f'Renamed: {renamed}', visible=visible)
    return renamed

def get_current_progress():
    return vas.player.get_time() / 1000

def save_user_data():
    global USER_DATA

    total_plays = [j for i, j in
                   USER_DATA['default_user_data']['stats']['play_count'].items()
                   if i in ['local', 'radio', 'general', 'youtube', 'redditsession']]
    total_plays = sum(total_plays)
    USER_DATA['default_user_data']['stats']['play_count']['total'] = total_plays

    write_user_data_atomic(RUNTIME_PATHS.user_data, USER_DATA)

def save_song_data():
    global currentsong_length, currentsong

    SONG_DATA = []
    with open('data/song_data.json', 'w', encoding="utf-8") as s_data_file:
        json.dump(SONG_DATA, s_data_file)

def exitplayer(sys_exit=False):
    global EXIT_INFO, APP_BOOT_START_TIME, USER_DATA, currentsong, isplaying

    IPrint(colored.fg('red')+'Exiting...'+colored.attr('reset'), visible=visible)
    DESKTOP_CONTROL.emit('shutdown-ack')
    snapshot = vas.controller.snapshot()
    if snapshot.media:
        RECOMMENDER.record_event(
            snapshot.media,
            'played_duration',
            reward=0,
            context={'position': snapshot.position, 'duration': snapshot.duration},
        )

    # These services are independent at shutdown. Closing them concurrently keeps
    # one slow network encoder, watcher, or device driver from serially delaying exit.
    closures = (
        ('sleep timer', SLEEP_TIMER.close),
        ('discord presence', PRESENCE.close),
        ('station', STATION.close),
        ('downloads', DOWNLOADS.close),
        ('broadcast', BROADCASTER.close),
        ('desktop control', DESKTOP_CONTROL.close),
        ('playback', vas.supervisor.close),
        ('library profiler', LIBRARY_SERVICE.close),
    )
    threads = []
    failures = []

    def close_component(name, callback):
        try:
            callback()
        except Exception as error:
            failures.append((name, error))

    for name, callback in closures:
        worker = threading.Thread(
            target=close_component,
            args=(name, callback),
            name=f'mariana-shutdown-{name.replace(" ", "-")}',
            daemon=True,
        )
        worker.start()
        threads.append((name, worker))
    deadline = time.monotonic() + 6
    for name, worker in threads:
        worker.join(max(0, deadline - time.monotonic()))
        if worker.is_alive():
            failures.append((name, TimeoutError('shutdown exceeded six-second global deadline')))

    for name, error in failures:
        SAY(
            visible=visible,
            display_message=f'[WARNING] {name} did not close cleanly; process cleanup will finish on exit.',
            log_message=f'{name} shutdown failure: {error}',
            log_priority=2,
        )
    currentsong = None
    isplaying = False
    purge_old_lyrics_if_exist()
    APP_CLOSE_TIME = time.time()

    time_spent_on_app = APP_CLOSE_TIME - APP_BOOT_END_TIME
    app_boot_time = APP_BOOT_END_TIME - APP_BOOT_START_TIME

    SAY(visible=visible,
        display_message = '',
        log_message = f'Time spent to boot app = {app_boot_time}',
        log_priority = 3)

    SAY(visible=visible,
        display_message = '',
        log_message = f'Time spent using app = {time_spent_on_app}',
        log_priority = 3)

    USER_DATA['default_user_data']['stats']['times_spent'].append(time_spent_on_app)
    save_user_data()

    if sys_exit:
        sys.exit(f"{EXIT_INFO}")

# def loadsettings():
#     global settings
#     with open('', encoding='utf-8') as settingsfile:
#         settings = yaml.load(settingsfile)

def _queued_local_item(songpath):
    """Return a queued local occurrence using case-insensitive canonical paths."""
    path = songpath[0] if isinstance(songpath, list) else songpath
    canonical = os.path.normcase(os.path.abspath(path)).casefold()
    return next(
        (
            (index, item)
            for index, item in enumerate(QUEUE.items())
            if item.media.source == MediaSource.LOCAL
            and os.path.normcase(os.path.abspath(item.media.original_uri)).casefold() == canonical
        ),
        (None, None),
    )


def _library_song_index(songpath):
    """Return the one-based library position for a path, or ``N/A``."""
    path = songpath[0] if isinstance(songpath, list) else songpath
    canonical = os.path.normcase(os.path.abspath(path)).casefold()
    return next(
        (
            index
            for index, candidate in enumerate(_sound_files, start=1)
            if os.path.normcase(os.path.abspath(candidate)).casefold() == canonical
        ),
        'N/A',
    )


def _navigate_active_queue(command, offset):
    """Preview or play a queue-relative item when queue and playback agree."""
    current = QUEUE.current()
    snapshot = vas.controller.snapshot()
    if current is None or snapshot.media is None or current.media.stable_id != snapshot.media.stable_id:
        return False
    items = QUEUE.items()
    try:
        current_position = next(index for index, item in enumerate(items) if item.queue_id == current.queue_id)
    except StopIteration:
        return False
    state = QUEUE.state()
    if state.get('repeat_mode') == 'one':
        target_position = current_position
    else:
        target_position = current_position + offset
        if state.get('repeat_mode') == 'all' and items:
            target_position %= len(items)
    if target_position not in range(len(items)):
        direction = 'forward' if offset > 0 else 'backward'
        SAY(
            visible=visible,
            display_message=f'Cannot skip {direction}; the queue boundary has been reached',
            log_message=f'Reached queue boundary while skipping {direction}',
            log_priority=2,
        )
        return True
    target = items[target_position]
    if command.startswith('.'):
        _play_queue_item(QUEUE.jump(target_position))
        return True
    library_index = _library_song_index(target.media.original_uri)
    position_label = library_index if library_index != 'N/A' else f'queue {target_position + 1}'
    title = target.media.title or Path(target.media.original_uri).stem or target.media.original_uri
    IPrint(
        f'@{command[0]} {colored.fg("light_red")}{position_label}'
        f'{colored.fg("aquamarine_3")} | {title}{colored.attr("reset")}',
        visible=visible,
    )
    return True


def play_local_default_player(songpath, _songindex, is_queue=False, media=None):
    global isplaying, currentsong, currentsong_length, songindex
    global USER_DATA, current_media_type, SONG_CHANGED

    try:
        queue_position, queue_item = _queued_local_item(songpath)
        if media is None and queue_item is not None:
            media = queue_item.media
        if not is_queue and queue_position is not None:
            QUEUE.jump(queue_position)
        vas.set_media(_type='local', localpath=songpath)
        if media is not None:
            # Preserve the library/queue stable ID through decoder completion.
            vas.current_media = media
        vas.media_player(action='play')
        vas.player.audio_set_volume(int(cached_volume*100))

        isplaying = True
        currentsong = songpath[0] if isinstance(songpath, list) else songpath
        songindex = _library_song_index(currentsong)

        if _songindex:
            IPrint(colored.fg('dark_olive_green_2') + \
                  f':: {_sound_files_names_only[int(_songindex)-1]}' + \
                  colored.attr('reset'), visible=visible)

            recents_queue_save((songindex, currentsong))

        else:
            if is_queue:
                IPrint(colored.fg('dark_olive_green_2') + '::queue' + \
                       colored.attr('reset'), visible=visible)

            else:
                IPrint(colored.fg('dark_olive_green_2') + \
                    f':: {os.path.splitext(os.path.split(songpath)[1])[0]}' + \
                    colored.attr('reset'), visible=visible)
                recents_queue_save(currentsong)


        current_media_type = None
        USER_DATA['default_user_data']['stats']['play_count']['local'] += 1
        save_user_data()

        vas.wait_until_playing(max_wait_limit_to_get_song_length)

        # TODO - Save all audio info in `data` dir
        # save_song_data()

        IPrint(f"{colored.fg('grey_50')}Attempting to calculate audio length{colored.fg('grey_50')}", visible=visible)
        length_find_start_time = time.time()
        while True:
            if vas.player.get_length():
                currentsong_length = vas.player.get_length()/1000
                break
            if time.time() - length_find_start_time >= max_wait_limit_to_get_song_length:
                currentsong_length = -1
                break

        if currentsong_length == -1:
            SAY(visible=visible,
                log_message = "Cannot get length for vas media",
                display_message = "",
                log_priority=3)
        isplaying = True

        if not currentsong_length and currentsong_length != -1:
            get_currentsong_length()

        # Save current audio to log/history.log in human readable form
        SAY(visible=visible,
            display_message = '',
            out_file=RUNTIME_PATHS.logs / 'history.log',
            log_message = currentsong,
            log_priority = 3,
            format_style = 0)

        if not is_queue and queue_item is not None:
            _prefetch_after(queue_item)

    except Exception:
        #raise
        SAY(visible=visible,
            display_message=f"Failed to play \"{songpath}\"",
            log_message=f"Failed to play audio: \"{songpath}\"",
            log_priority=2,)


def voltransition(
    initial=cached_volume,
    final=cached_volume,
    disablecaching=False,  # NOT_USED: Enable volume caching by default
    transition_time=0.2,
    show_progress = False,
    # transition_time=1,
):
    global cached_volume, visible

    if not ismuted:
        for i in range(101):
            diffvolume = initial*100+(final-initial)*i
            time.sleep(transition_time/100)

            if show_progress and visible:
                print(f'{colored.fg("orange_1")}    -> {i}%', end='\r')
                print(colored.attr('reset'), end = '\r')
            vas.player.audio_set_volume(int(diffvolume))

        # if not disablecaching:
        #     cached_volume = final


def vol_trans_process_spawn():
    # This operation is synchronous by design. Multiprocessing would relaunch the
    # frozen Mariana executable on Windows, producing a nested player session.
    voltransition(initial=cached_volume, final=0, disablecaching=True)

# https://stackoverflow.com/a/3463582/17685480
def remove_adjacent(seq): # works on any sequence, not just on numbers
    i = 1
    n = len(seq)
    while i < n: # avoid calling len(seq) each time around
        if seq[i] == seq[i-1]:
            del seq[i]
            # value returned by seq.pop(i) is ignored; slower than del seq[i]
            n -= 1
        else:
            i += 1

    #### return seq #### don't do this
    # function acts in situ; should follow convention and return None

def playpausetoggle(softtoggle=True, use_multi=False, transition_time=0.2, show_progress=False): # Soft pause by default
    global isplaying, currentsong, cached_volume

    try:
        if currentsong:
            if isplaying:
                # with concurrent.futures.ProcessPoolExecutor() as executor:
                if use_multi:
                    vol_trans_process_spawn()
                else:
                    voltransition(initial=cached_volume,
                                  final=0,
                                  transition_time=transition_time*(softtoggle),
                                  disablecaching=True,
                                  show_progress=show_progress)
                # executor.submit(voltransition,
                #                 initial=cached_volume,
                #                 transition_time=transition_time*(softtoggle),
                #                 final=0,
                #                 disablecaching=True)

                vas.media_player(action='pausetoggle')

                if visible: print(' '*12, end='\r')
                IPrint("|| Paused", visible=visible)
                isplaying = False

            else:
                vas.media_player(action='pausetoggle')

                # with concurrent.futures.ProcessPoolExecutor() as executor:
                vas.player.audio_set_volume(0)

                if use_multi:
                    vol_trans_process_spawn()
                else:
                    voltransition(initial=0,
                                  final=cached_volume,
                                  transition_time=transition_time*(softtoggle),
                                  disablecaching=True,
                                  show_progress=show_progress)
                # executor.submit(voltransition, initial=0, final=cached_volume)
                if visible: print(' '*12, end='\r')
                IPrint("|> Resumed", visible=visible)
                isplaying = True
        else:
            isplaying = False
            SAY(
                visible=visible,
                log_priority=3,
                display_message="Nothing to pause/unpause",
                log_message="Nothing to pause/unpause",
            )

    except Exception:
        # raise
        SAY(
            visible=visible,
            log_priority=2,
            display_message=f"Failed to toggle play/pause for \"{currentsong}\"",
            log_message=f"Failed to toggle play pause for audio: \"{currentsong}\"",
        )


def stopsong():
    global isplaying, currentsong
    try:
        snapshot = vas.controller.snapshot()
        if snapshot.media:
            RECOMMENDER.record_event(
                snapshot.media,
                'played_duration',
                reward=0,
                context={'position': snapshot.position, 'duration': snapshot.duration},
            )
        vas.media_player(action='stop')
        RECOMMENDER.retrain_if_due()

        currentsong = None
        isplaying = False
        purge_old_lyrics_if_exist()
    except Exception:
        IPrint(f'Failed to stop: {currentsong}', visible=visible)

def searchsongs(queryitems):
    global _sound_files_names_enumerated

    out = []
    for index, audio in _sound_files_names_enumerated:
        flag = True
        for queryitem in list(OrderedSet(queryitems)):
            if queryitem.lower() not in audio.lower():
                flag = False

        if flag:
            out.append((index, audio))

    return out


# TODO - Implement librosa bpm + online bpm API features
# def get_bpm(filename, duration=50, enable_round=True):
#     y, sr = librosa.load(filename, duration=duration)
#     tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
#     if enable_round:
#         return round(tempo)
#     else:
#         return tempo

def fade_in_out(initvol=None, finalvol=None, fade_type=0, fade_duration=5):
    """
    To fade out, use fade_type = 1
    To fade in, use fade_type = 0
    """

    global cached_volume, isplaying, ismuted

    if initvol is None: initvol = cached_volume

    if ismuted:
        SAY(visible=visible,
            display_message='Cannot fade audio in or out when muted',
            log_message='Cannot fade audio in or out when muted',
            log_priority=3)

    if finalvol is not None: # Complex fade has been command issued,
                             # execute it

        if finalvol != 0: # Music is paused, resume and then fade in to v > 0
            # Resume music
            if not isplaying:
                IPrint("|> Resumed", visible=visible)
                vas.media_player(action='pausetoggle')
                isplaying = True

        voltransition(initial=initvol,
                      final=finalvol,
                      transition_time=fade_duration,
                      disablecaching=True,
                      show_progress=True)

        if finalvol != 0: cached_volume = finalvol
        if visible: print(' '*12, end='\r')

        if finalvol == 0:
            if isplaying:
                vas.media_player(action='pausetoggle')
                IPrint("|> Paused", visible=visible)
                isplaying = False

    elif fade_type == 0 and isplaying:
        SAY(visible=visible,
            display_message='Cannot fade in, audio already playing. Try pausing',
            log_message='Cannot fade in, audio already playing. Try pausing',
            log_priority=3)
    elif fade_type == 0 or isplaying:
        playpausetoggle(softtoggle = True, transition_time=fade_duration, show_progress=True)

    else:
        SAY(visible=visible,
            display_message='Cannot fade out, no audio playing',
            log_message='Cannot fade out, no audio playing',
            log_priority=3)

def enqueue(songindices):
    IPrint("Enqueueing", visible=visible)
    global song_paths_to_enqueue

    song_paths_to_enqueue = []

    for songindex in songindices:
        if int(songindex)-1 in range(len(_sound_files)):
            song_paths_to_enqueue.append(_sound_files[int(songindex)-1])
        else:
            IPrint(f"Skipping index: {int(songindex)-1}", visible=visible)

    if song_paths_to_enqueue:
        song_paths_to_enqueue = list(OrderedSet(song_paths_to_enqueue))
        for songpath in song_paths_to_enqueue:
            try:
                IPrint(f"Queued {song_paths_to_enqueue.index(songpath)+1}", visible=visible)
            except Exception:
                SAY(visible=visible,
                    display_message = "Queueing error",
                    log_message = "Could not enqueue one or more files",
                    log_priority = 2)
                raise

        play_local_default_player(song_paths_to_enqueue, _songindex=None, is_queue=True)

    else:
        IPrint("No songs to queue", visible=visible)


def purge_old_lyrics_if_exist():
    lyrics_file_paths = [LYRICS_TEXT_PATH, LYRICS_HTML_PATH]

    for lyrics_file_path in lyrics_file_paths:
        try:
            if os.path.isfile(lyrics_file_path):
                os.remove(lyrics_file_path)
        except Exception:
            raise

def local_play_commands(commandslist, _command=False):
    global cached_volume, currentsong_length, lyrics_saved_for_song
    # Output volume is controlled by the shared PCM stream.

    purge_old_lyrics_if_exist()
    lyrics_saved_for_song = None

    if not _command:
        if len(commandslist) == 2:
            songindex = commandslist[1]
            if songindex.isnumeric():
                if int(songindex) in range(1, len(_sound_files)+1):
                    currentsong_length = None
                    play_local_default_player(songpath = _sound_files[int(songindex)-1],
                                              _songindex = songindex)
                else:
                    if any(_sound_files):
                        SAY(visible=visible,
                            log_message='Out of bound audio index',
                            display_message=f'Song number {songindex} does not exist. Please input audio number between 1 and {len(_sound_files)}',
                            log_priority=3)

                    else:
                        SAY(visible=visible,
                            log_message='User attempted to play local audio, even though there are no audios in library',
                            display_message='There are no audios in library',
                            log_priority=2)

        else:
            # TODO - Implement full queue functionality
            # as per `future ideas{...}.md`
            # Not yet implemented
            # This is just a sekeleton code for future

            songindices = commandslist[1:]
            _ = []
            for songindex in songindices:
                try:
                    if songindex.isnumeric():
                        _.append(songindex)
                except Exception:
                    pass

            songindices = _
            del _

            enqueue(songindices)
    else:
        currentsong_length = None
        play_local_default_player(songpath=_command[1:], _songindex=None)

def timeinput_to_timeobj(rawtime):
    try:
        if ':' in rawtime.strip():
            processed_rawtime = rawtime.split(':')
            processed_rawtime = [int(i) if i else 0 for i in processed_rawtime]

            # print(processed_rawtime)

            # timeobj: A list of the format [WHOLE HOURS IN SECONDS, WHOLE MINUTES in SECONDS, REMAINING SECONDS]
            timeobj = [value * 60 ** (len(processed_rawtime) - _index - 1)
                       for _index, value in enumerate(processed_rawtime)]

            totaltime = sum(timeobj)

            formattedtime = ' '.join([''.join(map(lambda x: str(x), i)) for i in list(
                zip(processed_rawtime, ['h', 'm', 's'][3-len(processed_rawtime):]))])

            if totaltime > currentsong_length:
                return ValueError
            else:
                return (formattedtime, totaltime)

        elif rawtime.strip() == '-0':
            return ('0', 0)

        elif rawtime.isnumeric():
            if int(rawtime) > currentsong_length:
                return ValueError
            processed_rawtime = list(
                map(lambda x: int(x), convert(int(rawtime)).split(':')))
            formattedtime = ' '.join([''.join(map(lambda x: str(x), i)) for i in list(
                zip(processed_rawtime, ['h', 'm', 's'][3-len(processed_rawtime):]))])
            # print (None, rawtime)
            return (formattedtime, rawtime)

    except Exception:
        # print (None, None)
        return (None, None)

def get_currentsong_length():
    global currentsong_length
    if currentsong:
        if not currentsong_length and currentsong_length != -1:
            length_ms = vas.player.get_length()
            currentsong_length = length_ms / 1000 if length_ms else -1

    return currentsong_length

def song_seek(timeval=None, rel_val=None):
    global currentsong

    if timeval is not None:
        try:
            vas.player.set_time(int(timeval)*1000)
            media = vas.controller.snapshot().media
            if media:
                RECOMMENDER.record_event(media, 'seek', context={'target': int(timeval)})
            return True
        except Exception:
            return None
            # raise # TODO - remove all "raise"d exceptions?

    elif not rel_val:
        SAY(visible=visible, display_message="Error: Can't seek in this audio",
            log_message=f'Unsupported codec for seeking audio: {currentsong}', log_priority=2)
        return None


def setmastervolume(value=None):
    global cached_volume

    if comtypes_load_error:
        SAY(visible=visible,
            log_message="comtypes functionality used even when not available",
            display_message="This functionality is unavailable",
            log_priority=3)
    else:
        if value is None:
            value = cached_volume

        if value in range(101):
            set_master_volume(value)
        else:
            SAY(visible=visible, display_message='ERROR: Could not set master volume',
                log_message='Could not set master volume', log_priority=2)

def convert(seconds):
    seconds = seconds % (24 * 3600)
    hour = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60

    return f"{hour:0>2.0f}:{minutes:0>2.0f}:{seconds:0>2.0f}"

def isdecimal(value):
    try:
        float(value)
        return True
    except ValueError:
        return False


def parse_fade_arguments(arguments, current_volume):
    """Parse the extended fade command without leaving partially initialized values."""
    if not arguments or arguments[0].lower() != 'fade':
        raise ValueError('Fade command must begin with "fade"')

    tokens = arguments[1:]
    if len(tokens) in {2, 3} and all(isdecimal(value) for value in tokens):
        initial, final = (float(value) / 100 for value in tokens[:2])
        duration = float(tokens[2]) if len(tokens) == 3 else 5.0
    else:
        initial = float(current_volume)
        final = None
        duration = 5.0
        seen = set()
        position = 0
        while position < len(tokens):
            keyword = tokens[position].lower()
            if keyword not in {'from', 'to', 'in'} or keyword in seen:
                raise ValueError(f'Invalid fade command token: {tokens[position]}')
            if position + 1 >= len(tokens) or not isdecimal(tokens[position + 1]):
                raise ValueError(f'Fade {keyword} value must be numeric')
            value = float(tokens[position + 1])
            seen.add(keyword)
            if keyword == 'from':
                initial = value / 100
            elif keyword == 'to':
                final = value / 100
            else:
                duration = value
            position += 2

        if final is None:
            if 'from' in seen:
                final = float(current_volume)
            else:
                raise ValueError('Fade command requires a final volume')

    if not 0 <= initial <= 1 or not 0 <= final <= 1:
        raise ValueError('Fade volume must be between 0 and 100')
    if duration < 0:
        raise ValueError('Fade duration must not be negative')
    return initial, final, duration

def rand_song_index_generate():
    global _sound_files_names_only
    if len(_sound_files) == 0:
        SAY(visible=visible,
        log_message='User attempted to play local audio, even though there are no audios in library',
        display_message='There are no audios in library',
        log_priority=2)
        return None
    else:
        return rand.randint(0, len(_sound_files_names_only)-1)


def validate_time(rawtime):
    rawtime = rawtime.replace(':', '')
    try:
        _ = float(rawtime)
    except Exception:
        return 2
    if '.' in rawtime:
        return 1
    elif float(rawtime) < 0:
        return 3
    else:
        return 0


# `media_url` is the only mandatory param in `play_vas_media`
def play_vas_media(media_url, single_video = None, media_name = None,
                   print_now_playing = True, media_type = 'video',
                   show_link_chosen_msg = False):

    global isplaying, visible, currentsong, cached_volume
    global currentsong_length, current_media_type

    # Stop prev audios b4 loading VAS Media...
    stopsong()

    # VAS Media Load/Set
    if media_type == 'video':
        YT_aud_url = vas.set_media(_type='yt_video', vidurl=media_url)
        current_media_type = 0

        if not media_name:
            try:
                vid_info = YT_query.vid_info(media_url)
                media_name = vid_info['title']
            except Exception:
                media_name = '[VIDEO NAME COULD NOT BE RESOLVED]'
                SAY(visible=visible,
                    display_message = '',
                    log_message = f'video name could not be resolved for:: {media_url}',
                    log_priority = 2)

        currentsong = (media_name, media_url, YT_aud_url)
        recents_queue_save(currentsong)

        if print_now_playing and visible:
            if single_video:
                IPrint(f"Playing YouTube search result:: {colored.fg('plum_1')}{media_name}{colored.attr('reset')}", visible=visible)
            else:
                IPrint(f"Chosen YouTube video:: {colored.fg('plum_1')}{media_name}{colored.attr('reset')}", visible=visible)
            IPrint(f"{colored.fg('light_red')}@ {colored.fg('orange_1')}{media_url}{colored.attr('reset')}", visible=visible)

    elif media_type == 'general':
        vas.set_media(_type='audio', audurl=media_url)

        current_media_type = 1
        currentsong = media_url
        recents_queue_save(currentsong)
        IPrint(f"Chosen custom media url:: {text_overflow_prettify(media_url)}", visible=visible*show_link_chosen_msg)

    elif media_type == 'radio':
        # Here `media_name` is actually the radio name
        vas.set_media(_type=f'radio/{media_name}') # No need for an explicit `audurl` here... (as per definition of vas.set_media)

        current_media_type = 2
        currentsong = media_name
        recents_queue_save(currentsong)
        IPrint(f"Chosen radio: {colored.fg('light_goldenrod_1')}{currentsong}{colored.attr('reset')}", visible=visible)

    elif media_type == 'redditsession':
        vas.set_media(_type='audio', audurl=media_url)

        current_media_type = 3
        currentsong = (media_name, media_url)
        recents_queue_save(currentsong)

    else:
        SAY(visible=visible, display_message = "Invalid media type provided", log_message = "Invalid media type provided", log_priority = 2)
        return False

    if media_type == 'video': media_type = 'youtube'
    if media_type:

        # VAS Media Play
        vas.media_player(action='play')
        vas.player.audio_set_volume(int(cached_volume*100))

        # TODO - Save all audio info in `data` dir
        # save_song_data()

        # Save current audio to log/history.log in human readable form
        SAY(visible=visible,
            display_message = '',
            out_file=RUNTIME_PATHS.logs / 'history.log',
            log_message = [' \u2014 '.join(currentsong[:-1]) if isinstance(currentsong, tuple) else currentsong][0],
            log_priority = 3,
            format_style = 0)

    currentsong_length = None

    USER_DATA['default_user_data']['stats']['play_count'][media_type] += 1
    save_user_data()

    vas.wait_until_playing(max_wait_limit_to_get_song_length)

    if current_media_type == 2:
        currentsong_length = -1
    else:
        IPrint(f"{colored.fg('grey_50')}Attempting to calculate audio length{colored.fg('grey_50')}", visible=visible)
        length_find_start_time = time.time()
        while True:
            if vas.player.get_length():
                currentsong_length = vas.player.get_length()/1000
                break
            if time.time() - length_find_start_time >= max_wait_limit_to_get_song_length:
                currentsong_length = -1
                break
    # currentsong_length gives output in ms, this will be converted to seconds when needed

    if currentsong_length == -1:
        SAY(visible=visible,
            log_message = "Cannot get length for vas media",
            display_message = "",
            log_priority=3)
    isplaying = True


def choose_media_url(media_url_choices: list, yt: bool = True):
    global isplaying, currentsong

    if yt:
        if len(media_url_choices) == 1:
            media_name, media_url = media_url_choices[0]
            play_vas_media(media_name=media_name, media_url=media_url, single_video=True)

        else:
            chosen_index = input(f"{colored.fg('deep_pink_4c')}Choose video number between 1 and {len(media_url_choices)}" \
                                 f" (leave blank to skip): {colored.fg('navajo_white_1')}").strip()
            print(colored.attr('reset'), end='')

            if chosen_index:
                try:
                    chosen_index = int(chosen_index)
                except Exception:
                    if visible:
                        print("ERROR: Invalid choice, choose again: ", end='\r')

                if chosen_index in range(1, len(media_url_choices)+1):
                    _, media_name, media_url = media_url_choices[chosen_index-1]
                    play_vas_media(media_name=media_name, media_url=media_url,
                                   single_video=False)
                elif visible:
                    print("ERROR: Invalid choice, choose again: ", end='\r')

                if visible: IPrint('\n', visible=visible)

def refresh_settings():
    global SYSTEM_SETTINGS, SETTINGS, visible, supported_file_types, enforce_os_requirement
    global max_yt_search_results_threshold, max_wait_limit_to_get_song_length
    global FALLBACK_RESULT_COUNT, DEFAULT_EDITOR, MAX_RECENTS_SIZE, MAX_RESULT_COUNT, loglevel

    SYSTEM_SETTINGS = load_system_settings()
    SETTINGS = load_user_settings()
    enforce_os_requirement = SYSTEM_SETTINGS['system_settings']['enforce_os_requirement']

    # Supported file extensions
    # Progress is based on emitted PCM frames for every supported format.
    supported_file_types = SYSTEM_SETTINGS["system_settings"]['supported_file_types']
    max_wait_limit_to_get_song_length = SYSTEM_SETTINGS['system_settings']['max_wait_limit_to_get_song_length']
    MAX_RECENTS_SIZE = SYSTEM_SETTINGS["system_settings"]['max_recents_size']

    visible = SETTINGS['visible']
    loglevel = SETTINGS.get('loglevel')
    DEFAULT_EDITOR = SETTINGS.get('editor path')
    FALLBACK_RESULT_COUNT = SETTINGS['display items count']['general']['fallback']
    MAX_RESULT_COUNT = SETTINGS['display items count']['general']['maximum']
    max_yt_search_results_threshold = SETTINGS['display items count']['youtube-search results']['maximum']
    browser_profile = SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile')
    YT_query.configure(browser_profile=browser_profile)
    vas.set_youtube_browser_profile(browser_profile)
    presence_value = SETTINGS.get('integrations', {}).get('discord', {}).get('presence', {}).get('mode', 'off')
    try:
        presence_mode = PresencePrivacyMode(presence_value)
    except ValueError:
        presence_mode = PresencePrivacyMode.OFF
    if presence_mode != PresencePrivacyMode.OFF:
        PRESENCE.start()
    PRESENCE.set_mode(presence_mode)

    if not loglevel:
        restore_default.restore('loglevel', SETTINGS)
        loglevel = SETTINGS.get('loglevel')

def text_overflow_prettify(text, length_thresh=100, end_length = 8, as_tuple=False):
    if length_thresh == 100:
        if as_tuple:
            final = (text[:92], text[-5:]) if len(text) > length_thresh else (text, None)
        else:
            final = f"{text[:92]}...{text[-5:]}" if len(text) > length_thresh else text
        return final
    elif length_thresh >= 14:
        if as_tuple:
            final = (text[:length_thresh-(end_length+3)], text[-end_length:]) if len(text) > length_thresh else (text, None)
        else:
            final = f"{text[:length_thresh-(end_length+3)]}...{text[-end_length:]}" if len(text) > length_thresh else text
        return final
    else:
        return


def get_prettified_recents(indices):
    global recents_QUEUE

    results = [] # prettified results (formatted as WYSIWYG)

    # results = [RECENTS_QUEUE[::-1][index] for index in indices]
    for index in indices:
        result= RECENTS_QUEUE[::-1][index]
        yt_play_type, media_player, inf = result

        if media_player == -1:
            cur_song = inf[1]
            cur_song = os.path.splitext(os.path.split(cur_song)[1])[0]
            result = f":: {colored.fg('plum_1')}{inf[0]}{colored.attr('reset')} | {cur_song}"

        elif media_player == 0:
            yt_prefix = ["@yl", "@ys"][yt_play_type]
            result = (f"{colored.fg('red')}{yt_prefix}: {colored.fg('aquamarine_3')}Title | {inf[0]}\n"
                      f"     {colored.fg('navajo_white_1')}Link  | {inf[1]}{colored.attr('reset')}")

        elif media_player == 1:
            result = f"{colored.fg('hot_pink_1a')}@media-link: {colored.fg('aquamarine_3')}{text_overflow_prettify(inf)}{colored.attr('reset')}"

        elif media_player == 2:
            result = f"{colored.fg('light_slate_blue')}@webradio/{colored.fg('navajo_white_1')}{inf}{colored.attr('reset')}"

        elif media_player == 3:
            result = (f"{colored.fg('orange_1')}@rs: {colored.fg('aquamarine_3')}Session | {text_overflow_prettify(inf[0])}{colored.attr('reset')}\n"
                      f"     {colored.fg('navajo_white_1')}Link    | {text_overflow_prettify(inf[1])}{colored.attr('reset')}")

        results.append(result)

    return results

def lyrics_ops(show_window):
    global lyrics_saved_for_song, currentsong, ISDEV
    global visible

    refresh_lyrics = not (lyrics_saved_for_song == currentsong) # Song has changed since last save of lyrics,
                                                                # need to refresh the lyrics to match the current audio
    get_related = SETTINGS['get related songs']

    if current_media_type == 0:
        IPrint('Loading lyrics window for YT stream (Time taking)...', visible=visible)
        get_lyrics.show_window(refresh_lyrics = refresh_lyrics,
                                max_wait_lim = max_wait_limit_to_get_song_length,
                                get_related=get_related,
                                show_window=show_window,
                                weblink=currentsong[1],
                                visible=visible,
                                isYT=1)
    elif current_media_type == 1:
        IPrint('Loading lyrics window for online media stream (Time taking)...', visible=visible)
        get_lyrics.show_window(refresh_lyrics = refresh_lyrics,
                                max_wait_lim = max_wait_limit_to_get_song_length,
                                get_related=get_related,
                                show_window=show_window,
                                visible=visible,
                                weblink=currentsong)
    elif current_media_type == 2:
        IPrint('Lyrics for webradio are not supported', visible=visible)
    elif current_media_type == 3:
        IPrint('Lyrics for reddit sessions are not supported', visible=visible)


    if current_media_type is not None:
        lyrics_saved_for_song = currentsong

    # elif ISDEV: # Song hasn't changes, no need to refresh lyrics
    #             # Just re-display the existing one
    #     print('Lyrics have already been loaded')

    if current_media_type is None:
        get_related = SETTINGS['get related songs']
        if get_related and lyrics_saved_for_song == currentsong: # True only if the audio has changed.
                                                                 # If it has, we need to get the related audios ONLY IF it is enabled in settings
                                                                 # If it's still the same audio, no need to get related audios again
            get_related = False

        refresh_lyrics = get_related

        if currentsong:
            if os.path.isfile(currentsong):
                if show_window:
                    IPrint(lyrics_window_note, visible=visible)
                get_lyrics.show_window(refresh_lyrics = refresh_lyrics,
                                       max_wait_lim = max_wait_limit_to_get_song_length,
                                       get_related = get_related,
                                       show_window = show_window,
                                       visible=visible,
                                       songfile = currentsong)
                lyrics_saved_for_song = currentsong

def display_and_choose_podbean(latest_podbeans, commandslist, result_count, is_rss=False):

    podtype = ['podbean', 'rss'][is_rss]

    latest_podbeans_table = []
    for pod in latest_podbeans[:result_count]:
        table_items_1 = [text_overflow_prettify(pod[key].strip('.'), length_thresh=60) if pod.get(key) else None for key in ['title', 'caption'] ]
        table_items_2 = [pod[key] if pod.get(key) else None for key in ['pub_date', 'is_explicit']]
        table_items = table_items_1+table_items_2
        latest_podbeans_table.append(table_items)

    if commandslist[0].startswith('.'):
        podbean_index = str(result_count)
    else:
        IPrint(tbl([(i+1, *j) for i, j in enumerate(latest_podbeans_table)],
                    # missingval=f'{colored.fg("red")}( N/A ){colored.attr("reset")}',
                    missingval='( N/A )',
                    headers=('#', ['pod', 'title'][is_rss], 'caption', 'published on', 'is explicit'),
                    tablefmt='pretty',
                    colalign=('center','left',)),
                    visible=visible)
        IPrint('', visible=visible)
        podbean_index = input(f"{colored.fg('light_slate_blue')}Enter {podtype} session number to tune into: {colored.fg('navajo_white_1')}")
        print(colored.attr('reset'), end='')


    if podbean_index.isnumeric():
        podbean_index = int(podbean_index)-1
        if podbean_index in range(len(latest_podbeans_table)):
            IPrint(f"Attempting to play {podtype}: {colored.fg('green_1')}{latest_podbeans[podbean_index]['title']}{colored.attr('reset')}", visible=visible)
            if latest_podbeans[podbean_index].get('url'):
                if caption := latest_podbeans[podbean_index].get('caption'):
                    if visible:
                        caption_shortened_1, caption_shortened_2 = text_overflow_prettify(caption, length_thresh=200, end_length=16, as_tuple=True)
                        caption_shortened_formatted = f"{colored.fg('hot_pink_1a')}{caption_shortened_1}"\
                                                      f"{colored.fg('aquamarine_1b')}..."\
                                                      f"{colored.fg('hot_pink_1a')}{caption_shortened_2}"\
                                                      f"{colored.attr('reset')}"

                        print(caption_shortened_formatted) # This will only print if `visible` == True

                play_vas_media(media_url = latest_podbeans[podbean_index]['url'],
                               media_type='general',
                               show_link_chosen_msg=False)

    elif podbean_index.strip() == '':
        SAY(visible=visible,
            display_message=f'No {podtype} session number entered, skipping',
            log_message=f'{podtype.title()} session index left empty, skipped',
            log_priority=3)

    else:
        SAY(visible=visible,
            display_message=f'You have entered an invalid {podtype} session number',
            log_message=f'Invalid {podtype} session number entered',
            log_priority=2)

def process(command):
    global _sound_files_names_only, visible, currentsong, isplaying, ismuted, cached_volume
    global current_media_type, DEFAULT_EDITOR, YOUTUBE_PLAY_TYPE, lyrics_saved_for_song

    command = normalize_command(command)
    try:
        commandslist = split_command(command.strip())
    except CommandSyntaxError as error:
        SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)
        return None

    try:
        if vas.controller.snapshot().state == PlaybackState.IDLE and isplaying:
            currentsong = None
            isplaying = False
    except Exception:
        pass

    if commandslist:
        routed = {
            'h': help_command,
            'help': help_command,
            '?': help_command,
            'autoplay': autoplay_command,
            'autonext': autoplay_command,
            'discord': discord_command,
            'theme': theme_command,
            'media': media_command,
            'metadata': lambda values: media_command(['metadata', *values]),
            'rename': rename_command,
            'station': station_command,
            'download-ya': download_audio_command,
        }
        if handler := routed.get(commandslist[0].casefold()):
            try:
                handler(commandslist[1:])
                return None
            except (
                AlbumError,
                DownloadJobError,
                LibraryError,
                StationError,
                StationSeedError,
                YouTubeError,
                ValueError,
                OSError,
            ) as error:
                SAY(
                    visible=visible,
                    display_message=str(error),
                    log_message=f'{commandslist[0]} command failed: {error}',
                    log_priority=2,
                )
                return None

    if commandslist != []:  # Atleast 1 word

        # Quitting the player
        if commandslist in [['exit'], ['quit']]:
            perm = input(colored.fg('light_red')+'Do you want to exit? [Y]es, [N]o (default = N): '+colored.fg('magenta_3c'))
            print(colored.attr('reset'), end = '')
            if perm.strip().lower() == 'y':
                return False

        # Quitting the player w/o conf
        elif commandslist in [['exit', 'y'], ['quit', 'y']]:
            return False

        if commandslist in (['all'], ['all*']):
            rescount = MAX_RESULT_COUNT
            results_enum = enumerate(
                _sound_files_names_only if commandslist == ['all*'] else _sound_files_names_only[:rescount]
            )
            IPrint(tbl([(i+1, j) for i, j in results_enum], tablefmt='plain'), visible=visible)

        # TODO: Need to display files in n columns (Mostly 3 cols) depending upon terminal size (dynamically...)
        if commandslist[0] in ['list', 'ls']:

            if len(_sound_files) != 0:
                # TODO: Get values for `order_results` and `order_type` from SETTINGS
                indices = [] # Indices of audios to be displayed
                rescount = FALLBACK_RESULT_COUNT
                order_results = False
                order_type = 1 # Default value (1): Display in ascending order

                if 'o' in commandslist[1:]:
                    order_results = True
                if 'desc' in commandslist[1:]:
                    order_type = 0

                range_command_is_valid = True
                if '-' in command:

                    _command = command.replace('o', '').replace('desc', '')
                    _command = _command.strip().lstrip(commandslist[0]).split('-')

                    if len(_command) == 2:
                        try:
                            ls_x_to_y = list(map(lambda i:int(i.strip()), _command))
                            ls_x_to_y[0] -= 1
                            if ls_x_to_y[0] < ls_x_to_y[1]:
                                indices = list(range(*ls_x_to_y))
                            else:
                                SAY(visible=visible,
                                    display_message = 'Range order is reversed. It should be lower to upper',
                                    log_message = 'Invalid order of bounds for listing range of audios',
                                    log_priority = 2)
                                range_command_is_valid = False
                        except Exception:
                            SAY(visible=visible,
                                display_message = 'Invalid bounds for listing range of audios',
                                log_message = 'Invalid bounds for listing range of audios',
                                log_priority = 2)
                            range_command_is_valid = False
                    else:
                        SAY(visible=visible,
                            display_message = 'Invalid command for listing a range of audios',
                            log_message = 'Invalid command for listing a range of audios',
                            log_priority = 2)
                        range_command_is_valid = False
                else:
                    _commandslist = commandslist.copy()

                    if 'o' in commandslist: _commandslist.remove('o')
                    if 'desc' in commandslist: _commandslist.remove('desc')
                    if len([i for i in commandslist if i.isnumeric()]) == 1:
                        if commandslist[1].isnumeric():
                            rescount = int(commandslist[1])
                    else:
                        for i in commandslist[1:]:
                            if i.isnumeric():
                                if int(i)-1 not in indices:
                                    indices.append(int(i)-1)


                if indices:
                    results = [_sound_files_names_only[index] for index in indices]
                    results_enum = list(zip(indices, results))
                    if order_results:
                        results_enum = sorted(results_enum, key = lambda x: x[0], reverse = not order_type)

                if len([i for i in commandslist if i.isnumeric()]) == 0 and '-' not in command and len(commandslist) != 1:
                    # List files matching provided regex pattern
                    # Need to implement a check to validate the provided regex pattern
                    print(f'Regex search is still in progress... The developer {colored.fg("magenta_3a")}@{SYSTEM_SETTINGS["about"]["author"]}{colored.attr("reset")} will add this feature shortly...')
                    # regex_pattern
                    # regexp = re.compile(regex_pattern)

                else:
                    if len([i for i in commandslist if i.isnumeric()]) in [0, 1] and '-' not in command:
                        results_enum = list(enumerate(_sound_files_names_only[:rescount]))
                        if order_results:
                            results_enum = sorted(results_enum, key = lambda x: x[0], reverse = not order_type)

                    if indices or len([i for i in commandslist if i.isnumeric()]) in [0, 1]:
                        if range_command_is_valid:
                            IPrint(tbl([(i+1, j) for i, j in results_enum], tablefmt='plain'), visible=visible)


            else:
                SAY(visible=visible,
                    log_message='User attempted to play local audio, even though there are no audios in library',
                    display_message='There are no audios in library',
                    log_priority=2)

        elif commandslist[0] == '/open':
            if current_media_type is None:
                if len(commandslist) == 1: # To open current audio
                    if currentsong:
                        try:
                            open_in_youtube(currentsong)
                        except OSError:
                            SAY(visible=visible,
                                display_message="Video Load Error: Could not load video... (Maybe check your VPN?)", say=False)
                    else:
                        SAY(visible=visible,
                            display_message = 'No audio playing currently, try using "/open" with a audio number or path instead',
                            log_message = 'User issued "/open" as an isolated command even when no audio is currently playing',
                            log_priority = 2)

                elif len(commandslist) == 2: # To open custom audio
                    if commandslist[1].isnumeric(): # To open custom audio by index
                        song_index = int(commandslist[1])-1
                        songfile = _sound_files[song_index]
                        open_in_youtube(songfile)
                    else:
                        if os.path.isfile(commandslist[1]): # To open custom audio by absolute filepaths
                            songfile = commandslist[1]
                            open_in_youtube(songfile)
                        else:
                            SAY(visible=visible,
                                display_message = 'File path provided for "/open" is inexistent or invalid',
                                log_message = 'File path provided for "/open" is inexistent or invalid',
                                log_priority = 2)

            else:
                SAY(visible=visible,
                    display_message = '"/open" can only be used for local streaming, try "open" intead',
                    log_message = '"/open" cannot be used for online streaming, only local',
                    log_priority = 2)

        elif commandslist == ['last']:
            last_index, last_name = _sound_files_names_enumerated[-1]
            IPrint(f">| {last_index} | {last_name}", visible=visible)

        elif commandslist[0] in ['/rss', '/rss-link']:
            if len(commandslist) == 2:
                rss_link = commandslist[1]
                if url_is_valid(rss_link):
                    IPrint(f"Attempting to play {colored.fg('green_1')}rss link{colored.attr('reset')}", visible=visible)
                    latest_podbeans = get_latest_podbean_data(rss_link=rss_link)
                    display_and_choose_podbean(latest_podbeans=latest_podbeans,
                                               commandslist=commandslist,
                                               result_count=FALLBACK_RESULT_COUNT,
                                               is_rss=True)
                else:
                    SAY(visible=visible,
                        display_message = 'Invalid rss url provided',
                        log_message = 'Url for RSS media invalid',
                        log_priority = 2)
            else:
                SAY(visible=visible,
                    display_message = 'Invalid rss command provided. Must have exactly 1 argument, i.e. rss link',
                    log_message = 'Invalid rss command provided',
                    log_priority = 2)

        # Misspelled podbean commands
        elif commandslist[0] in ['pod', 'podbean', '.pods', '.podbeans']:
            warn_msg = None
            if commandslist[0].startswith('.'):
                warn_msg=f'/? Invalid command {commandslist[0]}, perhaps you meant "{commandslist[0][:-1]}"'
            else:
                if len(commandslist) in [2, 3]:
                    if commandslist[1] == 'vendors':
                        result_count=FALLBACK_RESULT_COUNT
                        if len(commandslist) == 3:
                            if commandslist[2] == 'all': result_count=None
                            if commandslist[2].isnumeric(): result_count=int(commandslist[2])
                        if result_count and len(pod_vendors) > result_count:
                            IPrint("{0}Showing the first {1} vendors (you may change this 'fallback' result count in settings){2}".format(colored.fg('orange_1'), result_count, colored.attr('reset')), visible=visible)
                        for pod_vendor in list(pod_vendors.keys())[:result_count]: print(f"  {colored.fg('aquamarine_3')}--> {colored.attr('reset')}{pod_vendor}")
                    else:
                        warn_msg=f'/? Invalid command {commandslist[0]}, perhaps you meant "{commandslist[0]}s"'
                else:
                    warn_msg=f'/? Invalid command {commandslist[0]}, perhaps you meant "{commandslist[0]}s"'

            if warn_msg:
                SAY(visible=visible,
                    display_message=warn_msg,
                    log_message="podbean command assumed to be misspelled",
                    log_priority=3)

        # Podbean music: default vendor => 1001tracklists
        # '1001tracklists'

        elif commandslist[0] in ['pods', 'podbeans', '.pod', '.podbean']:
            result_count = FALLBACK_RESULT_COUNT
            podbean_vendor = '1001tracklists'

            if len(commandslist) in [2, 3]: # Either pod[bean]s <count> or
                                            # pod[bean]s <count> <vendor>
                podbean_command_numbers_at = [i for i,j in enumerate(commandslist) if j.isnumeric()]

                if len(podbean_command_numbers_at) == 0:
                    podbean_vendor = commandslist[1]
                elif len(podbean_command_numbers_at) == 1:
                    result_count = int(commandslist[podbean_command_numbers_at[0]])
                    if len(commandslist) == 3:
                        podbean_vendor = commandslist[3-podbean_command_numbers_at[0]]
                else:
                    SAY(visible=visible,
                        display_message = 'Too many numbers provided, try using only 1',
                        log_message = 'Too many numbers provided for pod family of command',
                        log_priority = 2)

            IPrint(f"{['Show', 'Play'][commandslist[0][0] == '.']}ing from {colored.fg('green_1')}{podbean_vendor}{colored.attr('reset')}", visible=visible)
            latest_podbeans = get_latest_podbean_data(vendor=podbean_vendor)

            if latest_podbeans is not None:
                display_and_choose_podbean(latest_podbeans=latest_podbeans,
                                           commandslist=commandslist,
                                           result_count=result_count,
                                           is_rss=False)
            elif podbean_vendor in ['vendor', 'vendors']: # No podcasts found for provided vendor
                SAY(visible=visible,
                    display_message = 'Podbean vendor unknown. List vendors with "pod[bean] vendors"',
                    log_message = 'Unknown pod vendor mentioned',
                    log_priority = 2)

        if commandslist in [['recent', 'count'], ['recents', 'count']]:
            IPrint(f"Recents count: {len(RECENTS_QUEUE)}", visible=visible)

        elif commandslist[0] in ['recent', 'recents']:
            # TODO: Get values for `order_results` and `order_type` from SETTINGS
            indices = [] # Indices of audios to be displayed
            rescount = FALLBACK_RESULT_COUNT
            order_results = False
            order_type = 1 # Default value (1): Display in ascending order

            if 'o' in commandslist[1:]:
                order_results = True
            if 'desc' in commandslist[1:]:
                order_type = 0

            range_command_is_valid = True
            if '-' in command:

                _command = command.replace('o', '').replace('desc', '')
                _command = _command.strip().lstrip(commandslist[0]).split('-')

                if len(_command) == 2:
                    try:
                        recents_x_to_y = list(map(lambda i:int(i.strip()), _command))
                        recents_x_to_y[0] -= 1
                        if recents_x_to_y[0] < recents_x_to_y[1]:
                            indices = list(range(*recents_x_to_y))
                        else:
                            SAY(visible=visible,
                                display_message = 'Range order is reversed. It should be lower to upper',
                                log_message = 'Invalid order of bounds for listing range of recents',
                                log_priority = 2)
                            range_command_is_valid = False
                    except Exception:
                        SAY(visible=visible,
                            display_message = 'Invalid bounds for listing recents range',
                            log_message = 'Invalid bounds for listing range of recents',
                            log_priority = 2)
                        range_command_is_valid = False
                else:
                    SAY(visible=visible,
                        display_message = 'Invalid command for listing recents range',
                        log_message = 'Invalid command for listing a range of recents',
                        log_priority = 2)
                    range_command_is_valid = False
            else:
                _commandslist = commandslist.copy()

                if 'o' in commandslist: _commandslist.remove('o')
                if 'desc' in commandslist: _commandslist.remove('desc')
                if len([i for i in commandslist if i.isnumeric()]) == 1:
                    if commandslist[1].isnumeric():
                        rescount = int(commandslist[1])
                else:
                    for i in commandslist[1:]:
                        if i.isnumeric():
                            if int(i)-1 not in indices:
                                indices.append(int(i)-1)


            if indices:
                results = get_prettified_recents(indices)
                results_enum = list(zip(indices, results))

                if order_results:
                    results_enum = sorted(results_enum, key = lambda x: x[0], reverse = not order_type)

            if len([i for i in commandslist if i.isnumeric()]) == 0 and '-' not in command and len(commandslist) != 1:
                # List files matching provided regex pattern
                # Need to implement a check to validate the provided regex pattern
                print(f'Regex search is still in progress... The developer {colored.fg("magenta_3a")}@{SYSTEM_SETTINGS["about"]["author"]}{colored.attr("reset")} will add this feature shortly...')
                # regex_pattern
                # regexp = re.compile(regex_pattern)

            else:
                if len([i for i in commandslist if i.isnumeric()]) in [0, 1] and '-' not in command:
                    if rescount > len(RECENTS_QUEUE):
                        rescount = len(RECENTS_QUEUE)
                    results = get_prettified_recents(list(range(rescount)))
                    results_enum = list(enumerate(results))
                    if order_results:
                        results_enum = sorted(results_enum, key = lambda x: x[0], reverse = not order_type)

                if indices or len([i for i in commandslist if i.isnumeric()]) in [0, 1]:
                    if range_command_is_valid:
                        IPrint(tbl([(-(i+1), j) for i, j in results_enum], tablefmt='plain'), visible=visible)

        elif commandslist == ['last', 'played']:
            if RECENTS_QUEUE:
                if currentsong and len(RECENTS_QUEUE) >= 2:
                    IPrint(get_prettified_recents([1])[0], visible=visible)
                else:
                    IPrint(get_prettified_recents([0])[0], visible=visible)
            else:
                SAY(visible=visible,
                    display_message='No recents recorded yet for the current session',
                    log_message='No recents to display',
                    log_priority=2)

        elif commandslist[0] in {'hist', 'history'}:
            if commandslist[1:] == ['count']:
                try:
                    count = sum(bool(line.strip()) for line in (RUNTIME_PATHS.logs / 'history.log').read_text(
                        encoding='utf-8'
                    ).splitlines())
                    IPrint(f'History count: {count}', visible=visible)
                except OSError as error:
                    SAY(visible=visible, display_message=f'Error reading history: {error}', log_message=str(error), log_priority=2)
            elif len(commandslist) == 1:
                reveal_path(RUNTIME_PATHS.logs / 'history.log')
            else:
                SAY(visible=visible, display_message='Usage: history [count]', log_message='Invalid history command', log_priority=2)

        elif commandslist[0] in {'include', 'exclude'}:
            if len(commandslist) == 2 and commandslist[1] in {'download', 'downloads', 'dl', 'dls'}:
                set_download_library_inclusion(commandslist[0] == 'include')
            else:
                SAY(visible=visible, display_message='Usage: include|exclude downloads', log_message='Invalid download library command', log_priority=2)

        elif commandslist[0] == 'reload':
            option = ''.join(commandslist[1:]).replace('-', '')
            include_options = {'includedl', 'includedls', 'includedownload', 'includedownloads'}
            exclude_options = {'excludedl', 'excludedls', 'excludedownload', 'excludedownloads'}
            if option in include_options | exclude_options:
                set_download_library_inclusion(option in include_options)
            elif option:
                SAY(visible=visible, display_message='Invalid reload option', log_message='Invalid reload option', log_priority=2)
                return None
            IPrint("Reloading sounds", visible=visible)
            reload_sounds(quick_load = False)

            IPrint(f"Loaded {len(_sound_files)}", visible=visible)
            IPrint('Done', visible=visible)

        elif commandslist in [['refresh'], ['refresh', 'all']]:
            if commandslist == ['refresh', 'all']:
                confirm_refresh = input("Confirm refresh all? (This will refresh data of your library files) (y/n): ").lower().strip()
                while confirm_refresh not in ['y', 'n', 'yes', 'no']:
                    confirm_refresh = input("[INVALID RESPONSE] Do you wish to confirm refresh? (y/n): ").lower().strip()

                if confirm_refresh in ['yes', 'y']:
                    IPrint("Reloading settings (1/4)", visible=visible)
                    refresh_settings()

                    IPrint("Refreshing lyrics  (2/4)", visible=visible)
                    purge_old_lyrics_if_exist()
                    lyrics_saved_for_song = False
                    lyrics_ops(show_window=False)

                    IPrint("Reloading sounds   (3/4)", visible=visible)
                    reload_sounds(quick_load = False, full = True)
                    IPrint(f"  > Loaded {len(_sound_files)} sounds", visible=visible)

                    IPrint("Library profiling jobs queued (4/4)", visible=visible)

                    IPrint("Done", visible=visible)

            else:
                IPrint("Reloading settings (1/3)", visible=visible)
                refresh_settings()

                IPrint("Refreshing lyrics  (2/3)", visible=visible)
                purge_old_lyrics_if_exist()
                lyrics_saved_for_song = False
                lyrics_ops(show_window=False)

                IPrint("Reloading sounds   (3/3)", visible=visible)
                reload_sounds(quick_load = False)
                IPrint(f"  > Loaded {len(_sound_files)} sounds", visible=visible)

                IPrint("Done", visible=visible)

        elif commandslist in [['refresh', 'lyrics'], ['refresh', 'lyr']]:
            IPrint("Refreshing lyrics...", visible=visible)
            purge_old_lyrics_if_exist()
            lyrics_saved_for_song = False
            lyrics_ops(show_window=False)

            IPrint("Done", visible=visible)

        elif commandslist == ['vis']:
            visible = not visible
            IPrint('visibility on', visible=visible)

        elif commandslist[0] in ['prev', 'next', '.prev', '.next']:
            if current_media_type is None: # default player currently active
                offset = None
                if songindex not in ['N/A', -1]:
                    if len(commandslist) == 1: # default to 1 audio skip
                        offset = 1
                    elif len(commandslist) > 1:
                        if commandslist[1].isnumeric():
                            if int(commandslist[1]) != 0:
                                # number of audios to be skipped is provided by the user
                                # store offset as either +ve for fwd skip (next)
                                # or                     -ve for bwd seeks (prev)
                                offset = int(commandslist[1])
                            else:
                                SAY(visible=visible,
                                    display_message = 'Provided 0 audios to skip. Not allowed',
                                    log_message = 'Number of audios to skip was 0',
                                    log_priority = 2)
                        else:
                            SAY(visible=visible,
                                display_message = 'Number of audios to skip must be a positives integer',
                                log_message = 'Number of audios to skip wasn not a valid +ve int',
                                log_priority = 2)

                    if offset:
                        if commandslist[0] in ['prev', '.prev']: offset *= -1
                        if _navigate_active_queue(commandslist[0], offset):
                            return None
                        offsetted_index = songindex + offset
                        if offsetted_index in range(1, len(_sound_files)+1): # is audio found at offsetted index?
                            if commandslist[0][0] == '.':
                                local_play_commands(commandslist=[None, str(offsetted_index)])
                            else:
                                IPrint(f"@{commandslist[0][0]} {colored.fg('light_red')}{offsetted_index}{colored.fg('aquamarine_3')} | {_sound_files_names_only[offsetted_index-1]}{colored.attr('reset')}", visible=visible)
                        else:
                            if offset > 0:
                                if offsetted_index == 1:
                                    offset_err_disp_msg = 'Cannot skip backward as you have reached beginning of library'
                                    offset_err_log_msg = 'Reached beginning of library, cannot skip bwd'
                                else:
                                    offset_err_disp_msg = f'Number of audios to skip forward was too large, try "next" command with <= {len(_sound_files)-songindex} skips'
                                    offset_err_log_msg = 'Reached upper bound of index in library when skipping fwd'
                            else:
                                if offsetted_index == len(_sound_files_names_only):
                                    offset_err_disp_msg = 'Cannot skip forward as you have reached end of library'
                                    offset_err_log_msg = 'Reached end of library, cannot skip fwd'
                                else:
                                    offset_err_disp_msg = f'Number of audios to skip backward was too large, try "prev" command with <= {songindex} skips'
                                    offset_err_log_msg = 'Reached index 0 in library when skipping bwd'

                            SAY(visible=visible,
                                display_message = offset_err_disp_msg,
                                log_message = offset_err_log_msg,
                                log_priority = 2)
                else:
                    if songindex == -1:
                        SAY(visible=visible,
                            display_message = 'Cannot skip. No audio is currently playing',
                            log_message = 'Cannot skip when no audio is playing',
                            log_priority = 2)
                    if songindex == 'N/A':
                        SAY(visible=visible,
                            display_message = 'Cannot skip audios when playing individual audio files outside of your music library',
                            log_message = 'Cannot skip when playing explicit filepaths outside library',
                            log_priority = 2)

        elif commandslist == ['now']:
            if currentsong:
                if current_media_type is not None: # Online media
                    if current_media_type == 0:
                        if YOUTUBE_PLAY_TYPE == 0:
                            IPrint(f"@yl: {currentsong[0]}", visible=visible)
                        elif YOUTUBE_PLAY_TYPE == 1:
                            IPrint(f"@ys: {currentsong[0]}", visible=visible)
                    elif current_media_type == 1:
                        IPrint(f"@ml: {currentsong}", visible=visible)
                    elif current_media_type == 2:
                        IPrint(f"@wra: {currentsong}", visible=visible)
                    elif current_media_type == 3:
                        IPrint(f"@rs: {currentsong[0]}", visible=visible)
                else: # Local media
                    cur_song = os.path.splitext(os.path.split(currentsong)[1])[0]
                    IPrint(f":: {colored.fg('plum_1')}{songindex}{colored.fg('deep_pink_4c')} | {colored.fg('navajo_white_1')}{cur_song}{colored.attr('reset')}", visible=visible)
            else:
                # currentsong = None
                IPrint(f"{colored.fg('red')}({colored.fg('aquamarine_1b')}Not Playing{colored.fg('red')}){colored.attr('reset')}", visible=visible)
            chapter = vas.controller.snapshot().current_chapter
            if chapter:
                IPrint(
                    f'Chapter: {chapter.title} ({_prompt_time(chapter.start_time)}-{_prompt_time(chapter.end_time)})',
                    visible=visible,
                )

        elif commandslist == ['now*']:
            if currentsong:
                if current_media_type is not None: # Online media
                    if current_media_type == 0:
                        if YOUTUBE_PLAY_TYPE == 0:
                            IPrint(f"{colored.fg('red')}@youtube-link: {colored.fg('aquamarine_3')}Title | {currentsong[0]}", visible=visible)
                            IPrint(f"               {colored.fg('navajo_white_1')}Link  | {currentsong[1]}{colored.attr('reset')}", visible=visible)
                        elif YOUTUBE_PLAY_TYPE == 1:
                            IPrint(f"{colored.fg('red')}@youtube-search: {colored.fg('aquamarine_3')}Title | {currentsong[0]}", visible=visible)
                            IPrint(f"                 {colored.fg('navajo_white_1')}Link  | {currentsong[1]}{colored.attr('reset')}", visible=visible)
                    elif current_media_type == 1:
                        IPrint(f"{colored.fg('hot_pink_1a')}@media-link: {colored.fg('aquamarine_3')}{currentsong}{colored.attr('reset')}", visible=visible)
                    elif current_media_type == 2:
                        IPrint(f"{colored.fg('light_slate_blue')}@webradio/{colored.fg('navajo_white_1')}{currentsong}{colored.attr('reset')}", visible=visible)
                    elif current_media_type == 3:
                        IPrint(f"{colored.fg('orange_1')}@redditsession: {colored.fg('aquamarine_3')}Session | {currentsong[0]}{colored.attr('reset')}", visible=visible)
                        IPrint(f"                {colored.fg('navajo_white_1')}Link    | {currentsong[1]}{colored.attr('reset')}", visible=visible)

                else: # Local media
                    IPrint(f":: {colored.fg('plum_1')}{songindex}{colored.attr('reset')} | {currentsong}", visible=visible)

            else:
                # currentsong = None
                IPrint(f"{colored.fg('red')}({colored.fg('aquamarine_1b')}Not Playing{colored.fg('red')}){colored.attr('reset')}", visible=visible)

        elif commandslist[0].lower() == 'play':
            local_play_commands(commandslist=commandslist)

        if len(commandslist) == 2:
            if commandslist[1] == 'device':
                device_kind = None
                if commandslist[0] in ['output', 'input']:
                    device_kind = commandslist[0]
                elif commandslist[0] in ['out', 'in']:
                    device_kind = commandslist[0]+'put'

                if device_kind:
                    if device_kind == 'output':
                        try:
                            selected = vas.controller.default_output_device()
                            active = vas.controller.active_output_device
                            detail = f' via {selected.route}'
                            if active and active.key != selected.key:
                                detail += f'; switching from {active.name}'
                            IPrint(
                                f"{colored.fg('navajo_white_1')}output device: "
                                f"{colored.attr('reset')}{selected.name}{detail}; auto-follow: on",
                                visible=visible,
                            )
                        except OutputDeviceError as error:
                            IPrint(f'Output device unavailable: {error}', visible=visible)
                    elif device_name := sounddevice.query_devices(kind = device_kind).get('name'):
                        IPrint(f"{colored.fg('navajo_white_1')}{device_kind} device: {colored.attr('reset')}{device_name}", visible=visible)

        if commandslist[:2] in [['fade', 'in'], ['fade', 'out']]:
            try:
                """
                fade in  --> fade_type = 0
                fade out --> fade_type = 1
                """

                fade_type=(['in', 'out'].index(commandslist[1]))
                if len(commandslist) == 2:
                    fade_in_out(fade_type=fade_type)

                elif len(commandslist) == 3:
                    if isdecimal(commandslist[2]):
                        fade_duration = float(commandslist[2])
                        fade_in_out(fade_type=fade_type, fade_duration=fade_duration)

                    else:
                        SAY(visible=visible,
                            display_message='Fade duration must be a valid integer',
                            log_message='Fade duration is not a valid integer',
                            log_priority=2)

                else:
                    SAY(visible=visible,
                        display_message='Invalid use of fade command. Need to specify a single integer for fade duration',
                        log_message='Invalid use of fade in/out',
                        log_priority=2)

            except Exception:
                SAY(visible=visible,
                    display_message='Failed to fade in/out',
                    log_message='Failed to fade in/out',
                    log_priority=2)

        elif commandslist[0] == 'fade':
            try:
                initvol, finalvol, fade_duration = parse_fade_arguments(commandslist, cached_volume)
                fade_in_out(
                    initvol=initvol,
                    finalvol=finalvol,
                    fade_type=isplaying,
                    fade_duration=fade_duration,
                )
            except ValueError as error:
                SAY(
                    visible=visible,
                    display_message=f'Invalid fade command: {error}',
                    log_message=f'Invalid fade command: {error}',
                    log_priority=2,
                )

        elif commandslist[0].lower() in ['m?', 'ism?', 'ismute?']:
            # TODO - Make more reliable...?
            IPrint(int(ismuted), visible=visible)

        elif commandslist[0].lower() in ['isp?', 'ispl', 'isp']:
            SAY(visible=visible,
                display_message='/? Invalid command, perhaps you meant "ispl?" for "is playing?"',
                log_message="\"ispl[aying]?\" command assumed to be misspelled",
                log_priority=3)

        elif commandslist[0].lower() in ['ispl?', 'isplaying?']:
            # TODO - Make more reliable...?
            IPrint(int(isplaying), visible=visible)

        elif commandslist[0].lower() in ['isl?', 'isloaded?']:
            # TODO - Make more reliable...?
            if current_media_type is not None:
                IPrint(vas.current_media, visible=visible)
            IPrint(int(bool(currentsong)), visible=visible)

        elif commandslist[0].lower() == 'seek':
            if currentsong_length not in (None, 0, -1):
                if len(commandslist) == 2:
                    if commandslist[1].startswith('+'):
                        rawtime = str(int(get_current_progress()) + int(commandslist[1][1:]))
                    elif commandslist[1].startswith('-'):
                        rawtime = str(int(get_current_progress()) - int(commandslist[1][1:]))
                    else:
                        rawtime = commandslist[1]

                    time_validity = validate_time(rawtime)

                    if not time_validity: # Raw time is valid
                        # Take a valid raw value for time from the user. Format is defined in the time section of help
                        timeobj = timeinput_to_timeobj(rawtime)
                        if timeobj is not ValueError:
                            if timeobj == (None, None):
                                SAY(visible=visible,
                                    display_message = 'Internal Error',
                                    log_message = 'Invalid time format: Invalid time object',
                                    log_priority = 2)
                            else:
                                _ = song_seek(timeval=timeobj[1])
                                if _:
                                    IPrint(f"Seeking to: {timeobj[0]}", visible=visible)

                        # TODO - Make following error messages more meaningful by giving them more
                        # context depending on if absolute or relative seek was called...

                        # E.g. say "reached beginning" instead of "seek val can't be -ve"
                        # When using relative seek

                        else:
                            SAY(visible=visible, display_message="Error: Seek value too large for this audio",
                                log_message=f'Seek value too large for: {currentsong}', log_priority=2)
                    elif time_validity == 1:
                        SAY(visible=visible, display_message="Error: Seek value can't have a decimal point",
                            log_message=f'Seek value floating point for: {currentsong}', log_priority=2)
                    elif time_validity == 2:
                        SAY(visible=visible, display_message="Error: Seek value must be numeric",
                            log_message=f'Seek value non numeric for: {currentsong}', log_priority=2)
                    elif time_validity == 3:
                        SAY(visible=visible, display_message="Error: Seek value can't be negative",
                            log_message=f'Seek value negative for: {currentsong}', log_priority=2)
                    else:
                        pass
            else:
                if currentsong_length == -1:
                    SAY(visible=visible,
                        display_message="Error: Can't seek audio, as audio length could not be loaded",
                        log_message="Song length could not be loaded, cannot seek",
                        log_priority=2)
                else:
                    SAY(visible=visible,
                        display_message="Error: No audio to seek",
                        log_message="Seeked audio w/o playing any",
                        log_priority=2)

        elif commandslist in [['prog'], ['progress'], ['prog*'], ['progress*']]:
            if currentsong:
                if currentsong_length:
                    cur_len = currentsong_length
                else:
                    cur_len = get_currentsong_length()

                if cur_len != -1:
                    cur_prog = get_current_progress()

                    prog_sep = f"{colored.fg('green_1')}|{colored.attr('reset')}"
                    prog_div = f"{colored.fg('navajo_white_1')}\u2014{colored.attr('reset')}"

                    if commandslist[0].endswith('*'):
                        IPrint(f"elapsed: {colored.fg('deep_pink_1a')}{convert(round(cur_prog))} {prog_div} {colored.fg('deep_pink_1a')}{convert(round(cur_len))}"
                               f" {prog_sep} {colored.attr('reset')}remaining: {colored.fg('orange_1')}{convert(round(cur_len-cur_prog))}"
                               f" {prog_sep} {colored.attr('reset')}progress: {colored.fg('light_goldenrod_1')}{round(cur_prog/cur_len*100)}%", visible=visible)
                    else:
                        # IPrint(f"{colored.fg('deep_pink_1a')}{convert(round(cur_prog))}/{convert(round(cur_len))}", visible=visible)
                        IPrint(f"{colored.fg('deep_pink_1a')}{round(cur_prog)} {prog_div} {colored.fg('deep_pink_1a')}{round(cur_len)}"
                               f" {prog_sep} {colored.fg('orange_1')}{round(cur_len-cur_prog)}"
                               f" {prog_sep} {colored.fg('light_goldenrod_1')}{round(cur_prog/cur_len*100)}%", visible=visible)

                else:
                    SAY(visible=visible,
                        display_message = "Progress cannot be displayed for audio of unknown length",
                        log_message = 'Progress undefined for audio of unknown length',
                        log_priority = 2) # Log fatal crash

        elif commandslist[0].lower().split('-', 1)[0] in DOWNLOAD_TYPOS:
            IPrint('Unknown command. Did you mean "download"?', visible=visible)

        elif commandslist[0].lower() in ['download',  'download-yt',  'download-au',  'download-a',
                                         '/download', '/download-yt', '/download-au', '/download-a']:
            SAY(visible=visible,
                display_message=f'/? Invalid command, perhaps you meant one of:\n'
                f'  {colored.fg("magenta_3a")}download-yv:{colored.fg("light_sky_blue_1")} Download YouTube video\n'
                f'  {colored.fg("magenta_3a")}download-ya:{colored.fg("light_sky_blue_1")} Download YouTube audio\n'
                f'  {colored.fg("magenta_3a")}download-ml:{colored.fg("light_sky_blue_1")} Download custom media link'
                f'{colored.attr("reset")}\n',
                log_message="\"download-('ys'|'yv'|'ml')\" command assumed to be misspelled", log_priority=3)

        # Download current/custom YouTube media (as video with audio)
        elif commandslist[0].lower() == 'download-yv':
            # TODO - Add way for user to customize download settings...
            continue_dl = False
            confirm_dl = False
            url = None

            if len(commandslist) == 1: # Download current/custom YouTube media
                if current_media_type is None:
                    SAY(visible=visible,
                        log_message='Cannot download locally available audios',
                        display_message='Whoops! Looks like you\'re trying to download a audio already present in your local storage',
                        log_priority = 3)

                else:
                    if currentsong is not None:
                        url = currentsong[1]
                        continue_dl = True
                    else:
                        url = None
                        IPrint("No audio currently playing", visible=visible)

            elif len(commandslist) == 2:
                url = commandslist[1]
                if id_if_url_is_of_yt_format(url) is not None:
                    IPrint('Attempting to download YouTube video from:\n  '
                          f'{colored.fg("sandy_brown")}@ {colored.fg("orchid_2")}{url}{colored.attr("reset")}',
                          visible=visible)
                    continue_dl = True
                else:
                    SAY(visible=visible,
                        log_message=f'Invalid YouTube URL for video download: {url}',
                        display_message=f'Invalid YouTube URL for video download: {url}',
                        log_priority = 3)

            if len(commandslist) in [1, 2] and url:
                download_parmeters = {
                    "SETTINGS": SETTINGS,
                    "SYSTEM_SETTINGS": SYSTEM_SETTINGS,
                    "media_urls": url,
                    "typ": 1,
                    "quality": None,
                    "make_separate_mariana_dl_dir": None,
                    "dry_run": False,
                }

                if continue_dl:
                    confirm_dl = input("Do you want to confirm VIDEO download? (y/n): ").lower().strip()
                    while confirm_dl not in ['y', 'n', 'yes', 'no']:
                        confirm_dl = input("[INVALID RESPONSE] Do you want to confirm VIDEO download? (y/n): ").lower().strip()

                    if confirm_dl in ['yes', 'y']:
                        confirm_dl = True
                    else:
                        confirm_dl = False

                if confirm_dl:
                    SAY(visible=visible,
                        log_message='Download confirmed and initiated',
                        display_message='YouTube video download started in this Mariana session.',
                        log_priority = 3)
                    start_youtube_download(download_parmeters)

        elif commandslist[0].lower() == 'download-ya':
            # TODO - Add way for user to customize download settings...
            continue_dl = False
            confirm_dl = False
            url = None

            if len(commandslist) == 1: # Download current/custom YouTube media
                if current_media_type is None:
                    SAY(visible=visible,
                        log_message='Cannot download locally available audios',
                        display_message='Whoops! Looks like you\'re trying to download a audio already present in your local storage',
                        log_priority = 3)

                else:
                    if currentsong is not None:
                        url = currentsong[1]
                        continue_dl = True
                    else:
                        url = None
                        IPrint("No audio currently playing", visible=visible)

            elif len(commandslist) == 2:
                url = commandslist[1]
                if id_if_url_is_of_yt_format(url) is not None:
                    IPrint('Attempting to download YouTube audio from:\n  '
                          f'{colored.fg("sandy_brown")}@ {colored.fg("orchid_2")}{url}{colored.attr("reset")}',
                          visible=visible)
                    continue_dl = True
                else:
                    SAY(visible=visible,
                        log_message=f'Invalid YouTube URL for audio download: {url}',
                        display_message=f'Invalid YouTube URL for audio download: {url}',
                        log_priority = 3)

            if len(commandslist) in [1, 2] and url:
                download_parmeters = {
                    "SETTINGS": SETTINGS,
                    "SYSTEM_SETTINGS": SYSTEM_SETTINGS,
                    "media_urls": url,
                    "typ": 0,
                    "quality": None,
                    "make_separate_mariana_dl_dir": None,
                    "dry_run": False,
                }

                if continue_dl:
                    confirm_dl = input("Do you want to confirm AUDIO download? (y/n): ").lower().strip()
                    while confirm_dl not in ['y', 'n', 'yes', 'no']:
                        confirm_dl = input("[INVALID RESPONSE] Do you want to confirm AUDIO download? (y/n): ").lower().strip()

                    if confirm_dl in ['yes', 'y']:
                        confirm_dl = True
                    else:
                        confirm_dl = False

                if confirm_dl:
                    SAY(visible=visible,
                        log_message='Download confirmed and initiated',
                        display_message='YouTube audio download started in this Mariana session.',
                        log_priority = 3)
                    start_youtube_download(download_parmeters)

        elif commandslist[0].lower() == 'download-ml':
            if len(commandslist) not in (2, 3, 4):
                IPrint('Usage: download-ml <URL> [mp3|flac|wav|m4a|opus] [output path]', visible=visible)
            else:
                media_url = commandslist[1]
                output_format = commandslist[2].lower() if len(commandslist) >= 3 else 'mp3'
                if len(commandslist) == 4:
                    destination = Path(commandslist[3]).expanduser()
                else:
                    downloads = Path(SETTINGS['download']['downloads folder']).expanduser()
                    destination = downloads / f'mariana-download-{int(time.time())}.{output_format}'
                try:
                    result = download_media(
                        media_url,
                        destination,
                        output_format=output_format,
                        ffmpeg_bin=MEDIA_TOOLS.get('ffmpeg bin'),
                    )
                    IPrint(f'Downloaded: {result}', visible=visible)
                except DownloadError as error:
                    SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif commandslist == ['t']:
            IPrint(convert(get_current_progress()), visible=visible)

        # TODO - Add interactive help commands (similar to the following for rand command)
        # with syntax ?<command-name> ...
        # elif commandslist == ['? rand']:  # Random comand help
        #     IPrint("", visible=visible)

        elif commandslist == ['.rand']:  # Play random audio
            rand_song_index = rand_song_index_generate()
            if rand_song_index is not None:
                local_play_commands(commandslist=[None, str(rand_song_index + 1)])
        elif commandslist == ['=rand']:  # Print random audio number
            rand_song_index = rand_song_index_generate()
            if rand_song_index is not None:
                IPrint(rand_song_index + 1, visible=visible)
        elif commandslist == ['rand']:  # Print random audio name
            rand_song_index = rand_song_index_generate()
            if rand_song_index is not None:
                IPrint(_sound_files_names_only[rand_song_index], visible=visible)
        elif commandslist == ['rand*']:  # Print random audio path
            rand_song_index = rand_song_index_generate()
            if rand_song_index is not None:
                IPrint(_sound_files[rand_song_index], visible=visible)
        elif commandslist == ['/rand']:  # Print random audio number+name
            rand_song_index = rand_song_index_generate()
            if rand_song_index is not None:
                IPrint(f"{rand_song_index+1}: {_sound_files_names_only[rand_song_index]}", visible=visible)

        elif commandslist == ['reset']:
            if currentsong_length and currentsong_length != -1:
                try:
                    song_seek('0')
                except Exception:
                    SAY(visible=visible, display_message="Error: Can't reset this audio",
                        log_message=f'Error in resetting: {currentsong}', log_priority=2)
            else:
                SAY(visible=visible, display_message="Error: No audio to seek",
                    log_message="Seeked audio w/o playing any", log_priority=2)

        elif commandslist[0].casefold() in SEARCH_COMMANDS:
            try:
                advanced_search_command(commandslist)
            except ValueError as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif command[0] == '.':
            try:
                # Play by index
                if len(commandslist) == 1:
                    # Get info of currently loaded audio and display pleasantly...
                    # The info params displayed depend on those specified in the settings...
                    # getstats() # TODO - Make such a function...???
                    if commandslist[0][1:].isnumeric():
                        local_play_commands(commandslist=[None, ''.join(commandslist[0][1:])])

                # Play/find by path
                elif command.startswith('. '):
                    path = ' '.join(commandslist[1:])
                    if os.path.isfile(path):
                        if os.path.splitext(path)[1] in supported_file_types:
                            IPrint(1, visible=visible)
                        else:
                            IPrint(0, visible=visible)
                    else:
                        IPrint(0, visible=visible)

                elif command.startswith('.'):
                    if os.path.isfile(command.strip()[1:]):
                        local_play_commands(commandslist=[None, command[1:]],
                                            _command=command)

            except Exception:
                raise

        elif commandslist in [['clear'], ['cls']]:
            clear_terminal()
            if visible: showbanner()

        elif commandslist == ['p']:
            playpausetoggle()

        elif commandslist == ['ph']:
            playpausetoggle(softtoggle=False)

        # TODO: Refactor to replace two `err` funcs with one
        elif commandslist[0].isnumeric():  # Check if only a number is entered
            # global _sound_files
            if len(commandslist) == 1:
                if int(commandslist[0]) > 0:
                    try:
                        song_index_entered = int(commandslist[0])
                        IPrint(colored.fg('aquamarine_3')+\
                               f'@{song_index_entered}'+\
                               colored.fg('orange_1')+\
                               ' | '+\
                               colored.fg('medium_orchid_1a')+\
                               _sound_files_names_only[(song_index_entered)-1]+\
                               colored.attr('reset'), visible=visible)
                    except IndexError:
                        SAY(visible=visible,
                            display_message = f'Please input audio number between 1 and {len(_sound_files)}',
                            log_message = 'Invalid song index provided for listing name',
                            log_priority = 2)
                else:
                    SAY(visible=visible,
                        display_message = f'Please input audio number between 1 and {len(_sound_files)}',
                        log_message = 'Invalid song index provided for listing name',
                        log_priority = 2)

        elif commandslist in [['count'], ['howmany'], ['total']]:
            IPrint(len(_sound_files_names_only), visible=visible)

        elif commandslist[0] == 'weblinks':
            IPrint(
                'The legacy Google Drive weblinks collection is retired; use radio search/list or the persistent queue.',
                visible=visible,
            )

        if commandslist[0] == 'open':
            if commandslist == ['open']:
                if currentsong and current_media_type is None:
                    if os.path.isfile(currentsong):
                        if os.path.splitext(currentsong)[1] in supported_file_types:
                            if sys.platform == 'win32':
                                currentsong=currentsong.replace('/', '\\')
                                IPrint(f"Opening currently playing audio: {currentsong}", visible=visible)
                                os.system(f'explorer /select, {currentsong}')
                            else:
                                currentsong=currentsong.replace('\\', '/')
                        else:
                            IPrint(0, visible=visible)
                    else:
                        IPrint(0, visible=visible)
                else:
                    if current_media_type is not None: # Online media
                        if current_media_type == 0:
                            webbrowser.open(f"{currentsong[1]}&t={int(get_current_progress())}s")
                        elif current_media_type == 1:
                            webbrowser.open(currentsong)
                        elif current_media_type == 2:
                            webbrowser.open(vas.radio_stream_url(currentsong))
                        elif current_media_type == 3:
                            webbrowser.open(currentsong[1])
                        else:
                            SAY(visible=visible,
                                display_message = '',
                                log_message = 'Received invalid type for current media',
                                log_priority = 2,
                                format_style = 1)
                    else:
                        SAY(visible=visible,
                            display_message = "No audio playing, no file selected to open",
                            log_message = "No audio playing, no file selected to open",
                            log_priority = 2)

            elif len(commandslist) > 1 and commandslist[1] in ['lib', 'library']:
                IPrint('Opening library file in editor', visible=visible)
                if not DEFAULT_EDITOR:
                    restore_default.restore('editor path', SETTINGS)
                    DEFAULT_EDITOR = SETTINGS.get('editor path')
                if DEFAULT_EDITOR:
                    sp.Popen([fr"{DEFAULT_EDITOR}", str(RUNTIME_PATHS.library_file)], shell=False)
                else:
                    open_path(RUNTIME_PATHS.library_file)

            elif len(commandslist) > 1 and commandslist[1] in ['lyr', 'lyrics']:
                IPrint('Opening lyrics file in editor', visible=visible)
                lyrics_ops(show_window = False)
                if not DEFAULT_EDITOR:
                    restore_default.restore('editor path', SETTINGS)
                    DEFAULT_EDITOR = SETTINGS.get('editor path')

                if LYRICS_TEXT_PATH.is_file() and DEFAULT_EDITOR:
                    sp.Popen([fr"{DEFAULT_EDITOR}", str(LYRICS_TEXT_PATH)], shell=False)
                elif LYRICS_TEXT_PATH.is_file():
                    open_path(LYRICS_TEXT_PATH)
                else:
                    SAY(visible=visible,
                        log_message = 'No lyrics available to view',
                        display_message = 'No lyrics available to view',
                        log_priority = 2)

            elif commandslist[1:] in (['hist'], ['history']):
                history_path = RUNTIME_PATHS.logs / 'history.log'
                if DEFAULT_EDITOR:
                    sp.Popen([DEFAULT_EDITOR, str(history_path)], shell=False)
                else:
                    open_path(history_path)

            else:
                if len(commandslist) == 2 and commandslist[1].isnumeric():
                    user_entered_song_index = int(commandslist[1])-1
                    if user_entered_song_index in range(len(_sound_files_names_only)):
                        path = _sound_files[user_entered_song_index]
                        if sys.platform == 'win32': path=path.replace('/', '\\')
                        else: path=path.replace('\\', '/')
                        IPrint(f"Opening audio at index {user_entered_song_index+1}: {_sound_files_names_only[user_entered_song_index]}", visible=visible)
                        reveal_path(_sound_files[user_entered_song_index])
                else:
                    path = ' '.join(commandslist[1:])
                    if os.path.isfile(path):
                        if os.path.splitext(path)[1] in supported_file_types:
                            if sys.platform == 'win32': path=path.replace('/', '\\')
                            else: path=path.replace('\\', '/')
                            IPrint(f"Opening audio via path at: {path}", visible=visible)
                            reveal_path(path)
                        else:
                            SAY(visible=visible,
                                display_message = 'File type is unsupported, file existence cannot be guaranteed. (Will always be shown as 0)',
                                log_message = 'Existence of file of unsupported type cannot be guaranteed, will show as 0',
                                log_priority = 2)
                            IPrint(0, visible=visible)
                    else:
                        IPrint(0, visible=visible)

        elif commandslist in [['sm'], ['sync'], ['sync', 'media']]:
            IPrint("Syncing current media...", visible=visible)
            if current_media_type == 0: # If YT vid is playing...
                IPrint('YouTube audio cannot be synced, only seeked', visible=visible)
            elif current_media_type == 1: # If audio is playing...
                IPrint('media url cannot be synced, only seeked', visible=visible)
            elif current_media_type == 2: # If radio is playing...
                vas.media_player(action='resync') # Resync radio to live stream
            elif current_media_type == 3: # If reddit-session is streaming...
                # TODO - Find a way to get the current stream timestamp of current RPAN session
                print(f'Reddit session sync: The developer {colored.fg("magenta_3a")}@{SYSTEM_SETTINGS["about"]["author"]}{colored.attr("reset")} will add this feature shortly...')

        elif commandslist[0] == 'path':
            if len(commandslist) == 1:
                if currentsong and current_media_type is None:
                    IPrint(f":: {colored.fg('plum_1')}{currentsong}{colored.attr('reset')}", visible=visible)
                else:
                    IPrint(f"{colored.fg('red')}({colored.fg('aquamarine_1b')}Not Playing{colored.fg('red')}){colored.attr('reset')}", visible=visible)

            elif len(commandslist) == 2:
                if not commandslist[1].isnumeric():
                    SAY(visible=visible,
                        display_message='Audio number must be a positive integer',
                        log_message='Invalid non-numeric audio number provided for path lookup',
                        log_priority=2)
                elif int(commandslist[1]) > 0:
                    try:
                        IPrint(_sound_files[int(commandslist[1])-1], visible=visible)
                    except IndexError:
                        SAY(visible=visible,
                            display_message = f'Please input audio number between 1 and {len(_sound_files)}',
                            log_message = 'Invalid song index provided for listing name',
                            log_priority = 2)
                else:
                    SAY(visible=visible,
                        display_message = f'Please input audio number between 1 and {len(_sound_files)}',
                        log_message = 'Invalid song index provided for listing name',
                        log_priority = 2)

        elif commandslist[0] in {'fav', 'bl', 'blacklisted'}:
            try:
                preference_command(
                    commandslist[1:],
                    PreferenceState.FAVORITE if commandslist[0] == 'fav' else PreferenceState.BLOCKED,
                )
            except ValueError as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif commandslist[0] in {'favs', 'blacklist'}:
            try:
                list_preferences(
                    PreferenceState.FAVORITE if commandslist[0] == 'favs' else PreferenceState.BLOCKED,
                    commandslist[1:],
                )
            except ValueError as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif commandslist[0] == 'beta':
            if len(commandslist) <= 2 and (len(commandslist) == 1 or commandslist[1] in {'on', 'off'}):
                IPrint('Former beta features are stable and always available; no toggle is required.', visible=visible)
            else:
                SAY(visible=visible, display_message='Usage: beta [on|off]', log_message='Invalid beta command', log_priority=2)

        elif commandslist == ['check_dev']:
            IPrint(f'Development mode: {"on" if ISDEV else "off"}', visible=visible)

        elif commandslist[0] in {'rm', 'del'}:
            try:
                recycle_library_media(commandslist[1:])
            except MediaRemovalError as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif commandslist in [['s'], ['stop']]:
            stopsong()

        elif commandslist[0].lower() in ['sleep', 'timer']:
            try:
                sleep_command(commandslist[1:])
            except ValueError as error:
                SAY(
                    visible=visible,
                    display_message=f'Invalid sleep timer: {error}',
                    log_message=f'Invalid sleep timer command: {error}',
                    log_priority=2,
                )

        elif commandslist[0].lower() == 'replaygain':
            try:
                replaygain_command(commandslist[1:])
            except (LibraryError, ValueError) as error:
                SAY(
                    visible=visible,
                    display_message=f'ReplayGain command failed: {error}',
                    log_message=f'ReplayGain command failed: {error}',
                    log_priority=2,
                )

        elif commandslist[0].lower() == 'broadcast':
            try:
                broadcast_command(commandslist[1:])
            except (BroadcastError, CredentialError, ValueError) as error:
                SAY(
                    visible=visible,
                    display_message=f'Broadcast command failed: {error}',
                    log_message=f'Broadcast command failed: {error}',
                    log_priority=2,
                )

        elif commandslist == ['update', 'prepare']:
            try:
                prepare_update()
            except Exception as error:
                SAY(
                    visible=visible,
                    display_message=f'Update backup failed: {error}',
                    log_message=f'Update backup failed: {error}',
                    log_priority=2,
                )

        elif commandslist[0].lower() == 'tools':
            try:
                tools_command(commandslist[1:])
            except (ValueError, ToolchainError) as error:
                SAY(
                    visible=visible,
                    display_message=f'Media tools error: {error}',
                    log_message=f'Media tools error: {error}',
                    log_priority=2,
                )

        elif commandslist[0].lower() == 'youtube':
            try:
                if len(commandslist) < 2 or commandslist[1].lower() != 'auth':
                    raise ValueError(
                        'Usage: youtube auth [status|set <browser[:profile]>|clear|test <YouTube URL>]'
                    )
                youtube_auth_command(commandslist[2:])
            except (OSError, ValueError, YouTubeError, MediaFailure) as error:
                report_youtube_error(error, 'authentication')

        elif commandslist[0].lower() == 'setup':
            try:
                setup_command(commandslist[1:])
            except (ValueError, SetupStateError) as error:
                SAY(
                    visible=visible,
                    display_message=f'Setup command failed: {error}',
                    log_message=f'Setup command failed: {error}',
                    log_priority=2,
                )

        elif commandslist == ['m']:
            ismuted = not ismuted

            if ismuted:
                vas.player.audio_set_mute(1)
            else:
                vas.player.audio_set_mute(0)
                vas.player.audio_set_volume(cached_volume*100)

        elif commandslist[0] in {'lyr', 'lyrics'}:
            if len(commandslist) == 1:
                lyrics_ops(show_window = True)
            elif commandslist[1:] == ['edit']:
                try:
                    edit_current_lyrics()
                except ValueError as error:
                    SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)
            else:
                SAY(visible=visible, display_message='Usage: lyrics [edit]', log_message='Invalid lyrics command', log_priority=2)

        elif commandslist[0].lower() in ['v', 'vol', 'volume']:
            try:
                if len(commandslist) == 2 and commandslist[1].isnumeric():
                    if '.' in commandslist[1]:
                        SAY(visible=visible, display_message='Volume must not have decimal point precision',
                            log_message='Volume set to decimal percentage', log_priority=2)
                    else:
                        volper = int(commandslist[1])
                        if volper in range(101):
                            vas.player.audio_set_volume(volper)
                            cached_volume = volper/100
                        else:
                            SAY(visible=visible, display_message='Volume percentage is out of range, it must be between 0 and 100',
                                log_message='Volume percentage out of range', log_priority=2)

                elif len(commandslist) == 1:
                    IPrint(f"}}}} {cached_volume*100} %", visible=visible)

            except Exception:
                SAY(visible=visible,
                    display_message = 'Some internal issue occured while setting player volume',
                    log_message = 'Some internal issue occured while setting player volume',
                    log_priority = 2)

        elif commandslist[0].lower() in ['mv', 'mvol', 'mvolume']:
            # '''
            try:
                if len(commandslist) == 2 and commandslist[1].isnumeric():
                    if '.' in commandslist[1]:
                        SAY(visible=visible, display_message='System volume must not have decimal point precision',
                            log_message='System volume set to decimal percentage', log_priority=2)
                    else:
                        volper = int(commandslist[1])
                        if volper in range(101):
                            setmastervolume(value=volper)
                        else:
                            SAY(visible=visible, display_message='System volume percentage is out of range, it must be between 0 and 100',
                                log_message='System volume percentage out of range', log_priority=2)

                elif len(commandslist) == 1:
                    if comtypes_load_error:
                        SAY(visible=visible,
                            log_message="comtypes functionality used even when not available",
                            display_message="This functionality is unavailable",
                            log_priority=3)
                    else:
                        try:
                            IPrint(f"}}}} {get_master_volume()} %", visible=visible)
                        except Exception:
                            SAY(visible=visible, display_message='ERROR: Couldn\'t get system master volume', log_message=f'Unknown error while getting master volume as percent: {currentsong}', log_priority=2)

            except Exception:
                SAY(visible=visible,
                    display_message = 'Some internal issue occured while setting the system volume',
                    log_message = 'Some internal issue occured while setting the system volume',
                    log_priority = 2)

            # '''

            # print('Sorry, system volume commands have been (temporarily) disabled...\n...due to some internal issue (Issue #244, #180 comtypes)')

        elif commandslist in [['l'], ['len'], ['length']]:
            if currentsong and currentsong_length != -1:
                if currentsong_length:
                    IPrint(convert(currentsong_length), visible=visible)
                else:
                    IPrint(convert(get_currentsong_length()), visible=visible)

        elif commandslist in [['lib'], ['library']]:
            IPrint("Opening location of library file", visible=visible)
            reveal_path(RUNTIME_PATHS.library_file)

        elif commandslist[0] == 'view':
            if len(commandslist) == 2:
                if commandslist[1] in ['lib', 'library']:
                    IPrint("Opening library file in browser for viewing", visible=visible)
                    if webbrowser._tryorder in [['windows-default', 'C:\\Program Files\\Internet Explorer\\IEXPLORE.EXE'], ['windows-default'], None]:
                        for brave_path in SYSTEM_SETTINGS['system_settings']['brave_paths']:
                            if os.path.exists(brave_path):
                                break

                        try:
                            webbrowser.register('brave', None, webbrowser.BackgroundBrowser(brave_path))
                            webbrowser.get('brave').open_new(RUNTIME_PATHS.library_file.as_uri())
                        except Exception:
                            webbrowser.open(RUNTIME_PATHS.library_file.as_uri())

                    else:
                        try:
                            webbrowser.get('brave').open_new(RUNTIME_PATHS.library_file.as_uri())
                        except Exception:
                            webbrowser.open(RUNTIME_PATHS.library_file.as_uri())

                elif commandslist[1] in ['lyr', 'lyrics']:
                    IPrint("Attempting to open lyrics file in browser for viewing", visible=visible)
                    lyrics_ops(show_window = False)
                    if webbrowser._tryorder in [['windows-default'], None]:
                        for brave_path in SYSTEM_SETTINGS['system_settings']['brave_paths']:
                            if os.path.exists(brave_path):
                                break

                        webbrowser.register('brave', None, webbrowser.BackgroundBrowser(brave_path))
                        if LYRICS_HTML_PATH.is_file():
                            webbrowser.get('brave').open_new(LYRICS_HTML_PATH.as_uri())
                        else:
                            SAY(visible=visible,
                                log_message = 'No lyrics available to view',
                                display_message = 'No lyrics available to view',
                                log_priority = 2)
                    else:
                        if LYRICS_HTML_PATH.is_file():
                            try:
                                webbrowser.get('brave').open_new(LYRICS_HTML_PATH.as_uri())
                            except Exception:
                                webbrowser.open(LYRICS_HTML_PATH.as_uri())
                        else:
                            SAY(visible=visible,
                                log_message = 'No lyrics available to view',
                                display_message = 'No lyrics available to view',
                                log_priority = 2)

        elif commandslist in [['music-downloads'], ['md']]:
            from beta import mediadl
            dl_dir_setup_code = mediadl.setup_dl_dir(SETTINGS, SYSTEM_SETTINGS)
            if dl_dir_setup_code not in range(4):
                dl_dir = dl_dir_setup_code
                if sys.platform == 'win32': dl_dir=dl_dir.replace('/', '\\')
                else: dl_dir=dl_dir.replace('\\', '/')
                IPrint(f"Opening downloads directory: {dl_dir}", visible=visible)
                open_path(dl_dir)
            else:
                # ERRORS have already been handled and logged by `mediadl.setup_dl_dir()`
                pass

        # E.g. /ys "The Weeknd Blinding Lights"
        #                       or
        #      /ys "The Weeknd Blinding Lights" 4
        elif commandslist[0] in ['/ys', '/youtube-search']:
            YOUTUBE_PLAY_TYPE = 1
            try:
                user_query = list(re.finditer(r'\"(.+?)"', command))
                if len(user_query):
                    query_re_obj = user_query[0]
                    qr_span = query_re_obj.span()
                    qr_val = query_re_obj.group()[1:-1].strip()
                    rescount = command[qr_span[1]:].strip()
                else: # User casually forgot to place query in double quotes..., let's assume they're there
                    qr_val = ' '.join(commandslist[1:])
                    rescount=''

                ytv_choices = None

                if rescount == '':
                    ytv_choices = [YT_query.search_youtube(search=qr_val)]

                elif rescount.isnumeric():
                    if int(rescount) == 1:
                        ytv_choices = [YT_query.search_youtube(search=qr_val)]
                    elif int(rescount) in range(2, max_yt_search_results_threshold+1):
                        ytv_choices = YT_query.search_youtube(
                            search=qr_val, rescount=int(rescount))
                    else:
                        if int(rescount) <= 0:
                            SAY(visible=visible,
                                log_message = 'Subceeded lower threshold for YT search result count',
                                display_message = "YT result count should be > 0, please retry",
                                log_priority = 2)

                        if int(rescount) > max_yt_search_results_threshold:
                            SAY(visible=visible,
                                log_message = 'Exceeded upper threshold for YT search result count',
                                display_message = f'YT results limit exceeded, retry with result count <= {max_yt_search_results_threshold} (can be changed in settings)',
                                log_priority = 2)

                else:
                    SAY(visible=visible,
                        log_message = 'Invalid value for YT search result count',
                        display_message = "Invalid value for YT search result count",
                        log_priority = 2)

                if ytv_choices:
                    choose_media_url(media_url_choices=ytv_choices)

            except Exception as error:
                report_youtube_error(error, 'search/playback')

        elif commandslist[0].lower() in ['/yl', '/youtube-link']:
            YOUTUBE_PLAY_TYPE = 0
            if len(commandslist) == 2:
                media_url = commandslist[1]
                if id_if_url_is_of_yt_format(media_url):
                    try:
                        play_vas_media(media_url=media_url, single_video=True)
                    except Exception as error:
                        report_youtube_error(error, 'playback')

                else:
                    SAY(visible=visible, display_message='Entered Youtube URL is invalid', log_message='Entered Youtube URL is invalid', log_priority = 2)
            else:
                SAY(visible=visible,
                    display_message = "Invalid YouTube-link command (too long)",  # Too many args
                    log_message = "Invalid YouTube-link command (too long)",
                    log_priority = 2)

        elif commandslist[0] in ['/ml', '/media-link']:
            if len(commandslist) == 2:
                user_aud_url = commandslist[1]
                if url_is_valid(user_aud_url):
                    try:
                        play_vas_media(media_url=commandslist[1], media_type='general')
                    except Exception as error:
                        stopsong()
                        if isinstance(error, MediaFailure) and error.code != FailureCode.DECODE:
                            message = str(error)
                        else:
                            message = "The media link could not be decoded or played"
                        SAY(
                            visible=visible,
                            display_message=message,
                            log_message=(
                                f"Custom media playback failed "
                                f"({getattr(error, 'code', type(error).__name__)})"
                            ),
                            log_priority=2,
                        )
                else:
                    SAY(visible=visible,
                        display_message = "Invalid or unreachable media link",
                        log_message = "Invalid or unreachable media link",
                        log_priority = 2)
            else:
                SAY(visible=visible,
                    display_message = "Invalid media-link command (too long)",  # Too many args
                    log_message = "Invalid media-link command (too long)",
                    log_priority = 2)

        elif commandslist[0].lower() == 'library' and len(commandslist) > 1:
            try:
                library_command(commandslist[1:])
            except (LibraryError, ValueError, IndexError) as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif commandslist[0].lower() == 'queue':
            try:
                queue_command(commandslist[1:])
            except (QueueError, MediaFailure, ValueError, IndexError) as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif commandslist[0].lower() == 'playlist':
            try:
                playlist_command(commandslist[1:])
            except (PlaylistError, QueueError, MediaFailure, ValueError, IndexError) as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif commandslist[0].lower() == 'album':
            try:
                album_command(commandslist[1:])
            except (AlbumError, PlaylistError, QueueError, MediaFailure, ValueError, IndexError) as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif commandslist[0].lower() == 'radio':
            try:
                radio_command(commandslist[1:])
            except (RadioError, QueueError, MediaFailure, ValueError, IndexError) as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif commandslist[0].lower() in {'recommend', 'recommendations'}:
            try:
                recommendation_command(commandslist[1:])
            except (QueueError, ValueError, IndexError) as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif commandslist[0].lower() in {'like', 'dislike'}:
            media = _preference_media(vas.controller.snapshot().media)
            if media:
                state = (
                    PreferenceState.FAVORITE
                    if commandslist[0].lower() == 'like'
                    else PreferenceState.BLOCKED
                )
                changed = PREFERENCES.set(media, state)
                if changed:
                    RECOMMENDER.record_event(media, commandslist[0].lower(), candidate=Candidate(media))
                IPrint(f'{commandslist[0].title()} {"recorded" if changed else "already set"}', visible=visible)
            else:
                IPrint('No active media', visible=visible)

        elif commandslist[0] in ['/wra', '/webradio']:
            if len(commandslist) == 1: # Default station is coffee if not stated otherwise
                r_station = 'coffee'
            elif len(commandslist) == 2:
                r_station = commandslist[1].strip()

            if len(commandslist) in [1, 2]:
                r_stations = ['coffee', 'chillout', 'lounge']

                radio_media = None
                if r_station.isnumeric():
                    if int(r_station)-1 in range(len(r_stations)):
                        r_station = r_stations[int(r_station)-1]
                        radio_media = r_station
                elif r_station in r_stations: # TODO - print these values in help...
                    radio_media = r_station

                if radio_media:
                    play_vas_media(media_url=None, media_type='radio', media_name=r_station)
                else:
                    SAY(visible=visible,
                        display_message = f'Unknown webradio station {colored.fg("navajo_white_1")}"{r_station}"{colored.fg("magenta_3a")} selected'+\
                                           '\n'+f'Choose one of the following stations ({colored.fg("navajo_white_1")}index or name{colored.fg("magenta_3a")}):',
                        log_message=f'Unknown webradio station "{r_station}" selected',
                        log_priority = 2)
                    IPrint(tbl([(f"{colored.fg('light_red')}/wra {i+1}{colored.attr('reset')}", j) for i, j in enumerate(r_stations)], tablefmt='plain'), visible=visible)
            else:
                SAY(visible=visible,
                    display_message = "Unknown webradio command (too long)",
                    log_message = "Unknown webradio command (too long)",
                    log_priority = 2)


        elif commandslist[0] in ['/rs', '/reddit-sessions']:
            IPrint(REDDIT_RETIRED_MESSAGE, visible=visible)

        elif commandslist in [['vivojay', 'favourite'], ['vivojay', 'fav']]:
            IPrint(
                'The legacy hard-coded favorite shortcut is retired; use fav, favs, or recommend related.',
                visible=visible,
            )



def _prompt_time(seconds):
    seconds = max(0, int(seconds or 0))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def prompt_text():
    """Build the testing snapshot's richer two-line prompt from live state."""
    snapshot = vas.controller.snapshot()
    media = snapshot.media
    if media:
        title = media.title or Path(media.original_uri).stem or media.original_uri
        prefix = f'[{songindex}] ' if isinstance(songindex, int) and songindex > 0 else ''
        first = (
            colored.fg('light_slate_blue') + '┏━' +
            colored.fg('navajo_white_1') + f' {prefix}{text_overflow_prettify(str(title), 72)}'
        )
        duration = snapshot.duration or media.duration or 0
        percent = (snapshot.position / duration * 100) if duration else 0
        state = {
            PlaybackState.PLAYING: 'playing ▶',
            PlaybackState.PAUSED: 'paused Ⅱ',
            PlaybackState.BUFFERING: 'buffering …',
            PlaybackState.FAILED: 'failed !',
        }.get(snapshot.state, snapshot.state.value)
        status = f'{_prompt_time(snapshot.position)} ━ {_prompt_time(duration)} ━ {percent:>3.0f}% ━ {state}'
        if snapshot.current_chapter:
            status += f' ━ {truncate_display_cells(snapshot.current_chapter.title, 36)}'
    else:
        first = colored.fg('light_slate_blue') + '┏━' + colored.fg('navajo_white_1') + ' (Not Playing)'
        status = 'ready'
    second = (
        colored.fg('light_slate_blue') + '┗━ ' +
        colored.fg('aquamarine_3') + status + ' ' +
        colored.fg('gold_1') + '❱ ' +
        colored.attr('reset') + colored.fg('dark_turquoise')
    )
    return f'{first}{colored.attr("reset")}\n{second}'


def mainprompt():
    global visible
    while True:
        try:
            prompt = prompt_text()
            command = input(prompt) if visible else getpass(prompt)
            print(colored.attr('reset'), end='')
            COMMAND_BUSY.set()
            try:
                outcode = process(command)
            finally:
                COMMAND_BUSY.clear()

            if isinstance(outcode, bool) and not outcode:
                exitplayer()
                break
        except KeyboardInterrupt:
            IPrint('\n', visible=visible)


def showversion():
    global visible, SYSTEM_SETTINGS
    if visible and SYSTEM_SETTINGS:
        try:
            print(colored.fg('aquamarine_3')+\
                  f"v {__version__}"+\
                  colored.attr('reset'))
            print()
        except Exception:
            pass


def showbanner():
    global visible
    banner_lines = []

    if visible:
        try:
            with RUNTIME_PATHS.resource('res', 'banner.banner').open(encoding='utf-8') as file:
                banner_lines = file.read().splitlines()
                maxlen = len(max(banner_lines, key=len))
                if maxlen % 10 != 0:
                    maxlen = (maxlen // 10 + 1) * 10 # Smallest multiple of 10 >= maxlen,
                                                     # Since 10 is the length of cols...
                                                     # So lines will be printed with full olor range
                                                     # and would be more visually pleasing...
                banner_lines = [(x + ' ' * (maxlen - len(x))) for x in banner_lines]
                for banner_line in banner_lines:
                    blue_gradient_print(banner_line, cols+cols[::-1])
        except OSError:
            pass

    if visible: showversion()

def initialize_audio_output():
    if os.environ.get('MARIANA_E2E') == '1':
        return
    try:
        default_output_device()
    except Exception as error:
        raise RuntimeError(
            "Mariana Player could not initialize an audio output device. "
            "Connect or enable speakers and verify the operating-system audio settings."
        ) from error


def run():
    global enforce_os_requirement, visible, USER_DATA

    initialize_audio_output()
    if PRESENCE.mode != PresencePrivacyMode.OFF:
        PRESENCE.start()
    DESKTOP_CONTROL.start_playback_monitor(vas.controller.snapshot)
    def update_safety():
        reasons = []
        if COMMAND_BUSY.is_set():
            reasons.append('command-active')
        if SLEEP_TIMER.status().active:
            reasons.append('sleep-timer')
        if vas.controller.snapshot().state not in {PlaybackState.IDLE, PlaybackState.PAUSED, PlaybackState.FAILED}:
            reasons.append('playback-active')
        if BROADCASTER.snapshot().state != BroadcastState.IDLE:
            reasons.append('broadcast-active')
        jobs = LIBRARY_SERVICE.status().get('jobs', [])
        if any(job.get('status') == 'leased' for job in jobs):
            reasons.append('profiler-transaction')
        download_jobs = DOWNLOADS.status()
        if any(job.get('state') in {'queued', 'running', 'paused'} for job in download_jobs):
            reasons.append('download-active')
        return not reasons, reasons
    DESKTOP_CONTROL.start_safety_monitor(update_safety)
    DESKTOP_CONTROL.emit('ready', {
        'version': __version__,
        'theme': SETTINGS.get('appearance', {}).get('terminal theme', 'aurora'),
    })
    _emit_queue_desktop_state()
    DESKTOP_CONTROL.emit('download', {'jobs': DOWNLOADS.status()})
    LIBRARY_SERVICE.start(initial_scan=True)
    USER_DATA['default_user_data']['stats']['log_ins'] += 1
    save_user_data()

    if FIRST_BOOT:
        startup_sound_path = RUNTIME_PATHS.resource('res', 'first_boot_startup_sound.mp3')
        if startup_sound_path.is_file():
            vas.set_media(_type='local', localpath=startup_sound_path)
            vas.media_player(action='play')
        notify(Time = 6000) # For 6 seconds

    if visible: showbanner()
    mainprompt()


def startup():
    global enforce_os_requirement, SOFT_FATAL_ERROR_INFO

    was_first_boot = FIRST_BOOT
    try: first_startup_greet(FIRST_BOOT)
    except Exception: raise

    if not was_first_boot and not SOFT_FATAL_ERROR_INFO:
        ensure_managed_tool_migration()

    if enforce_os_requirement and sys.platform not in {'win32', 'darwin', 'linux'}:
        sys.exit(f'ABORTING: Mariana Player does not support {sys.platform}')
    if not SOFT_FATAL_ERROR_INFO: # End program silently if SOFT_FATAL_ERROR_INFO is set
        if FATAL_ERROR_INFO:
            IPrint(f"FATAL ERROR ENCOUNTERED: {FATAL_ERROR_INFO}", visible=visible)
            IPrint("Exiting program...", visible=visible)
            sys.exit(1) # End program...forcefully...
        else: run()


if __name__ == '__main__':
    startup()
else:
    print(' '*30, end='\r')  # Get rid of the current '\r'...

# Way to convert chars outside BMP to unicode:
# out_str = test_str.encode('utf-16','surrogatepass').decode('utf-16')

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

import math
import threading
import time
from typing import TypedDict, cast

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
from sqlite3 import Error as SQLiteError

from mariana.tls import enable_system_trust_store

SYSTEM_TRUST_STORE_ENABLED = enable_system_trust_store()

# import concurrent.futures;                          print("Loaded 15/31", end='\r')

import sounddevice;                                 _boot_progress(14, 'audio devices')
# from scipy.io.wavfile import read;                  print("Loaded 15/31", end='\r')
from getpass import getpass;                        _boot_progress(15, 'prompts')
from url_validate import id_if_url_is_of_yt_format, url_is_valid; _boot_progress(16, 'URL validation')
from tabulate import tabulate as tbl;               _boot_progress(17, 'tables')
from ruamel.yaml import YAML;                       _boot_progress(18, 'settings')
from collections.abc import Iterable, Mapping;      _boot_progress(19, 'collections')
from logger import SAY;                             _boot_progress(20, 'logging')
from first_boot_welcome_screen import notify;       _boot_progress(21, 'first run')
from config_manager import load_system_settings, load_user_settings, save_user_settings
from mariana import playback_diagnostics
from mariana.albums import AlbumCatalog, AlbumError
from mariana.artwork import ArtworkState, create_artwork_manager
from mariana.broadcast import BroadcastError, BroadcastState, IcecastBroadcaster
from mariana.chapters import normalize_chapters
from mariana.command_catalog import serialize_command_catalog
from mariana.equalizer import EqualizerService, command_intent as equalizer_command_intent
from mariana.commands import (
    DOWNLOAD_TYPOS,
    SEARCH_COMMANDS,
    SearchAction,
    SearchScope,
    normalize_command,
    parse_search,
    search_rows,
)
from mariana.captions import CaptionError, CaptionPreferences
from mariana.command_parser import CommandSyntaxError, split_command
from mariana.collection_transfer import (
    CollectionTransferError,
    CollectionTransferService,
    TransferOperation,
    parse_transfer_request,
)
from mariana.credentials import CredentialError, CredentialStore
from mariana.database import MarianaDatabase
from mariana.desktop_control import DesktopControl
from mariana.discovery import DiscoverySelection
from mariana.entertainment_catalog import BY_ID as ENTERTAINMENT_ENTRIES
from mariana.entertainment_catalog import CatalogueReader
from mariana.download import DownloadError, download_media, prepare_download_target
from mariana.download_jobs import DownloadJobError, DownloadManager
from mariana.adhoc_identification import (
    DEFAULT_CAPTURE_SECONDS,
    MAX_CAPTURE_SECONDS,
    MIN_CAPTURE_SECONDS,
    AdHocIdentificationError,
    AdHocIdentificationService,
    CapturePhase,
)
from mariana.identity import AcoustIDClient, IdentificationService, LRCLIBClient, MusicBrainzClient, MIN_FINGERPRINT_SECONDS, IdentificationError, find_fpcalc
from mariana.homepage import HOMEPAGE_CACHE_STATE_KEY, HomepageConfiguration, HomepageService, ListenBrainzFreshReleasesProvider, create_homepage_image_cache
from mariana.library import LibraryCatalog, LibraryError
from mariana.library_service import LibraryProfilerService
from mariana.librivox import (
    API_INFO_URL as LIBRIVOX_API_INFO_URL,
    DEFAULT_LIMIT as LIBRIVOX_DEFAULT_LIMIT,
    LibrivoxCatalog,
    LibrivoxError,
)
from mariana.local_match import LocalMatchResult, LocalMatchStatus, LocalMediaMatcher
from mariana.loudness import LoudnessError, RSGainAnalyzer
from mariana.media_details import clean_component, flattened_details, format_file_size, format_probed_media_type, short_filename_plan, display_media_error, display_media_uri, normalized_provider_metadata
from mariana.media_removal import MediaRemovalError, MediaRemovalService
from mariana.models import (
    IdentityStatus,
    MediaCapabilities,
    MediaChapter,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
    QueueStrategy,
    canonical_uri,
    has_durable_podcast_identity,
    truncate_display_cells,
)
from mariana.navigation import NavigationContext, NavigationEntry, NavigationScope, parse_navigation, parse_relative_reference
from mariana.output_devices import OutputDeviceError, default_output_device
from mariana.output_targets import OutputTargetError, bind_output_target
from mariana.paths import initialize_runtime_paths
from mariana.platform import PlatformCapabilityError, open_path, reveal_path
from mariana.playlists import PlaylistError, PlaylistStore
from mariana.playback_resume import PlaybackResumeTracker
from mariana.playback_status import (
    FavoriteStatusProjection,
    PlaybackChapterProjection,
    PlaybackPolicyProjection,
    PlaybackStatusProjection,
    project_playback_status,
)
from mariana.playback import BYTES_PER_FRAME, SAMPLE_RATE, PlaybackError
from mariana.playback_events import LocalPlaybackEvents, Scaling
from mariana.play_regions import (
    PlayRegionError,
    PlayRegionStore,
    format_region_time,
    parse_region_time,
)
from mariana.preferences import MediaPreferences, PreferenceEntry, PreferenceState
from mariana.presence import PresenceCoordinator, PresencePrivacyMode, sanitize_presence_text
from mariana.queueing import PersistentQueue, QueueError
from mariana.radio import RadioCatalog, RadioError
from mariana.seek import SeekSyntaxError, parse_seek_target
from mariana.sleep_timer import SleepAction, SleepTimer, parse_duration
from mariana.sources import FailureCode, MediaFailure, ResolvedMedia
from mariana.station import StationError, StationManager
from mariana.tag_commands import TagCommandService
from mariana.tags import TagError, TagStore
from mariana.station_discovery import StationDiscovery, StationSeedError
from mariana.setup import SetupStateError, SetupStateStore
from mariana.tool_setup import discover_media_tools, persist_media_tools, setup_media_tools, executable_version
from mariana.toolchain import ToolchainError, ToolchainManager, find_javascript_runtime
from mariana.user_state import load_user_data, write_user_data_atomic
from mariana.version import __version__
from mariana.video import LocalVideo, VideoUnavailable, presentation_arguments
from mariana.integrations.discord_presence import (
    DiscordPresenceFailureCode,
    DiscordPresencePublisher,
)
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


def _configured_discord_application_id(system_settings):
    """Return the public Discord application ID, preferring a developer override."""
    return (
        os.environ.get('MARIANA_DISCORD_APPLICATION_ID')
        or system_settings.get('system_settings', {}).get('discord_application_id')
    )


def _configured_presence_mode(settings):
    """Return a safe privacy mode for persisted settings."""
    value = settings.get('integrations', {}).get('discord', {}).get('presence', {}).get('mode', 'off')
    try:
        return PresencePrivacyMode(value)
    except (TypeError, ValueError):
        return PresencePrivacyMode.OFF


def _configured_desktop_close_behavior(settings):
    """Return the validated desktop close-button policy."""
    desktop_settings = settings.get('desktop')
    if not isinstance(desktop_settings, dict):
        return 'tray'
    value = desktop_settings.get('close button', 'tray')
    return value if value in {'tray', 'quit'} else 'tray'

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


def _configured_playback_events(settings):
    """Return validated, privacy-conservative local interaction settings."""
    section = settings.get('playback events')
    if not isinstance(section, dict):
        section = {}
    enabled = section.get('enabled', False)
    forwarding = section.get('forward to log', False)
    retention = section.get('retention days', 90)
    return {
        'enabled': enabled if type(enabled) is bool else False,
        'forward_to_log': forwarding if type(forwarding) is bool else False,
        'retention_days': retention
        if isinstance(retention, int) and not isinstance(retention, bool) and 1 <= retention <= 3650
        else 90,
    }


def _configured_homepage(settings):
    """Return independent, validated homepage visibility/network preferences."""
    return HomepageConfiguration.from_mapping(settings.get('homepage'))


def _configured_automatic_artwork(settings):
    """Return the opt-in automatic network-artwork preference."""
    artwork_settings = settings.get('artwork')
    if not isinstance(artwork_settings, dict):
        return False
    value = artwork_settings.get('automatic online retrieval', False)
    return value if type(value) is bool else False



def _emit_discovery_event(event, payload) -> None:
    """Adapt typed service callbacks to the existing best-effort desktop emitter."""
    DESKTOP_CONTROL.emit(event, dict(payload))


def _trusted_artwork_reference(media: MediaRef, resolved: ResolvedMedia | None) -> str | None:
    """Select resolver/provider artwork without trusting arbitrary URL metadata."""
    candidate = resolved.metadata.get('artwork') if resolved is not None else None
    if not candidate and media.source == MediaSource.PODCAST:
        candidate = media.resolver_data.get('artwork')
    if media.source not in {MediaSource.PODCAST, MediaSource.YOUTUBE, MediaSource.URL}:
        return None
    return str(candidate).strip() if isinstance(candidate, str) and candidate.strip() else None


def _artwork_active_media_changed(
    media: MediaRef | None,
    resolved: ResolvedMedia | None,
) -> None:
    """Bind presentation-only artwork work to the authoritative active media."""
    if media is None:
        ARTWORK.clear()
        return
    ARTWORK.activate(
        media.stable_id,
        projection_media_id=media.stable_id,
        local_path=media.original_uri if media.source == MediaSource.LOCAL else None,
        trusted_provider_url=_trusted_artwork_reference(media, resolved),
    )


_ARTWORK_SINK_REMOVE = None
_ARTWORK_OBSERVER_REVISION = 0


def _connect_artwork_controller() -> None:
    """Attach artwork observation whenever runtime configuration replaces the controller."""
    global _ARTWORK_SINK_REMOVE, _ARTWORK_OBSERVER_REVISION
    _ARTWORK_OBSERVER_REVISION += 1
    revision = _ARTWORK_OBSERVER_REVISION
    if _ARTWORK_SINK_REMOVE is not None:
        try:
            _ARTWORK_SINK_REMOVE()
        except Exception:
            pass
    controller = vas.controller

    def active_media_changed(media, resolved):
        if revision == _ARTWORK_OBSERVER_REVISION and controller is vas.controller:
            _artwork_active_media_changed(media, resolved)

    _ARTWORK_SINK_REMOVE = controller.add_active_media_sink(active_media_changed)


def _close_artwork_controller() -> None:
    """Detach the presentation observer before closing its owned artwork service."""
    global _ARTWORK_SINK_REMOVE, _ARTWORK_OBSERVER_REVISION
    _ARTWORK_OBSERVER_REVISION += 1
    remove = _ARTWORK_SINK_REMOVE
    _ARTWORK_SINK_REMOVE = None
    try:
        if remove is not None:
            remove()
    finally:
        ARTWORK.close()
SETTINGS = load_user_settings()
# Serialize shared settings persistence from terminal and desktop requests.
_SETTINGS_WRITE_LOCK = threading.RLock()


def _persist_equalizer_configuration(value):
    with _SETTINGS_WRITE_LOCK:
        # Save a new mapping first; a failed atomic save must not publish live changes.
        save_user_settings({**SETTINGS, 'equalizer': value}, RUNTIME_PATHS.settings)
        SETTINGS['equalizer'] = value

def _persist_caption_configuration(value):
    with _SETTINGS_WRITE_LOCK:
        save_user_settings({**SETTINGS, 'captions': value}, RUNTIME_PATHS.settings)
        SETTINGS['captions'] = value


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
PLAYBACK_EVENT_SETTINGS = _configured_playback_events(SETTINGS)
PLAYBACK_EVENTS = LocalPlaybackEvents(
    DATABASE,
    **PLAYBACK_EVENT_SETTINGS,
    log_sink=lambda message: SAY(visible=False, log_priority=3, log_message=message),
)
LOCAL_MATCHER = LocalMediaMatcher(DATABASE)
_LOCAL_COPY_HINTED_MEDIA_IDS: set[str] = set()
_LOCAL_COPY_HINT_LOCK = threading.Lock()
PREFERENCES = MediaPreferences(DATABASE)
PLAY_REGIONS = PlayRegionStore(DATABASE)
REPLAYGAIN_SETTINGS = {
    **SETTINGS.get('replaygain', {}),
    **DATABASE.get_state('replaygain', {}),
}
LIVE_LEVELING_SETTINGS = {
    **SETTINGS.get('radio', {}).get('live leveling', {}),
    **DATABASE.get_state('radio_live_leveling', {}),
}
QUEUE = PersistentQueue(DATABASE)
_LOOP_LOCK = threading.RLock()
_LOOP_OVERRIDE = {
    'mode': 'off',
    'media_id': None,
    'title': None,
}
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
    blocked=PREFERENCES.is_blocked,
)
ALBUMS = AlbumCatalog(
    DATABASE,
    musicbrainz=IDENTITY.musicbrainz,
    browser_profile=SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile'),
)
LIBRIVOX = LibrivoxCatalog()
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
    play_region_provider=PLAY_REGIONS.get,
    playback_event_sink=PLAYBACK_EVENTS.capture,
)
ADHOC_IDENTIFICATION = AdHocIdentificationService(
    lambda media, pcm: IDENTITY.identify_pcm_window(media, pcm),
    on_update=lambda status: _adhoc_identification_update(status),
)
vas.controller.add_identification_sink(
    lambda samples, frames, media_id, session_id, decoder_token, position, mixed: ADHOC_IDENTIFICATION.offer(
        samples,
        frames,
        media_id=media_id,
        playback_session_id=session_id,
        decoder_token=decoder_token,
        start_position_seconds=position,
        mixed=mixed,
    )
)
vas.controller.add_active_media_sink(ADHOC_IDENTIFICATION.active_media_changed)
get_lyrics.configure(IDENTITY, vas.controller)
EQUALIZER = EqualizerService(lambda: vas.controller.equalizer, SETTINGS.get('equalizer'), _persist_equalizer_configuration)
DESKTOP_CONTROL = DesktopControl()


def _publish_video_state(payload: dict[str, object]) -> None:
    DESKTOP_CONTROL.emit('video', payload)


PLAYBACK_RESUME = PlaybackResumeTracker(
    DATABASE,
    lambda: vas.controller.snapshot(),
    lambda payload: DESKTOP_CONTROL.emit('resume-offer', payload),
)
VIDEO = LocalVideo(
    RUNTIME_PATHS.state('cache', 'video'), lambda: vas.controller.snapshot(),
    _publish_video_state,
    resolve_video=lambda media, resolved: vas.controller.resolvers.resolve_video(media, resolved),
    enabled=lambda: DESKTOP_CONTROL.enabled,
    youtube_cache_settings=SETTINGS.get('youtube video cache') if isinstance(SETTINGS.get('youtube video cache'), dict) else None,
    caption_preferences=CaptionPreferences(SETTINGS.get('captions'), _persist_caption_configuration),
)

_PRESENTATION_OBSERVER_REMOVERS = []
_PRESENTATION_OBSERVER_GENERATION = None


def _connect_video_controller() -> None:
    """Reconnect presentation observers when the authoritative controller changes."""
    global _PRESENTATION_OBSERVER_GENERATION
    _disconnect_video_controller()
    controller = vas.controller
    generation = object()
    _PRESENTATION_OBSERVER_GENERATION = generation

    def video_changed(media, resolved):
        if vas.controller is controller and _PRESENTATION_OBSERVER_GENERATION is generation:
            VIDEO.activate(media, resolved)

    def resume_changed(media, resolved):
        if vas.controller is controller and _PRESENTATION_OBSERVER_GENERATION is generation:
            PLAYBACK_RESUME.activate(media, resolved)

    _PRESENTATION_OBSERVER_REMOVERS.extend((
        controller.add_active_media_sink(video_changed),
        controller.add_active_media_sink(resume_changed),
    ))


def _disconnect_video_controller() -> None:
    global _PRESENTATION_OBSERVER_GENERATION
    _PRESENTATION_OBSERVER_GENERATION = None
    while _PRESENTATION_OBSERVER_REMOVERS:
        _PRESENTATION_OBSERVER_REMOVERS.pop()()


_connect_video_controller()

ARTWORK = create_artwork_manager(
    RUNTIME_PATHS.state('cache', 'artwork'),
    automatic_online=_configured_automatic_artwork(SETTINGS),
    on_update=lambda payload: _emit_discovery_event('artwork', payload),
)
_connect_artwork_controller()
DISCORD_PRESENCE = DiscordPresencePublisher(
    _configured_discord_application_id(SYSTEM_SETTINGS)
)
PRESENCE_MODE = _configured_presence_mode(SETTINGS)
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
_NAVIGATION_CONTEXT: NavigationContext | None = None
_LAST_SEARCH_CONTEXT: NavigationContext | None = None
_LAST_TAG_CONTEXT: NavigationContext | None = None
# Queue steps can each commit a cursor change; bound one CLI request even when
# repeat mode prevents the queue from ever reaching an end.
_MAX_QUEUE_NAVIGATION_STEPS = 100

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
        play_region_provider=PLAY_REGIONS.get,
        playback_event_sink=PLAYBACK_EVENTS.capture,
    )
    PLAYBACK_EVENTS.configure(**_configured_playback_events(SETTINGS))
    if equalizer_service := globals().get('EQUALIZER'):
        vas.controller.equalizer.submit(vas.controller.equalizer.prepare(equalizer_service.settings))
    _connect_video_controller()
    if artwork_service := globals().get('ARTWORK'):
        artwork_service.clear()
        artwork_service.set_automatic_online(_configured_automatic_artwork(SETTINGS))
        _connect_artwork_controller()
    if homepage_service := globals().get('HOMEPAGE'):
        homepage_configuration = _configured_homepage(SETTINGS)
        homepage_service.configure(
            show_on_startup=homepage_configuration.show_on_startup,
            online_enabled=homepage_configuration.online_enabled,
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


def _homepage_local_content():
    """Build a bounded title-only local summary without publishing media identities."""
    snapshot = vas.controller.snapshot()
    items = []
    if snapshot.media is not None:
        items.append({
            'kind': 'current',
            'title': snapshot.media.title or 'Current media',
            'subtitle': snapshot.media.artist or snapshot.media.source.value,
        })
    for entry in PREFERENCES.list(PreferenceState.FAVORITE, limit=4):
        items.append({
            'kind': 'favorite',
            'title': entry.label,
            'subtitle': entry.source.value if entry.source else 'Saved media',
        })
    for queued in QUEUE.items()[:4]:
        items.append({
            'kind': 'queue',
            'title': queued.media.title or 'Queued media',
            'subtitle': queued.media.artist or queued.media.source.value,
        })
    return {
        'library_count': len(LIBRARY.media_refs()),
        'favorite_count': len(PREFERENCES.list(PreferenceState.FAVORITE)),
        'playlist_count': len(QUEUE.playlists.list()),
        'queue_count': len(QUEUE.items()),
        'items': items,
    }


HOMEPAGE = HomepageService(
    configuration=_configured_homepage(SETTINGS),
    local_loader=_homepage_local_content,
    cache_load=lambda: DATABASE.get_state(HOMEPAGE_CACHE_STATE_KEY),
    cache_save=lambda payload: DATABASE.set_state(HOMEPAGE_CACHE_STATE_KEY, payload),
    additional_providers=(ListenBrainzFreshReleasesProvider(),),
    image_cache=create_homepage_image_cache(RUNTIME_PATHS.state('cache', 'homepage')),
    on_update=lambda payload: _emit_discovery_event('homepage', payload),
)

CATALOGUE_READER = CatalogueReader()
DISCOVERY = DiscoverySelection(
    catalog=ALBUMS,
    source=lambda item_id: HOMEPAGE.release_target(item_id),
    apply=lambda media, intent: _apply_discovery_selection(media, intent),
    unavailable=lambda media: _discovery_unavailable(media),
    on_update=lambda payload: _emit_discovery_event('discovery', payload),
    catalogue_choices=lambda identifier, cancelled: _catalogue_choices(identifier, cancelled),
)

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


def _relative_media_reference(request):
    """Resolve a collection-relative target without moving its cursor or playback."""
    media = vas.controller.snapshot().media
    if media is None:
        raise ValueError('Relative media references require currently active media')
    context = None
    scope = request.scope
    if scope == NavigationScope.AUTO and _NAVIGATION_CONTEXT and _NAVIGATION_CONTEXT.matches(media):
        context = _NAVIGATION_CONTEXT
        if context.scope == NavigationScope.FAVORITES:
            context = _favorite_navigation_context(media)
        elif context.scope == NavigationScope.PLAYLIST:
            context = _playlist_navigation_context(context.name, media)
    if scope == NavigationScope.FAVORITES:
        context = _favorite_navigation_context(media)
    elif scope == NavigationScope.PLAYLIST:
        context = _playlist_navigation_context(request.scope_name, media)
    elif scope == NavigationScope.RESULTS:
        if _LAST_SEARCH_CONTEXT is None:
            raise ValueError('No search results are available for navigation')
        context = _bind_navigation_context(_LAST_SEARCH_CONTEXT, media)
    if context is not None:
        target = context.target(request.offset)
        if target is None:
            raise ValueError('Relative media reference is outside the collection')
        entry = target[1]
        if entry.media is None:
            raise ValueError('The referenced media is missing or unavailable')
        return entry.media
    if scope in {NavigationScope.AUTO, NavigationScope.QUEUE}:
        current = QUEUE.current()
        items = QUEUE.items()
        if current is not None and current.media.stable_id == media.stable_id:
            position = next((i for i, item in enumerate(items) if item.queue_id == current.queue_id), None)
            if position is not None:
                repeat = QUEUE.state().get('repeat_mode')
                target = position if repeat == 'one' else position + request.offset
                if repeat == 'all':
                    target %= len(items)
                if target not in range(len(items)):
                    raise ValueError('Relative media reference is outside the queue')
                return items[target].media
        if scope == NavigationScope.QUEUE:
            raise ValueError('Current media is not the active queue item')
    if media.source != MediaSource.LOCAL:
        raise ValueError('No ordered collection is available for current media')
    index = _library_song_index(media.original_uri)
    if not isinstance(index, int):
        raise ValueError('Current media is outside the indexed library')
    target_index = index + request.offset
    if target_index not in range(1, len(_sound_files) + 1):
        raise ValueError('Relative media reference is outside the library')
    return _library_media(target_index)


def _expand_relative_library_target(tokens):
    """Extend explicit library-target commands, not time/gain or preference signs."""
    if not tokens or tokens[0] not in {'path', 'open', 'play', 'block', 'unblock'}:
        return tokens
    request = parse_relative_reference(' '.join(tokens[1:]))
    if request is None:
        return tokens
    media = _relative_media_reference(request)
    if media.source != MediaSource.LOCAL:
        raise ValueError('This command requires a local library item; use media info for online media')
    index = _library_song_index(media.original_uri)
    if not isinstance(index, int):
        raise ValueError('The referenced media is outside the indexed library')
    return [tokens[0], str(index)]


def _media_from_argument(argument):
    relative = parse_relative_reference(argument)
    if relative is not None:
        return _relative_media_reference(relative)
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
                title=(info.get('metadata') or {}).get('title') or media.title,
                artist=(info.get('metadata') or {}).get('artist'),
                album=(info.get('metadata') or {}).get('album'),
                duration=(info.get('metadata') or {}).get('duration') or media.duration,
                provenance='library',
                capabilities=media.capabilities,
                chapters=list(media.chapters),
            )
    return media


class PlaybackBlockedError(ValueError):
    """A safe refusal raised before a blocked item reaches playback."""


def _is_media_blocked(media):
    bound = _preference_media(media)
    if bound is None:
        return False
    if checker := getattr(PREFERENCES, 'is_blocked', None):
        return bool(checker(bound))
    getter = getattr(PREFERENCES, 'get', None)
    return bool(getter and getter(bound) == PreferenceState.BLOCKED)


def _ensure_media_playable(media):
    if _is_media_blocked(media):
        raise PlaybackBlockedError('Playback blocked for this media; use "unblock <library-index>" first')
    return media


def _blocked_label(value, media):
    return f'{value} [Blocked]' if _is_media_blocked(media) else value


def _media_rating(media):
    """Return a bounded rating while accepting pre-rating preference doubles."""
    bound = _preference_media(media)
    if bound is None:
        return 0
    if rating_getter := getattr(PREFERENCES, 'rating', None):
        try:
            return min(5, max(0, int(rating_getter(bound))))
        except (TypeError, ValueError):
            return 0
    return 0


def _is_media_favorite(media):
    bound = _preference_media(media)
    if bound is None:
        return False
    if checker := getattr(PREFERENCES, 'is_favorite', None):
        return bool(checker(bound))
    getter = getattr(PREFERENCES, 'get', None)
    return bool(getter and getter(bound) == PreferenceState.FAVORITE)


def _favorite_marker(media):
    """Return a heart only for a saved favourite, independently of stars."""
    return '♥' if _is_media_favorite(media) else ''


def _preference_markers(media):
    return _favorite_marker(media), '★' * _media_rating(media)


_ACTIVE_LISTING_STATES = {
    PlaybackState.RESOLVING,
    PlaybackState.BUFFERING,
    PlaybackState.PLAYING,
    PlaybackState.PAUSED,
    PlaybackState.SEEKING,
    PlaybackState.CROSSFADING,
}


def _active_media_marker(media):
    """Mark a listed item only when it is the authoritative active media."""
    if media is None:
        return ''
    try:
        snapshot = vas.controller.snapshot()
    except (AttributeError, RuntimeError):
        return ''
    active = getattr(snapshot, 'media', None)
    if active is None or getattr(snapshot, 'state', None) not in _ACTIVE_LISTING_STATES:
        return ''
    if active.stable_id == media.stable_id:
        return '▶'
    if active.source == media.source == MediaSource.RADIO:
        active_station = active.resolver_data.get('station_id')
        listed_station = media.resolver_data.get('station_id')
        if active_station and active_station == listed_station:
            return '▶'
    return ''


def _media_listing_fields(media):
    """Return path-free size/type columns for an available local media item."""
    if media is None or media.source != MediaSource.LOCAL:
        return '', ''
    info = None
    lookup = getattr(LIBRARY, 'info', None)
    if callable(lookup):
        for reference in (media.stable_id, media.original_uri):
            if not reference:
                continue
            try:
                info = lookup(reference)
            except (OSError, RuntimeError, SQLiteError, TypeError, ValueError):
                info = None
            if isinstance(info, Mapping):
                break
    if isinstance(info, Mapping) and info.get('state') not in (None, 'available'):
        return 'Unavailable', 'Unknown'
    metadata = info.get('metadata') if isinstance(info, Mapping) else None
    metadata = metadata if isinstance(metadata, Mapping) else {}
    size = info.get('size') if isinstance(info, Mapping) else None
    if size is None:
        try:
            size = Path(media.original_uri).stat().st_size
        except (OSError, RuntimeError, ValueError):
            pass
    return (
        format_file_size(size),
        format_probed_media_type(metadata.get('format'), metadata.get('codec')),
    )


_LISTING_ORDER_OPTIONS = frozenset({'o', 'desc'})


def _listing_selector(arguments):
    """Return the non-ordering portion of a list/recents command."""
    return [value for value in arguments if value.casefold() not in _LISTING_ORDER_OPTIONS]


def _listing_range(arguments):
    """Return an inclusive, one-based numeric listing range when one was supplied."""
    selector = ' '.join(_listing_selector(arguments)).strip()
    match = re.fullmatch(r'(\d+)\s*-\s*(\d+)', selector)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _listing_regex(arguments):
    """Compile a case-insensitive title filter, including the all/* conveniences."""
    selector = ' '.join(_listing_selector(arguments)).strip()
    if selector.casefold() in {'all', '*'}:
        selector = '.*'
    if not selector:
        return None
    if len(selector) > 512:
        raise ValueError('List pattern must be 512 characters or fewer')
    try:
        return re.compile(selector, re.IGNORECASE)
    except re.error as error:
        raise ValueError(f'Invalid list regular expression: {error.msg}') from error


def _media_display_label(media: MediaRef | None, fallback: str | None = None) -> str:
    """Resolve a local display label without changing stored or playback identity."""
    if label := sanitize_presence_text(getattr(media, 'title', None)):
        return label
    candidates = []
    if media is not None and media.source == MediaSource.LOCAL:
        try:
            info = LIBRARY.info(media.original_uri or media.stable_id)
            if info is None and media.original_uri and media.stable_id != media.original_uri:
                info = LIBRARY.info(media.stable_id)
        except (OSError, RuntimeError, SQLiteError, TypeError, ValueError):
            info = None
        if info:
            candidates.append((info.get('metadata') or {}).get('title'))
            path = info.get('canonical_path')
            if info.get('state') == 'available' and isinstance(path, str) and info.get('library_id'):
                candidates.append(Path(path).stem)
        candidates.append(media.resolver_data.get('library_display_title'))
    candidates.append(fallback)
    for candidate in candidates:
        if label := sanitize_presence_text(candidate):
            return label
    if media is None:
        return 'Media'
    return {
        MediaSource.LOCAL: 'Local media',
        MediaSource.YOUTUBE: 'YouTube media',
        MediaSource.URL: 'Online media',
        MediaSource.PODCAST: 'Podcast',
        MediaSource.RADIO: 'Internet radio',
        MediaSource.RECOMMENDATION: 'Recommended media',
    }.get(media.source, 'Media')


def _scoped_search_media_label(media: MediaRef | None, fallback: str | None = None) -> str:
    """Use the shared display policy for collection search and navigation."""
    return _media_display_label(media, fallback)


def _preference_search_media(entry):
    """Recover stored preference media without requiring it to be playable."""
    media = PREFERENCES.media(entry.stable_id)
    if entry.source == MediaSource.LOCAL and entry.uri:
        try:
            local = _preference_media(
                MediaRef(
                    MediaSource.LOCAL,
                    entry.uri,
                    stable_id=entry.stable_id,
                    title=media.title if media else None,
                    artist=media.artist if media else None,
                    album=media.album if media else None,
                    duration=media.duration if media else None,
                    capabilities=media.capabilities if media else MediaCapabilities(downloadable=False),
                    resolver_data=dict(media.resolver_data) if media else {},
                    chapters=list(media.chapters) if media else [],
                    provenance=media.provenance if media else 'library',
                )
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            local = None
        media = local or media
    elif media is None and entry.source is not None and entry.uri:
        media = MediaRef(
            entry.source,
            entry.uri,
            stable_id=entry.stable_id,
            title=entry.label,
            provenance='saved-preference',
        )
    return media


def _recent_listing_fields(index):
    """Return active/favourite/local facts for one reverse-chronological recent entry."""
    try:
        _play_type, media_player, identity = RECENTS_QUEUE[::-1][index]
        if media_player != -1 or not isinstance(identity, (list, tuple)) or len(identity) < 2:
            return '', '', '', '', ''
        path = identity[1]
        if not isinstance(path, str):
            return '', '', '', '', ''
        media = _preference_media(MediaRef(MediaSource.LOCAL, path))
        return _active_media_marker(media), *_preference_markers(media), *_media_listing_fields(media)
    except (IndexError, TypeError, ValueError):
        return '', '', '', '', ''


def _library_media(index):
    if index not in range(1, len(_sound_files) + 1):
        raise ValueError(f'Library number must be between 1 and {len(_sound_files)}')
    media = _preference_media(MediaRef(MediaSource.LOCAL, str(Path(_sound_files[index - 1]).resolve())))
    if media is None:
        raise ValueError(f'Library item #{index} is unavailable')
    return media


def _indexed_local_playback_media(media):
    """Attach trusted library metadata for local playback presentation only."""
    if media is None or media.source != MediaSource.LOCAL:
        return media
    info = LIBRARY.info(media.original_uri)
    if not info or info.get('state') != 'available':
        return media
    metadata = info.get('metadata') or {}
    canonical_path = info.get('canonical_path')
    library_id = info.get('library_id')
    if not isinstance(canonical_path, str) or not isinstance(library_id, str):
        return media
    resolver_data = dict(media.resolver_data)
    # The catalog already presents this indexed basename in library listings.
    # Keep it separate from media.title so external presence never receives it.
    resolver_data['library_display_title'] = Path(canonical_path).stem
    chapters = media.chapters or [
        MediaChapter.from_dict(item)
        for item in normalize_chapters(metadata.get('chapters'), media.duration or metadata.get('duration'))
    ]
    return MediaRef(
        MediaSource.LOCAL,
        canonical_path,
        stable_id=library_id,
        title=media.title or metadata.get('title'),
        artist=media.artist or metadata.get('artist'),
        album=media.album or metadata.get('album'),
        duration=media.duration or metadata.get('duration'),
        resolver_data=resolver_data,
        provenance='library',
        capabilities=media.capabilities,
        chapters=chapters,
    )


def _media_for_local_match(media):
    """Copy the active media only when playback supplied its finite duration."""
    if media is None or media.duration is not None:
        return media
    snapshot = vas.controller.snapshot()
    if snapshot.media is None or snapshot.media.stable_id != media.stable_id or snapshot.duration is None:
        return media
    payload = media.to_dict()
    payload['duration'] = snapshot.duration
    return MediaRef.from_dict(payload)


def _show_local_copy_hint(media):
    """Print one path-free hint per matched online item for this process."""
    if media is None:
        return None
    candidate = _media_for_local_match(media)
    try:
        duration = float(candidate.duration)
    except (TypeError, ValueError, OverflowError):
        duration = 0
    if (
        candidate.source
        not in {
            MediaSource.YOUTUBE,
            MediaSource.URL,
            MediaSource.PODCAST,
            MediaSource.RECOMMENDATION,
        }
        or not candidate.capabilities.finite
        or candidate.capabilities.live
        or not math.isfinite(duration)
        or duration <= 0
    ):
        return LocalMatchResult(LocalMatchStatus.UNSUPPORTED)
    media_id = media.stable_id
    with _LOCAL_COPY_HINT_LOCK:
        if media_id in _LOCAL_COPY_HINTED_MEDIA_IDS:
            return None
    try:
        result = LOCAL_MATCHER.match(candidate)
    except Exception:
        return None
    if result.status != LocalMatchStatus.MATCHED or result.library_index is None:
        return result
    with _LOCAL_COPY_HINT_LOCK:
        if media_id in _LOCAL_COPY_HINTED_MEDIA_IDS:
            return result
        _LOCAL_COPY_HINTED_MEDIA_IDS.add(media_id)
    IPrint(
        f'Local copy available: library item {result.library_index}. '
        'Run "media local-match current".',
        visible=visible,
    )
    return result


def _play_queue_item(item):
    global currentsong, current_media_type, isplaying, currentsong_length
    media = item.media
    _ensure_media_playable(media)
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
            _show_local_copy_hint(media)
    except Exception:
        RECOMMENDER.record_event(media, 'failure')
        action = QUEUE.mark_failure(item.queue_id)
        if action == 'retry':
            return _play_queue_item(item)
        if action == 'skip':
            next_item = _advance_queue_to_playable()
            if next_item:
                return _play_queue_item(next_item)
        raise
    RECOMMENDER.record_event(media, 'start')
    _prefetch_after(item)


def _set_current_media_state(media):
    global currentsong, current_media_type, isplaying, currentsong_length, songindex
    currentsong = media.title or media.original_uri
    currentsong_length = media.duration or -1
    current_media_type = {
        MediaSource.YOUTUBE: 0,
        MediaSource.URL: 1,
        MediaSource.PODCAST: 1,
        MediaSource.RADIO: 2,
        MediaSource.RECOMMENDATION: 0,
    }.get(media.source)
    songindex = _library_song_index(media.original_uri) if media.source == MediaSource.LOCAL else -1
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
        if candidate and _is_media_blocked(candidate.media):
            candidate = _queue_candidate_after(candidate)
        if candidate and candidate.media.capabilities.finite and not _is_media_blocked(candidate.media):
            media = _indexed_local_playback_media(candidate.media) or candidate.media
            vas.controller.prefetch(media)
    except Exception:
        pass


def _queue_candidate_after(item):
    """Return the next unblocked item without moving the persistent cursor."""
    items = QUEUE.items()
    if not items:
        return None
    try:
        start = next(index for index, candidate in enumerate(items) if candidate.queue_id == item.queue_id)
    except StopIteration:
        return None
    state = QUEUE.state()
    if state.get('repeat_mode') == 'one':
        return item if not _is_media_blocked(item.media) else None
    positions = list(range(start + 1, len(items)))
    if state.get('repeat_mode') == 'all':
        positions.extend(range(start + 1))
    return next((items[index] for index in positions if not _is_media_blocked(items[index].media)), None)


def _advance_queue_to_playable(*, previous=False):
    """Move the queue cursor until one playable item is found, without looping."""
    items = QUEUE.items()
    if not items:
        return None
    initial = QUEUE.current()
    for _ in items:
        item = QUEUE.previous() if previous else QUEUE.next()
        if item is None:
            return None
        if not _is_media_blocked(item.media):
            return item
        if initial is not None and item.queue_id == initial.queue_id:
            return None
    return None


def _record_queue_history(media):
    """Record a committed automatic start, not a prefetch, retry, or seek."""
    projection = project_playback_status(PlaybackSnapshot(PlaybackState.PLAYING, media=media))
    try:
        SAY(
            visible=False, log_priority=3, format_style=0,
            out_file=RUNTIME_PATHS.logs / 'history.log',
            log_message=projection.title or 'Media',
        )
    except OSError:
        playback_diagnostics.record(2, 'history.write_failed')


def _record_successful_start(media):
    """Record one successful start with enough identity for durable history actions."""
    try:
        PREFERENCES.remember(media)
    except Exception:
        playback_diagnostics.record(2, 'history.identity_write_failed')
    RECOMMENDER.record_event(media, 'start')


def _set_loop_override(mode='off', media=None):
    """Publish an identity-bound finite loop override without touching queue contents."""
    if mode not in {'off', 'once', 'infinite'}:
        raise ValueError(f'Unknown loop mode: {mode}')
    if mode != 'off' and media is None:
        raise ValueError('Looping requires current media')
    with _LOOP_LOCK:
        _LOOP_OVERRIDE.update(
            mode=mode,
            media_id=media.stable_id if media is not None else None,
            title=(media.title or 'Current media') if media is not None else None,
        )


def _consume_loop_override(media):
    """Return whether completion should replay, consuming a one-time override."""
    with _LOOP_LOCK:
        if _LOOP_OVERRIDE['media_id'] != media.stable_id:
            return False
        mode = _LOOP_OVERRIDE['mode']
        if mode == 'once':
            _LOOP_OVERRIDE.update(mode='off', media_id=None, title=None)
        return mode in {'once', 'infinite'}


def _loop_replay_requested(media):
    """Resolve explicit loop state and repeat-one for media outside the queue."""
    snapshot = vas.controller.snapshot()
    active = snapshot.media
    if (
        active is None or active.stable_id != media.stable_id
        or snapshot.state not in {PlaybackState.IDLE, PlaybackState.PLAYING, PlaybackState.CROSSFADING}
    ):
        return False
    if _consume_loop_override(media):
        return True
    if QUEUE.state().get('repeat_mode') != 'one':
        return False
    current = QUEUE.current()
    if current is not None and current.media.stable_id == media.stable_id:
        return False
    _set_loop_override('infinite', media)
    return True


def _loop_status():
    """Return a URL-free loop projection synchronized with queue repeat-one."""
    try:
        active = vas.controller.snapshot().media
    except Exception:
        active = None
    with _LOOP_LOCK:
        if (
            _LOOP_OVERRIDE['mode'] != 'off'
            and (active is None or active.stable_id != _LOOP_OVERRIDE['media_id'])
        ):
            _LOOP_OVERRIDE.update(mode='off', media_id=None, title=None)
        override = dict(_LOOP_OVERRIDE)
    queue_repeat = QUEUE.state().get('repeat_mode', 'off')
    mode = override['mode']
    if mode == 'off' and queue_repeat == 'one':
        mode = 'infinite'
    title = override['title'] or (active.title if active is not None else None) or 'Current media'
    return {
        'mode': mode,
        'remaining': 1 if mode == 'once' else None,
        'title': title if mode != 'off' else None,
        'queue_repeat': queue_repeat,
    }


def _replay_completed_media(media):
    """Replay one completed identity without changing or duplicating the queue."""
    _ensure_media_playable(media)
    current = QUEUE.current()
    if current is not None and current.media.stable_id == media.stable_id:
        snapshot = vas.controller.snapshot()
        if (
            snapshot.media is not None and snapshot.media.stable_id == media.stable_id
            and snapshot.state in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}
        ):
            _set_current_media_state(snapshot.media)
            _record_queue_history(snapshot.media)
            _record_successful_start(snapshot.media)
            _prefetch_after(current)
        else:
            _play_queue_item(current)
        return
    vas.supervisor.play(media, origin='automatic')
    _set_current_media_state(media)
    _record_queue_history(media)
    _show_local_copy_hint(media)
    _record_successful_start(media)


def _on_queue_item_complete(media):
    RECOMMENDER.record_event(media, 'completion')
    STATION.mark_played(media)
    if _loop_replay_requested(media):
        _replay_completed_media(media)
        return
    current = QUEUE.current()
    if current is None or current.media.stable_id != media.stable_id:
        RECOMMENDER.retrain_if_due()
        return
    if not AUTOPLAY_ENABLED:
        RECOMMENDER.retrain_if_due()
        return
    next_item = _advance_queue_to_playable()
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
        _set_current_media_state(snapshot.media)
        RECOMMENDER.record_event(snapshot.media, 'start')
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


def _confirmation_bypass(arguments, *, preserve_single_bare=False):
    """Remove one command-scoped confirmation token without consuming data."""
    values = list(arguments)
    long_flags = [index for index, value in enumerate(values) if value.casefold() == '--yes']
    trailing_bare = bool(
        values
        and values[-1].casefold() in {'y', 'yes'}
        and not (preserve_single_bare and len(values) == 1)
    )
    if len(long_flags) > 1 or (long_flags and trailing_bare):
        raise ValueError('Use only one confirmation bypass token: y, yes, or --yes')
    if long_flags:
        del values[long_flags[0]]
        return True, values
    if trailing_bare:
        values.pop()
        return True, values
    return False, values


def _confirm_action(message, *, assume_yes=False):
    if assume_yes:
        return True
    return input(f'{message} (y/N): ').strip().casefold() in {'y', 'yes'}


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


def _youtube_queue_request(arguments):
    values = list(arguments)
    result_count = 1
    if len(values) > 1 and values[-1].isdigit():
        result_count = int(values.pop())
    query = ' '.join(values).strip()
    if not query:
        raise QueueError('Usage: queue ys|youtube "<query>" [result-count]')
    if result_count < 1:
        raise QueueError('YouTube result count must be greater than zero')
    if result_count > max_yt_search_results_threshold:
        raise QueueError(f'YouTube result count must not exceed {max_yt_search_results_threshold}')
    return query, result_count


def _select_youtube_queue_result(choices):
    if len(choices) == 1:
        _, title, url = choices[0]
        return title, url
    selected = input(f'Choose video number between 1 and {len(choices)} (leave blank to cancel): ').strip()
    if not selected:
        IPrint('YouTube queue selection cancelled', visible=visible)
        return None
    if not selected.isdigit() or int(selected) not in range(1, len(choices) + 1):
        raise QueueError(f'YouTube selection must be a number between 1 and {len(choices)}')
    _, title, url = choices[int(selected) - 1]
    return title, url


def _queue_youtube_search(arguments):
    query, result_count = _youtube_queue_request(arguments)
    try:
        result = YT_query.search_youtube(search=query, rescount=result_count)
    except (OSError, YouTubeError) as error:
        if 'no youtube results found' in str(error).casefold():
            raise QueueError('YouTube search returned no results; no item was queued') from error
        browser_profile = SETTINGS.get('sources', {}).get('youtube', {}).get('browser profile')
        message = youtube_error_message(error, browser_profile)
        raise QueueError(message or 'YouTube search failed; no item was queued') from error

    choices = [(1, result[0], result[1])] if result_count == 1 else list(result)
    if not choices:
        raise QueueError('YouTube search returned no results; no item was queued')
    selected = _select_youtube_queue_result(choices)
    if selected is None:
        return None
    title, result_url = selected
    durable_url = canonical_uri(MediaSource.YOUTUBE, result_url)
    if not id_if_url_is_of_yt_format(durable_url):
        raise QueueError('YouTube search returned an invalid canonical media reference')
    media = MediaRef(
        MediaSource.YOUTUBE,
        durable_url,
        title=title,
        resolver_data={'youtube': True},
        provenance='youtube-search',
    )
    item = QUEUE.add(media)
    RECOMMENDER.record_event(media, 'manual_queue', candidate=Candidate(media))
    IPrint(f'Queued YouTube result: {title}', visible=visible)
    snapshot = vas.controller.snapshot()
    if snapshot.media is None or snapshot.state in {PlaybackState.IDLE, PlaybackState.FAILED}:
        position = next(index for index, queued in enumerate(QUEUE.items(), 1) if queued.queue_id == item.queue_id)
        IPrint(f"No media is playing; use 'queue jump {position}' to start this item.", visible=visible)
    return item


def _step_queue_playback(operation, count=1):
    """Move queue playback using the same policy for CLI and typed desktop controls."""
    if operation not in {'next', 'previous'}:
        raise QueueError('Queue playback step must be next or previous')
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise QueueError('Queue navigation count must be a positive integer')
    if count > _MAX_QUEUE_NAVIGATION_STEPS:
        raise QueueError(f'Queue navigation count must be between 1 and {_MAX_QUEUE_NAVIGATION_STEPS}')
    snapshot = vas.controller.snapshot()
    if operation == 'next' and snapshot.media:
        RECOMMENDER.record_event(
            snapshot.media,
            'early_skip',
            context={'position': snapshot.position, 'duration': snapshot.duration},
        )
        STATION.mark_played(snapshot.media)
    item = None
    for _ in range(count):
        item = _advance_queue_to_playable(previous=operation == 'previous')
        if item is None:
            break
    if item:
        _play_queue_item(item)
    return item


def queue_command(arguments):
    operation = arguments[0].lower() if arguments else 'list'
    if operation == 'list':
        rows = []
        for index, item in enumerate(QUEUE.items()):
            size, media_type = _media_listing_fields(item.media)
            rows.append((
                index + 1,
                '*' if QUEUE.current() and QUEUE.current().queue_id == item.queue_id else '',
                _active_media_marker(item.media),
                item.priority,
                _blocked_label(_media_display_label(item.media), item.media),
                *_preference_markers(item.media),
                size,
                media_type,
            ))
        IPrint(
            tbl(
                rows,
                headers=('#', 'Queue', 'Now', 'Priority', 'Media', 'Fav', 'Rating', 'Size', 'Media format'),
                tablefmt='plain',
            ) if rows else '(queue empty)',
            visible=visible,
        )
        IPrint(f'Queue source: {QUEUE.origin() or "legacy/custom"}', visible=visible)
    elif operation == 'tree':
        _print_queue_tree(QUEUE.tree())
    elif operation == 'group':
        _queue_group_command(arguments[1:])
    elif operation == 'reset':
        QUEUE.sync_library_defaults(LIBRARY.media_refs(), force=True)
        IPrint(f'Queue reset to {len(QUEUE.items())} library item(s)', visible=visible)
    elif operation in {'ys', 'youtube'}:
        _queue_youtube_search(arguments[1:])
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
        position = int(arguments[1]) - 1
        items = QUEUE.items()
        if position not in range(len(items)):
            raise QueueError('Queue position is out of range')
        _ensure_media_playable(items[position].media)
        _play_queue_item(QUEUE.jump(position))
    elif operation in {'next', 'previous'}:
        values = arguments[1:]
        if len(values) > 1 or (values and (not values[0].isdigit() or int(values[0]) <= 0)):
            raise QueueError('Usage: queue next|previous [positive-count]')
        count = int(values[0]) if values else 1
        if _step_queue_playback(operation, count) is None:
            IPrint('(end of queue)', visible=visible)
    elif operation == 'clear':
        yes, values = _confirmation_bypass(arguments[1:])
        if values:
            raise QueueError('Usage: queue clear [y|yes|--yes]')
        if not _confirm_action('Clear every item from the queue?', assume_yes=yes):
            IPrint('Queue clear cancelled', visible=visible)
            return
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
        if len(arguments) != 2:
            raise QueueError('Usage: queue repeat off|one|all')
        repeat_mode = arguments[1].lower()
        if repeat_mode not in {'off', 'one', 'all'}:
            raise QueueError(f'Unknown repeat mode: {repeat_mode}')
        _set_loop_override()
        QUEUE.set_repeat(repeat_mode)
        vas.controller.clear_prefetch()
        IPrint(f'Queue repeat: {repeat_mode}', visible=visible)
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
    if operation in {'next', 'prev', 'previous'}:
        direction = '.prev' if operation in {'prev', 'previous'} else '.next'
        return navigation_command(direction, [*values, '--in', 'playlist'])
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
    elif operation == 'history' and len(values) == 1:
        playlist = store.get(values[0])
        IPrint(f'Playlist {playlist.name}: current revision {playlist.revision}; '
               f'available revisions: {", ".join(map(str, store.revisions(playlist.playlist_id)))}', visible=visible)
    elif operation == 'restore':
        yes, values = _confirmation_bypass(values, preserve_single_bare=True)
        try:
            if len(values) != 2 or not values[1].isdecimal():
                raise ValueError
            revision = int(values[1])
            if revision < 1:
                raise ValueError
        except ValueError:
            raise PlaylistError('Usage: playlist restore "<name>" <revision> [--yes]') from None
        target = store.bind_mutation(values[0])
        if revision not in store.revisions(target.playlist_id):
            raise PlaylistError(f'Unknown playlist revision: {revision}')
        if not _confirm_action(f'Restore playlist "{target.name}" to revision {revision}? '
                               'Current contents will remain in history.', assume_yes=yes):
            return None
        playlist = store.restore(target.playlist_id, revision, expected=target)
        IPrint(f'Restored playlist: {playlist.name}; new revision {playlist.revision}', visible=visible)
    elif operation == 'delete':
        yes, values = _confirmation_bypass(values, preserve_single_bare=True)
        if len(values) != 1:
            raise PlaylistError('Usage: playlist delete "<name>" [y|yes|--yes]')
        target = store.bind_mutation(values[0])
        if not _confirm_action(f'Delete playlist "{target.name}"?', assume_yes=yes):
            IPrint('Playlist deletion cancelled', visible=visible)
            return
        IPrint(f'Deleted playlist: {store.delete_bound(target).name}', visible=visible)
    elif operation == 'clear':
        yes, values = _confirmation_bypass(values, preserve_single_bare=True)
        if len(values) != 1:
            raise PlaylistError('Usage: playlist clear "<name>" [y|yes|--yes]')
        target = store.bind_mutation(values[0])
        if not _confirm_action(f'Clear every item from playlist "{target.name}"?', assume_yes=yes):
            IPrint('Playlist clear cancelled', visible=visible)
            return
        playlist = store.clear_bound(target)
        IPrint(f'Cleared playlist: {playlist.name}', visible=visible)
    elif operation == 'add':
        at, values = _command_option(values, '--at')
        if len(values) < 3:
            raise PlaylistError(
                'Usage: playlist add "<name>" media <reference> [<reference> ...] [--at <path>] '
                '| playlist add "<name>" album|playlist <reference> [--at <path>]'
            )
        parent, position = _playlist_insertion(at)
        if values[1].lower() == 'media':
            playlist = store.add_media_many(
                values[0], [_media_from_argument(value) for value in values[2:]],
                parent=parent, position=position,
            )
        elif values[1].lower() == 'album' and len(values) == 3:
            album = ALBUMS.fetch(_album_reference(values[2]))
            snapshot = PlaylistStore.snapshot_from_media(
                [track.media for track in album.tracks if track.media is not None]
            )
            playlist = store.add_snapshot(
                values[0], snapshot, group_name=album.title, parent=parent, position=position,
                kind='album', source_ref=album.album_id,
            )
        elif values[1].lower() == 'playlist' and len(values) == 3:
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
    elif operation == 'export':
        if values.count('--yes') > 1:
            raise PlaylistError('Use --yes only once for playlist export overwrite approval')
        yes, values = _command_flag(values, '--yes')
        if len(values) != 2:
            raise PlaylistError('Usage: playlist export "<name>" <path.m3u8> [--yes]')
        target = store.bind_export(values[0], values[1])
        if target.destination.existed and not _confirm_action(
            f'Overwrite existing playlist export "{target.destination.path}"?',
            assume_yes=yes,
        ):
            IPrint('Playlist export cancelled', visible=visible)
            return
        IPrint(f'Exported playlist: {store.export_bound(target)}', visible=visible)
    else:
        raise PlaylistError(f'Invalid playlist command: {operation}')
    _emit_queue_desktop_state()


def tag_command(arguments):
    """Use durable tag identities and the standard media-listing presentation."""
    global _LAST_TAG_CONTEXT

    def resolve_target(reference):
        if reference == 'current':
            media = vas.controller.snapshot().media
            return _preference_media(media) if media is not None else None
        return _library_media(int(reference))

    service = TagCommandService(
        TagStore(DATABASE), resolve_target=resolve_target,
        confirm=lambda message: _confirm_action(message),
    )
    if arguments and arguments[0].casefold() in {'play', 'queue'}:
        operation = arguments[0].casefold()
        if len(arguments) != 2 or not re.fullmatch(r'[0-9]{1,19}', arguments[1]) or int(arguments[1]) < 1:
            raise TagError(f'Usage: tag {operation} <tag-result-number>')
        position = int(arguments[1]) - 1
        context = _LAST_TAG_CONTEXT
        if context is None or position not in range(len(context.entries)):
            raise TagError('Tag result is unavailable; run tag find again')
        entry = service.resolve_result(context.entries[position])
        if entry.media is None:
            raise TagError('Tag result is missing or unavailable')
        _ensure_media_playable(entry.media)
        if operation == 'queue':
            QUEUE.extend([entry.media])
            _emit_queue_desktop_state()
            IPrint(f'Queued: {entry.label}', visible=visible)
        else:
            if entry.media.source == MediaSource.LOCAL:
                index = _library_song_index(entry.media.original_uri)
                if isinstance(index, int) and _library_media(index).stable_id != entry.stable_id:
                    raise TagError('Library identity changed; run tag find again')
            _play_navigation_entry(entry)
            _remember_navigation_context(context.at(position))
        return entry
    result = service.execute(arguments)
    IPrint(result.message, visible=visible)
    if result.operation == 'find':
        context = NavigationContext(NavigationScope.RESULTS, result.entries, -1, 'tag results')
        _LAST_TAG_CONTEXT = context
        _remember_navigation_context(context, search=True)
        rows = [(
            entry.position, _active_media_marker(entry.media),
            _blocked_label(entry.label, entry.media) if entry.media is not None else entry.label,
            *_preference_markers(entry.media), *_media_listing_fields(entry.media),
        ) for entry in result.entries]
        IPrint(tbl(rows, tablefmt='mysql', headers=('#', 'Now', 'Media', 'Fav', 'Rating', 'Size', 'Media format')), visible=visible)
        if rows:
            IPrint('Use tag play N or tag queue N to select one of these bound results.', visible=visible)
    elif result.media_tags:
        IPrint(tbl([(item.tag.name, item.assignment_source, item.tag.description or '') for item in result.media_tags],
                   headers=('Tag', 'Assigned by', 'Description'), tablefmt='mysql'), visible=visible)
    elif result.tags:
        IPrint(tbl([(item.name, item.description or '') for item in result.tags],
                   headers=('Tag', 'Description'), tablefmt='mysql'), visible=visible)
    if result.groups:
        IPrint(tbl([(item.name, item.description or '') for item in result.groups],
                   headers=('Group', 'Description'), tablefmt='mysql'), visible=visible)
    return result


def _bind_transfer_favourite(media):
    bound = _preference_media(media)
    status = _favorite_status_projection(bound)
    if bound is None or not status.available or not status.toggle_enabled:
        return None, status.unavailable_reason or 'Favourite is unavailable'
    return bound, None


def transfer_command(arguments):
    """Copy or move ordered selections across playlists and favourites."""
    request = parse_transfer_request(arguments)
    service = CollectionTransferService(
        QUEUE.playlists,
        PREFERENCES,
        favourite_binder=_bind_transfer_favourite,
    )
    plan = service.plan(request)
    rows = [
        (
            item.source.label,
            item.source_index,
            item.media.artist or '',
            _media_display_label(item.media),
        )
        for item in plan.items
    ]
    IPrint(
        tbl(rows, headers=('Source', '#', 'Artist', 'Media'), tablefmt='plain'),
        visible=visible,
    )
    action = request.operation.value.title()
    summary = (
        f'{action} {plan.selected_count} item(s) to {request.destination.label}'
    )
    if request.dry_run:
        IPrint(f'Dry run: {summary}; no collections changed.', visible=visible)
        return plan
    if request.operation == TransferOperation.MOVE and not _confirm_action(
        f'{summary} and remove them from their source collections?',
        assume_yes=request.assume_yes,
    ):
        IPrint('Transfer cancelled', visible=visible)
        return None
    result = service.apply(plan)
    revisions = ', '.join(
        f'{name} revision {revision}' for name, revision in result.playlist_revisions
    )
    IPrint(
        f'{action} complete: {result.selected_count} item(s) -> {result.destination.label}'
        + (f' ({revisions})' if revisions else ''),
        visible=visible,
    )
    _emit_queue_desktop_state()
    return result


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


_LIBRIVOX_DOWNLOAD_FORMATS = frozenset({'mp3', 'flac', 'wav', 'm4a', 'opus'})


def _librivox_duration(value):
    if value is None:
        return ''
    seconds = max(0, round(float(value)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:d}:{seconds:02d}'


def _librivox_integer(value, *, name, minimum=0, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise LibrivoxError(f'LibriVox {name} must be a whole number') from None
    if number < minimum or (maximum is not None and number > maximum):
        boundary = f'between {minimum} and {maximum}' if maximum is not None else f'at least {minimum}'
        raise LibrivoxError(f'LibriVox {name} must be {boundary}')
    return number


def _print_librivox_results(books):
    rows = [
        (
            index,
            book.catalog_id,
            book.author_label,
            book.title,
            book.language or '',
            book.section_count or '',
            book.total_time or _librivox_duration(book.total_seconds),
        )
        for index, book in enumerate(books, 1)
    ]
    IPrint(
        tbl(
            rows,
            headers=('#', 'Catalog ID', 'Author', 'Audiobook', 'Language', 'Sections', 'Duration'),
            tablefmt='plain',
        ) if rows else '(no LibriVox audiobooks found)',
        visible=visible,
    )
    if rows:
        IPrint('Use a result number below, or id:<catalog-id> at any time.', visible=visible)


def _print_librivox_book(book):
    rows = (
        ('Catalog ID', book.catalog_id),
        ('Title', book.title),
        ('Author', book.author_label),
        ('Translator', ', '.join(book.translators) or 'Not supplied'),
        ('Language', book.language or 'Unknown'),
        ('Copyright year', book.copyright_year or 'Not supplied'),
        ('Sections', book.section_count or len(book.sections)),
        ('Duration', book.total_time or _librivox_duration(book.total_seconds) or 'Unknown'),
        ('Genres', ', '.join(book.genres) or 'Not supplied'),
        ('Catalog', book.catalog_url or 'Unavailable'),
        ('Text source', book.text_url or 'Unavailable'),
        ('RSS', book.rss_url or 'Unavailable'),
        ('Whole-book ZIP', book.zip_url or 'Unavailable'),
        ('Internet Archive', book.archive_url or 'Unavailable'),
        ('Artwork', book.artwork_url or 'Unavailable'),
    )
    IPrint(tbl(rows, tablefmt='plain'), visible=visible)
    if book.description:
        IPrint(f'Description\n{book.description}', visible=visible)


def _print_librivox_chapters(book):
    rows = [
        (
            index,
            section.number,
            section.title,
            ', '.join(section.readers) or book.author_label,
            _librivox_duration(section.duration_seconds),
            section.language or book.language or '',
        )
        for index, section in enumerate(book.sections, 1)
    ]
    IPrint(
        tbl(
            rows,
            headers=('#', 'Feed section', 'Title', 'Reader', 'Duration', 'Language'),
            tablefmt='plain',
        ) if rows else '(no playable LibriVox sections found)',
        visible=visible,
    )


def _librivox_search(operation, arguments):
    limit, values = _command_option(arguments, '--limit')
    offset, values = _command_option(values, '--offset')
    result_limit = _librivox_integer(
        limit or LIBRIVOX_DEFAULT_LIMIT,
        name='result count',
        minimum=1,
        maximum=50,
    )
    result_offset = _librivox_integer(offset or 0, name='offset', minimum=0)
    if operation == 'recent':
        if len(values) > 1:
            raise LibrivoxError('Usage: librivox recent [days] [--limit N] [--offset N]')
        days = _librivox_integer(values[0] if values else 30, name='recent days', minimum=1, maximum=3660)
        books = LIBRIVOX.search('recent', limit=result_limit, offset=result_offset, days=days)
    else:
        query = ' '.join(values).strip()
        if not query:
            raise LibrivoxError(
                f'Usage: librivox {operation} <text> [--limit N] [--offset N]'
            )
        kind = 'title' if operation == 'search' else operation
        books = LIBRIVOX.search(kind, query, limit=result_limit, offset=result_offset)
    _print_librivox_results(books)
    return books


def _download_librivox_sections(book, sections, *, output_format, destination, assume_yes):
    if output_format not in _LIBRIVOX_DOWNLOAD_FORMATS:
        choices = ', '.join(sorted(_LIBRIVOX_DOWNLOAD_FORMATS))
        raise LibrivoxError(f'LibriVox download format must be one of: {choices}')
    output_directory = _download_destination(destination)
    downloads = []
    book_stem = clean_component(book.title, fallback=f'LibriVox {book.catalog_id}')[:80]
    for section in sections:
        media = LIBRIVOX.media(book, section)
        chapter_stem = clean_component(section.title, fallback='Section')[:80]
        filename = f'{book_stem} - {section.number:03d} - {chapter_stem}.{output_format}'
        downloads.append((media, output_directory / filename))
    existing = sum(path.exists() for _, path in downloads)
    overwrite = f'; {existing} existing file(s) will be overwritten' if existing else ''
    if not _confirm_action(
        f'Download {len(downloads)} section(s) from "{book.title}" as '
        f'{output_format.upper()} into "{output_directory}"{overwrite}?',
        assume_yes=assume_yes,
    ):
        IPrint('LibriVox download cancelled', visible=visible)
        return ()
    completed = []
    for media, path in downloads:
        completed.append(
            _download_media_link(
                media.original_uri,
                output_format=output_format,
                destination=path,
                bound_media=media,
                assume_yes=True,
            )
        )
    return tuple(completed)


def _librivox_media_coordinates(media):
    """Return stable book/section coordinates without exposing transport URLs."""
    if media is None:
        return None
    data = media.resolver_data
    book_id = str(data.get('librivox_book_id') or '').strip()
    section_id = str(data.get('librivox_section_id') or '').strip()
    if not book_id or not section_id:
        return None
    try:
        number = int(data.get('librivox_section_number'))
        count = int(data.get('librivox_section_count'))
    except (TypeError, ValueError, OverflowError):
        number = count = 0
    return book_id, section_id, number, count


def _librivox_book_queue(book_id):
    """Return this book's persistent queue entries in feed-section order."""
    rows = []
    for queue_position, item in enumerate(QUEUE.items()):
        coordinates = _librivox_media_coordinates(item.media)
        if coordinates is None or coordinates[0] != book_id:
            continue
        rows.append((coordinates[2] or queue_position + 1, queue_position, item))
    rows.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in rows]


def _queue_librivox_book(book):
    """Append missing book sections and return all sections in catalog order."""
    media_items = [LIBRIVOX.media(book, section) for section in book.sections]
    existing_ids = {item.media.stable_id for item in QUEUE.items()}
    added = QUEUE.extend(media for media in media_items if media.stable_id not in existing_ids)
    for item in added:
        RECOMMENDER.record_event(
            item.media,
            'manual_queue',
            candidate=Candidate(item.media),
        )
    queue_by_identity = {}
    for item in QUEUE.items():
        queue_by_identity.setdefault(item.media.stable_id, item)
    ordered = [queue_by_identity[media.stable_id] for media in media_items]
    return ordered, added


def _play_librivox_queue_item(item):
    items = QUEUE.items()
    position = next(
        (index for index, queued in enumerate(items) if queued.queue_id == item.queue_id),
        None,
    )
    if position is None:
        raise LibrivoxError('The selected LibriVox chapter is no longer queued')
    selected = QUEUE.jump(position)
    _play_queue_item(selected)
    _emit_queue_desktop_state()
    return selected.media


def _play_librivox_book_section(book, chapter):
    chapter_number = _librivox_integer(
        chapter,
        name='chapter',
        minimum=1,
        maximum=len(book.sections),
    )
    ordered, _added = _queue_librivox_book(book)
    return _play_librivox_queue_item(ordered[chapter_number - 1])


def _current_librivox_media():
    """Prefer authoritative active media, then the persistent queue cursor."""
    snapshot = vas.controller.snapshot()
    if snapshot.media is not None:
        if _librivox_media_coordinates(snapshot.media) is None:
            raise LibrivoxError('The active media is not a LibriVox audiobook chapter')
        return snapshot.media, snapshot
    queued = QUEUE.current()
    if queued is None or _librivox_media_coordinates(queued.media) is None:
        raise LibrivoxError('No LibriVox audiobook chapter is active or selected')
    return queued.media, snapshot


def _resolve_librivox_reference(reference):
    if reference.casefold() != 'current':
        return LIBRIVOX.resolve(reference)
    media, _snapshot = _current_librivox_media()
    coordinates = _librivox_media_coordinates(media)
    if coordinates is None:
        raise LibrivoxError('The current media has no LibriVox book identity')
    book_id, _section_id, _number, _count = coordinates
    return LIBRIVOX.resolve(f'id:{book_id}')


def _print_current_librivox_chapter():
    media, snapshot = _current_librivox_media()
    coordinates = _librivox_media_coordinates(media)
    if coordinates is None:
        raise LibrivoxError('The current media has no LibriVox chapter identity')
    book_id, section_id, number, count = coordinates
    if number <= 0:
        queued = _librivox_book_queue(book_id)
        number = next(
            (index for index, item in enumerate(queued, 1) if item.media.stable_id == media.stable_id),
            0,
        )
    if count <= 0:
        count = max(number, len(_librivox_book_queue(book_id)))
    active = snapshot.media is not None and snapshot.media.stable_id == media.stable_id
    state = snapshot.state.value if active else 'selected in queue'
    position = _librivox_duration(snapshot.position) if active else ''
    rows = (
        ('Audiobook', media.album or media.title or 'LibriVox audiobook'),
        ('Chapter', f'{number}/{count}' if number and count else str(number or 'Unknown')),
        ('Title', media.title or 'Untitled chapter'),
        ('Reader', media.artist or 'Not supplied'),
        ('State', state),
        ('Position', position or 'Not currently playing'),
        ('Catalog ID', book_id),
        ('Section ID', section_id),
    )
    IPrint(tbl(rows, tablefmt='plain'), visible=visible)
    return {
        'book_id': book_id,
        'section_id': section_id,
        'chapter': number,
        'chapter_count': count,
        'state': state,
        'media_id': media.stable_id,
    }


def _navigate_librivox_book(operation, amount=1):
    """Navigate separate chapter resources without treating them as one file."""
    media, _snapshot = _current_librivox_media()
    coordinates = _librivox_media_coordinates(media)
    if coordinates is None:
        raise LibrivoxError('The current media has no LibriVox chapter identity')
    book_id, section_id, current_number, section_count = coordinates
    queued = _librivox_book_queue(book_id)
    if current_number <= 0:
        current_number = next(
            (
                index
                for index, item in enumerate(queued, 1)
                if (_librivox_media_coordinates(item.media) or ('', '', 0, 0))[1] == section_id
            ),
            0,
        )
    if section_count <= 0:
        section_count = len(queued)
    if current_number <= 0 or section_count <= 0:
        book = LIBRIVOX.resolve(f'id:{book_id}')
        current_number = next(
            (
                index
                for index, section in enumerate(book.sections, 1)
                if section.section_id == section_id
            ),
            0,
        )
        section_count = len(book.sections)
        queued, _added = _queue_librivox_book(book)
    if current_number <= 0:
        raise LibrivoxError('The current LibriVox chapter is no longer in this audiobook')
    target = {
        'first': 1,
        'last': section_count,
        'next': current_number + amount,
        'previous': current_number - amount,
    }.get(operation, amount)
    if target not in range(1, section_count + 1):
        raise LibrivoxError('No LibriVox chapter in that direction; book navigation does not wrap')
    selected = next(
        (
            item
            for item in queued
            if (_librivox_media_coordinates(item.media) or ('', '', 0, 0))[2] == target
        ),
        None,
    )
    if selected is None:
        book = LIBRIVOX.resolve(f'id:{book_id}')
        queued, _added = _queue_librivox_book(book)
        selected = queued[target - 1]
        section_count = len(queued)
    result = _play_librivox_queue_item(selected)
    IPrint(
        f'LibriVox chapter {target}/{section_count}: {result.title or "Untitled chapter"}',
        visible=visible,
    )
    return result


def _librivox_help():
    IPrint(
        'LibriVox public-domain audiobook catalog\n'
        '  librivox status|help\n'
        '  librivox search <title> [--limit N] [--offset N]\n'
        '  librivox author <surname> [--limit N] [--offset N]\n'
        '  librivox genre <genre> [--limit N] [--offset N]\n'
        '  librivox recent [days] [--limit N] [--offset N]\n'
        '  librivox show|chapters <result-number|id:catalog-id|current>\n'
        '  librivox play <result-number|id:catalog-id|current> [chapter]\n'
        '  librivox current|resume\n'
        '  librivox goto <chapter>|next [count]|previous [count]|first|last|restart\n'
        '  librivox queue <result-number|id:catalog-id|current> [chapter|all]\n'
        '  librivox download <result-number|id:catalog-id|current> [chapter|all] '
        '[--format mp3|flac|wav|m4a|opus] [--to <folder>] [--yes]\n'
        '  librivox rss <result-number|id:catalog-id|current>\n'
        '  librivox open <result-number|id:catalog-id|current> '
        '[catalog|text|archive|download|rss]\n'
        'Aliases: lv, libri. Playing a chapter appends missing sections of that book to the '
        'persistent queue, enabling automatic, next/previous, and restart-safe navigation. '
        'Search result numbers last only until the next LibriVox search; id:<catalog-id> is '
        'explicit and reusable.',
        visible=visible,
    )


def librivox_command(arguments):
    """Browse and play the official LibriVox public-domain audiobook catalog."""
    operation = arguments[0].casefold() if arguments else 'help'
    values = list(arguments[1:])
    if operation in {'help', '?'}:
        if values:
            raise LibrivoxError('Usage: librivox help')
        _librivox_help()
        return None
    if operation == 'status':
        if values:
            raise LibrivoxError('Usage: librivox status')
        IPrint(
            f'LibriVox catalog integration: ready for on-demand requests; '
            f'no account or API key required; '
            f'last results: {LIBRIVOX.result_count}; API reference: {LIBRIVOX_API_INFO_URL}',
            visible=visible,
        )
        return {'last_results': LIBRIVOX.result_count, 'api': LIBRIVOX_API_INFO_URL}
    if operation in {'search', 'author', 'genre', 'recent'}:
        return _librivox_search(operation, values)
    if operation in {'show', 'chapters'}:
        if len(values) != 1:
            raise LibrivoxError(f'Usage: librivox {operation} <result-number|id:catalog-id>')
        book = _resolve_librivox_reference(values[0])
        if operation == 'show':
            _print_librivox_book(book)
        else:
            _print_librivox_chapters(book)
        return book
    if operation == 'play':
        if len(values) not in {1, 2}:
            raise LibrivoxError('Usage: librivox play <result-number|id:catalog-id> [chapter]')
        book = _resolve_librivox_reference(values[0])
        selector = values[1] if len(values) == 2 else '1'
        if selector.casefold() == 'all':
            raise LibrivoxError('Use librivox queue <reference> all to add the complete audiobook')
        LIBRIVOX.select_sections(book, selector)
        return _play_librivox_book_section(book, selector)
    if operation == 'queue':
        if len(values) not in {1, 2}:
            raise LibrivoxError(
                'Usage: librivox queue <result-number|id:catalog-id> [chapter|all]'
            )
        book = _resolve_librivox_reference(values[0])
        sections = LIBRIVOX.select_sections(book, values[1] if len(values) == 2 else 'all')
        media_items = [LIBRIVOX.media(book, section) for section in sections]
        queued = QUEUE.extend(media_items)
        for item in queued:
            RECOMMENDER.record_event(
                item.media,
                'manual_queue',
                candidate=Candidate(item.media),
            )
        IPrint(f'Queued {len(queued)} LibriVox section(s): {book.title}', visible=visible)
        _emit_queue_desktop_state()
        return queued
    if operation == 'current':
        if values:
            raise LibrivoxError('Usage: librivox current')
        return _print_current_librivox_chapter()
    if operation in {'goto', 'next', 'previous', 'prev', 'first', 'last'}:
        normalized = 'previous' if operation == 'prev' else operation
        if normalized == 'goto':
            if len(values) != 1:
                raise LibrivoxError('Usage: librivox goto <chapter>')
            amount = _librivox_integer(values[0], name='chapter', minimum=1)
        elif normalized in {'next', 'previous'}:
            if len(values) > 1:
                raise LibrivoxError(f'Usage: librivox {normalized} [positive-count]')
            amount = _librivox_integer(
                values[0] if values else 1,
                name='chapter count',
                minimum=1,
            )
        else:
            if values:
                raise LibrivoxError(f'Usage: librivox {normalized}')
            amount = 1
        return _navigate_librivox_book(normalized, amount)
    if operation == 'restart':
        if values:
            raise LibrivoxError('Usage: librivox restart')
        media, snapshot = _current_librivox_media()
        if snapshot.media is not None and snapshot.media.stable_id == media.stable_id:
            try:
                vas.controller.seek(0, origin='cli')
            except Exception as error:
                raise LibrivoxError('Could not restart the current LibriVox chapter') from error
            DESKTOP_CONTROL.emit('playback', _playback_status_projection().to_dict())
            IPrint(f'Restarted LibriVox chapter: {media.title or "Untitled chapter"}', visible=visible)
            return media
        selected = next(
            (item for item in QUEUE.items() if item.media.stable_id == media.stable_id),
            None,
        )
        if selected is None:
            raise LibrivoxError('The selected LibriVox chapter is no longer queued')
        return _play_librivox_queue_item(selected)
    if operation == 'resume':
        if values:
            raise LibrivoxError('Usage: librivox resume')
        media, snapshot = _current_librivox_media()
        if snapshot.media is not None and snapshot.media.stable_id == media.stable_id:
            if snapshot.state == PlaybackState.PAUSED:
                try:
                    vas.controller.resume(origin='cli')
                except Exception as error:
                    raise LibrivoxError('Could not resume the current LibriVox chapter') from error
                _set_current_media_state(media)
                DESKTOP_CONTROL.emit('playback', _playback_status_projection().to_dict())
                IPrint(f'Resumed LibriVox chapter: {media.title or "Untitled chapter"}', visible=visible)
                return media
            if snapshot.state in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}:
                IPrint(f'LibriVox chapter is already playing: {media.title or "Untitled chapter"}', visible=visible)
                return media
        selected = next(
            (item for item in QUEUE.items() if item.media.stable_id == media.stable_id),
            None,
        )
        if selected is None:
            raise LibrivoxError('The selected LibriVox chapter is no longer queued')
        return _play_librivox_queue_item(selected)
    if operation == 'download':
        if values.count('--yes') > 1:
            raise LibrivoxError('Use --yes only once for a LibriVox download')
        assume_yes, values = _command_flag(values, '--yes')
        output_format, values = _command_option(values, '--format')
        destination, values = _command_option(values, '--to')
        if len(values) not in {1, 2}:
            raise LibrivoxError(
                'Usage: librivox download <result-number|id:catalog-id> [chapter|all] '
                '[--format mp3|flac|wav|m4a|opus] [--to <folder>] [--yes]'
            )
        book = _resolve_librivox_reference(values[0])
        sections = LIBRIVOX.select_sections(book, values[1] if len(values) == 2 else 'all')
        return _download_librivox_sections(
            book,
            sections,
            output_format=(output_format or 'mp3').casefold(),
            destination=destination,
            assume_yes=assume_yes,
        )
    if operation in {'rss', 'open'}:
        if operation == 'rss':
            if len(values) != 1:
                raise LibrivoxError('Usage: librivox rss <result-number|id:catalog-id>')
            reference, destination_name = values[0], 'rss'
        else:
            if len(values) not in {1, 2}:
                raise LibrivoxError(
                    'Usage: librivox open <result-number|id:catalog-id> '
                    '[catalog|text|archive|download|rss]'
                )
            reference = values[0]
            destination_name = values[1].casefold() if len(values) == 2 else 'catalog'
        book = _resolve_librivox_reference(reference)
        destinations = {
            'catalog': book.catalog_url,
            'text': book.text_url,
            'archive': book.archive_url,
            'download': book.zip_url,
            'rss': book.rss_url,
        }
        if destination_name not in destinations:
            raise LibrivoxError('LibriVox link must be catalog, text, archive, download, or rss')
        target = destinations[destination_name]
        if not target:
            raise LibrivoxError(f'This audiobook has no {destination_name} link')
        if not webbrowser.open(target):
            raise LibrivoxError(f'Could not open the LibriVox {destination_name} link')
        IPrint(f'Opened LibriVox {destination_name}: {book.title}', visible=visible)
        return target
    raise LibrivoxError(f'Unknown LibriVox operation: {operation}; use librivox help')


def _download_destination(value=None):
    if value:
        return Path(value).expanduser()
    configured = (SETTINGS.get('download') or {}).get('downloads folder')
    destination = Path(configured).expanduser() if configured else Path.home() / 'Music'
    if (SETTINGS.get('download') or {}).get('make a separate mariana folder within "downloads folder"', True):
        folder = ((SYSTEM_SETTINGS.get('system_settings') or {}).get('mariana_dl_dir') or 'Mariana Player')
        destination /= str(folder)
    return destination


def _default_download_media():
    """Prefer active playback, then restore the latest successful durable history identity."""
    snapshot = vas.controller.snapshot()
    if snapshot.media is not None and snapshot.state in {
        PlaybackState.BUFFERING,
        PlaybackState.PLAYING,
        PlaybackState.PAUSED,
        PlaybackState.SEEKING,
        PlaybackState.CROSSFADING,
    }:
        return _require_downloadable_online_media(snapshot.media), 'current media'
    row = DATABASE.fetchone(
        "SELECT e.stable_id FROM interaction_events e "
        "INNER JOIN media_items m ON m.stable_id=e.stable_id "
        "WHERE e.event_type='start' AND e.stable_id IS NOT NULL "
        "ORDER BY e.created_at DESC, e.id DESC LIMIT 1"
    )
    if not row:
        raise DownloadError('No active or recently played media is available')
    media = PREFERENCES.media(str(row['stable_id']))
    if media is None:
        raise DownloadError('The most recently played media identity is no longer available')
    return _require_downloadable_online_media(media, subject='most recently played media'), 'most recently played media'


def _download_media_link(
    media_url,
    *,
    output_format='mp3',
    destination=None,
    bound_media=None,
    assume_yes=False,
    confirm_subject=None,
):
    """Download through the existing generic path with one bound target and optional confirmation."""
    downloads = Path(SETTINGS['download']['downloads folder']).expanduser()
    default_stem = f'mariana-download-{int(time.time())}'
    if bound_media is not None:
        default_stem = clean_component(bound_media.title, fallback=default_stem)[:160]
    destination = Path(destination).expanduser() if destination is not None else downloads / f'{default_stem}.{output_format}'
    target = prepare_download_target(destination, output_format=output_format)
    if confirm_subject is not None:
        title = bound_media.title if bound_media is not None else None
        artist = bound_media.artist if bound_media is not None else None
        identity = f'{artist} — {title}' if artist and title else title or artist or 'Online media'
        overwrite = ' This will overwrite the existing file.' if target.existed else ''
        if not _confirm_action(
            f'Download {confirm_subject} "{identity}" as {output_format.upper()} to "{target.path}"?{overwrite}',
            assume_yes=assume_yes,
        ):
            IPrint('Download cancelled', visible=visible)
            return None
    elif target.existed and not _confirm_action(
        f'Overwrite existing download file "{target.path}"?',
        assume_yes=assume_yes,
    ):
        IPrint('Download cancelled', visible=visible)
        return None
    result = download_media(
        media_url,
        destination,
        output_format=output_format,
        ffmpeg_bin=MEDIA_TOOLS.get('ffmpeg bin'),
        output_target=target,
    )
    IPrint(f'Downloaded: {result}', visible=visible)
    return result


def download_shortcut_command(arguments):
    """Confirm and download active or most-recent finite online media as MP3."""
    assume_yes, values = _confirmation_bypass(arguments)
    if values:
        raise DownloadError('Usage: dl [y|yes|--yes]')
    media, subject = _default_download_media()
    return _download_media_link(
        media.original_uri,
        bound_media=media,
        assume_yes=assume_yes,
        confirm_subject=subject,
    )


def download_media_link_command(arguments):
    """Parse the existing generic media-link download command."""
    values = list(arguments)
    if values.count('--yes') > 1:
        raise DownloadError('Use --yes only once for download overwrite approval')
    yes, values = _command_flag(values, '--yes')
    if len(values) not in (1, 2, 3):
        raise DownloadError(
            'Usage: download-ml <current|URL> [mp3|flac|wav|m4a|opus] [output path] [--yes]'
        )
    media_url = values[0]
    output_format = values[1].lower() if len(values) >= 2 else 'mp3'
    current_media = None
    if media_url.casefold() == 'current':
        current_media = _current_downloadable_media()
        media_url = current_media.original_uri
    destination = Path(values[2]).expanduser() if len(values) == 3 else None
    return _download_media_link(
        media_url,
        output_format=output_format,
        destination=destination,
        bound_media=current_media,
        assume_yes=yes,
    )


def _current_youtube_media():
    if current_media_type == 0 and isinstance(currentsong, (tuple, list)) and len(currentsong) > 1:
        return MediaRef(MediaSource.YOUTUBE, str(currentsong[1]), title=str(currentsong[0]))
    media = vas.controller.snapshot().media
    if media is None:
        raise DownloadJobError('No media is currently active')
    if media.source == MediaSource.LOCAL:
        raise DownloadJobError('The active track is already stored locally and will not be downloaded again')
    if media.source != MediaSource.YOUTUBE:
        raise DownloadJobError(
            'The active media is not a YouTube track; use "download-ml current" '
            'for downloadable online media'
        )
    return media


def _require_downloadable_online_media(media, *, subject='active media'):
    """Validate one already-bound media identity without resolving or exposing its URL."""
    if media.source == MediaSource.LOCAL:
        raise DownloadError(f'The {subject} is already stored locally and will not be downloaded again')
    if (
        media.source == MediaSource.RADIO
        or media.capabilities.live
        or not media.capabilities.finite
        or not media.capabilities.downloadable
    ):
        raise DownloadError(f'The {subject} is not downloadable')
    return media


def _current_downloadable_media():
    """Bind the active finite online item for the general media downloader."""
    media = vas.controller.snapshot().media
    if media is None:
        raise DownloadError('No media is currently active')
    return _require_downloadable_online_media(media)


def _confirm_download(message, *, assume_yes=False):
    return _confirm_action(message, assume_yes=assume_yes)


def _download_overwrite_message(targets):
    existing = [target.path for target in targets if target.existed]
    if not existing:
        return ''
    destinations = '\n'.join(f'  - {path}' for path in existing)
    return f'\nOverwrite {len(existing)} existing download file(s):\n{destinations}'


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
    media_items = [track.media for track in downloadable if track.media is not None]
    output_targets = DOWNLOADS.bind_output_targets(
        media_items,
        destination=destination,
        metadata=metadata,
        missing_only=missing_only,
    )
    if not _confirm_download(
        f'Download album {album.album_artist or "Unknown artist"} — {album.title} '
        f'({edition}); {len(downloadable)} track(s), {len(unresolved)} unresolved; '
        f'destination {destination}?{_download_overwrite_message(output_targets)}',
        assume_yes=yes,
    ):
        IPrint('Album download cancelled', visible=visible)
        return None
    return DOWNLOADS.create(
        media_items,
        kind='album',
        quality=quality,
        destination=destination,
        album_id=album.album_id,
        metadata=metadata,
        missing_only=missing_only,
        output_targets=output_targets,
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
    yes, values = _confirmation_bypass(values, preserve_single_bare=album_mode)
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
        metadata = [{'title': media.title, 'artist': media.artist}]
        output_targets = DOWNLOADS.bind_output_targets(
            [media], destination=destination, metadata=metadata
        )
        if not _confirm_download(
            f'Download YouTube audio {media.title or media.original_uri} to {destination}?'
            f'{_download_overwrite_message(output_targets)}',
            assume_yes=yes,
        ):
            IPrint('Audio download cancelled', visible=visible)
            return None
        job = DOWNLOADS.create(
            [media],
            kind='track',
            quality=quality,
            destination=destination,
            metadata=metadata,
            output_targets=output_targets,
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
    elif operation == 'clean':
        yes, values = _confirmation_bypass(arguments[1:])
        if values != ['--missing']:
            raise LibraryError('Usage: library clean --missing [y|yes|--yes]')
        if not _confirm_action('Permanently remove every missing-file tombstone?', assume_yes=yes):
            IPrint('Library cleanup cancelled', visible=visible)
            return None
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
        action = arguments[1].lower()
        values = list(arguments[2:])
        yes = False
        if action == 'delete':
            yes, values = _confirmation_bypass(values, preserve_single_bare=True)
        if len(values) != 1:
            raise BroadcastError(
                'Usage: broadcast credentials set|status <profile> | '
                'broadcast credentials delete <profile> [y|yes|--yes]'
            )
        name = values[0]
        if name not in BROADCASTER.profiles:
            raise BroadcastError(f'Unknown broadcast profile: {name}')
        reference = BROADCASTER.profiles[name].reference
        if action == 'set':
            BROADCASTER.credentials.set(reference, getpass(f'Icecast password for {name}: '))
            IPrint(f'Credential stored in the operating-system keychain for {name}', visible=visible)
        elif action == 'delete':
            if not _confirm_action(f'Delete the stored broadcast credential for "{name}"?', assume_yes=yes):
                IPrint('Broadcast credential deletion cancelled', visible=visible)
                return None
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
    message = display_media_error(message)
    SAY(
        visible=visible,
        display_message=message,
        log_message=f'YouTube {operation} failed: {display_media_error(str(error))}',
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
        yes, values = _confirmation_bypass(arguments[1:])
        if values:
            raise ValueError('Usage: setup restart [y|yes|--yes]')
        if not _confirm_action('Restart first-run setup progress?', assume_yes=yes):
            IPrint('Setup restart cancelled', visible=visible)
            return SETUP_STORE.load()
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
        action = arguments[1].lower()
        values = list(arguments[2:])
        yes = False
        if action == 'delete':
            yes, values = _confirmation_bypass(values, preserve_single_bare=True)
        expected = {1, 2} if action == 'set' else {1}
        if len(values) not in expected:
            raise RadioError(
                'Usage: radio credentials set <station> [username] | '
                'radio credentials status <station> | '
                'radio credentials delete <station> [y|yes|--yes]'
            )
        station_name = values[0]
        station = RADIO.get(station_name)
        reference = f'radio:{station.station_id}'
        if action == 'set':
            username = values[1] if len(values) > 1 else 'source'
            CredentialStore().set(reference, getpass(f'Private-stream password for {station.name}: '))
            RADIO.set_credential(station.station_id, reference, username)
            IPrint(f'Private-stream credential stored for {station.name}', visible=visible)
        elif action == 'delete':
            if not _confirm_action(f'Delete the stored radio credential for "{station.name}"?', assume_yes=yes):
                IPrint('Radio credential deletion cancelled', visible=visible)
                return None
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
    if state == PreferenceState.BLOCKED:
        operation = arguments[0] if arguments else None
        if operation is None:
            blocked = PREFERENCES.is_blocked(media)
        elif operation == '!':
            blocked = PREFERENCES.toggle_blocked(media)
        elif operation in {'+', '-'}:
            blocked = operation == '+'
            PREFERENCES.set_blocked(media, blocked)
        else:
            raise ValueError('Usage: bl [!|+|-]')
        current = PreferenceState.BLOCKED if blocked else PreferenceState.NEUTRAL
        IPrint(f'Preference: {current.value}', visible=visible)
        return current
    operation = arguments[0] if arguments else None
    if state == PreferenceState.FAVORITE and media.source != MediaSource.LOCAL and operation in {None, '!', '+', '-'}:
        status = _favorite_status_projection(media)
        if not status.available or not status.toggle_enabled:
            if operation is None:
                current = PREFERENCES.get(media)
            elif operation == '-' or (operation == '!' and _is_media_favorite(media)):
                # Older builds could save transient online identities. Permit
                # removal without persisting their current transport again.
                PREFERENCES.set(media.stable_id, PreferenceState.NEUTRAL)
                current = PreferenceState.NEUTRAL
            else:
                raise ValueError(status.unavailable_reason or 'Favourite is unavailable')
            IPrint(f'Preference: {current.value}', visible=visible)
            return current
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


def block_command(arguments, *, unblock=False):
    """Bind a block mutation to current media or an immutable library item."""
    usage = 'unblock <library-index|current>' if unblock else 'block <current|library-index>'
    if len(arguments) != 1:
        raise ValueError(f'Usage: {usage}')
    target = arguments[0].casefold()
    library_index = None
    if target == 'current':
        media = _preference_media(vas.controller.snapshot().media)
        if media is None:
            raise ValueError('No current media to block' if not unblock else 'No current media to unblock')
    elif target.isdigit() and int(target) > 0:
        library_index = int(target)
        media = _library_media(library_index)
    else:
        raise ValueError(f'Usage: {usage}')
    blocked = not unblock
    changed = PREFERENCES.set_blocked(media, blocked)
    label = sanitize_presence_text(media.title)
    if not label and media.source == MediaSource.LOCAL:
        label = sanitize_presence_text(media.resolver_data.get('library_display_title'))
    label = label or {
        MediaSource.LOCAL: 'Local media',
        MediaSource.YOUTUBE: 'YouTube media',
        MediaSource.URL: 'Online media',
        MediaSource.PODCAST: 'Podcast',
        MediaSource.RADIO: 'Internet radio',
        MediaSource.RECOMMENDATION: 'Recommended media',
    }[media.source]
    prefix = f'Library #{library_index}: ' if library_index is not None else ''
    state = 'Playback blocked' if blocked else 'Playback unblocked'
    IPrint(f'{state}: {prefix}{label}' if changed else f'{state} already set: {prefix}{label}', visible=visible)
    return blocked


def blocked_command(arguments):
    if arguments not in ([], ['list']) and not (len(arguments) == 1 and arguments[0].isdigit()):
        raise ValueError('Usage: blocked [list|count]')
    values = [] if arguments == ['list'] else arguments
    return list_preferences(PreferenceState.BLOCKED, values, default_limit=None)


def _region_target(value, *, require_finite=True):
    """Bind one region command target to current identity or library index."""
    snapshot = vas.controller.snapshot()
    library_index = None
    if value.casefold() in {'current', 'now'}:
        media = _preference_media(snapshot.media)
        if media is None:
            raise PlayRegionError('No current media is available')
        duration = snapshot.duration or media.duration
    elif value.isdigit() and int(value) > 0:
        library_index = int(value)
        media = _library_media(library_index)
        info = LIBRARY.info(media.stable_id) or {}
        duration = media.duration or (info.get('metadata') or {}).get('duration')
    else:
        raise PlayRegionError('Region target must be current or a library index')
    if require_finite and (
        media.capabilities.live or not media.capabilities.finite or media.source == MediaSource.RADIO
    ):
        raise PlayRegionError('Live or non-finite media cannot have preferred playback bounds')
    try:
        duration_value = float(duration) if duration is not None else None
    except (TypeError, ValueError, OverflowError):
        duration_value = None
    if require_finite and (
        duration_value is None or not math.isfinite(duration_value) or duration_value <= 0
    ):
        raise PlayRegionError('A finite known media duration is required for playback bounds')
    if media.duration is None and duration_value is not None:
        media.duration = duration_value
    return media, duration_value, library_index


def _region_label(media, library_index=None):
    label = sanitize_presence_text(media.title)
    if not label and media.source == MediaSource.LOCAL:
        label = sanitize_presence_text(media.resolver_data.get('library_display_title'))
    label = label or {
        MediaSource.LOCAL: 'Local media',
        MediaSource.YOUTUBE: 'YouTube media',
        MediaSource.URL: 'Online media',
        MediaSource.PODCAST: 'Podcast',
        MediaSource.RADIO: 'Internet radio',
        MediaSource.RECOMMENDATION: 'Recommended media',
    }[media.source]
    return f'Library #{library_index}: {label}' if library_index is not None else label


def _region_description(region):
    if region is None or not region.active:
        return 'full media (no preferred bounds)'
    return f'{format_region_time(region.start_seconds)} -> {format_region_time(region.end_seconds)}'


def region_command(arguments):
    """Inspect or mutate non-destructive preferred playback bounds."""
    forms = (
        'region <current|library-index> start <time>',
        'region <current|library-index> end <time>',
        'region <current|library-index> <start> <end>',
        'region show <current|library-index>',
        'region clear|clear-start|clear-end <current|library-index>',
    )
    usage = ' | '.join(forms)
    if len(arguments) == 1 and arguments[0].casefold() in {'help', '--help', '-h'}:
        IPrint('\n'.join(forms), visible=visible)
        IPrint(
            'start changes only the starting bound; end changes only the ending bound. '
            'The other saved bound is preserved. An unset start means the beginning; '
            'an unset end means the natural end of the media.\n'
            'Examples: region current start 0:30 | region current end 3:45 | region 12 start 5.180\n'
            'Times are absolute (seconds, clock notation, or d/h/m/s/ms units). '
            'The start must be before the end and duration; the end cannot exceed duration.\n'
            'Changes are saved for the next playback start; they do not seek, pause, or trim media. '
            'Use regions to list saved bounds.',
            visible=visible,
        )
        return forms
    if not arguments:
        raise PlayRegionError(f'Usage: {usage}')
    operation = arguments[0].casefold()
    if operation in {'show', 'clear', 'clear-start', 'clear-end'}:
        if len(arguments) != 2:
            raise PlayRegionError(f'Usage: region {operation} <current|library-index>')
        media, _duration, library_index = _region_target(arguments[1], require_finite=False)
        if operation == 'clear':
            PLAY_REGIONS.clear(media)
        elif operation in {'clear-start', 'clear-end'}:
            PLAY_REGIONS.clear_bound(media, operation.removeprefix('clear-'))
        region = PLAY_REGIONS.get(media)
        IPrint(f'Play region for {_region_label(media, library_index)}: {_region_description(region)}', visible=visible)
        return region

    media, duration, library_index = _region_target(arguments[0])
    current = PLAY_REGIONS.get(media)
    values = arguments[1:]
    if len(values) >= 2 and values[0].casefold() in {'start', 'end'}:
        bound = values[0].casefold()
        timestamp = parse_region_time(' '.join(values[1:]))
        start = timestamp if bound == 'start' else current.start_seconds if current else None
        end = timestamp if bound == 'end' else current.end_seconds if current else None
    elif len(values) == 2:
        start = parse_region_time(values[0])
        end = parse_region_time(values[1])
    else:
        raise PlayRegionError(f'Usage: {usage}')
    region = PLAY_REGIONS.set(
        media,
        start_seconds=start,
        end_seconds=end,
        duration=duration,
    )
    IPrint(
        f'Preferred play region saved for {_region_label(media, library_index)}: '
        f'{_region_description(region)}. It applies on the next playback start.',
        visible=visible,
    )
    return region


def regions_command(arguments):
    if arguments:
        raise PlayRegionError('Usage: regions')
    rows = []
    for index, entry in enumerate(PLAY_REGIONS.list(), 1):
        media = PREFERENCES.media(entry.stable_id)
        if media is None:
            info = LIBRARY.info(entry.stable_id)
            if info:
                metadata = info.get('metadata') or {}
                media = MediaRef(
                    MediaSource.LOCAL,
                    '',
                    stable_id=entry.stable_id,
                    title=metadata.get('title'),
                    provenance='library',
                )
        label = _region_label(media) if media is not None else 'Saved media'
        rows.append((index, label, _region_description(entry)))
    IPrint(tbl(rows, headers=('#', 'Media', 'Preferred play region'), tablefmt='plain') if rows else '(no preferred play regions)', visible=visible)
    return rows


def _favorite_selection(index, *, rated=False):
    """Bind an index in the requested collection to one durable identity."""
    entries = PREFERENCES.list_rated() if rated else PREFERENCES.list(PreferenceState.FAVORITE)
    collection_label = 'Rated media' if rated else 'Favourite'
    if not entries:
        raise ValueError(f'No {collection_label.lower()} entries are saved')
    if index not in range(1, len(entries) + 1):
        raise ValueError(f'{collection_label} number must be between 1 and {len(entries)}')
    entry = entries[index - 1]
    stored = PREFERENCES.media(entry.stable_id)
    source = entry.source or (stored.source if stored else None)
    if source == MediaSource.LOCAL:
        info = LIBRARY.info(entry.stable_id)
        if not info or info.get('state') != 'available':
            raise ValueError(f'{collection_label} #{index} is missing or unavailable in the indexed library')
        canonical_path = info.get('canonical_path')
        if not isinstance(canonical_path, str) or not Path(canonical_path).is_file():
            raise ValueError(f'{collection_label} #{index} is missing or unavailable in the indexed library')
        metadata = info.get('metadata') or {}
        media = MediaRef(
            MediaSource.LOCAL,
            canonical_path,
            stable_id=entry.stable_id,
            title=metadata.get('title') or (stored.title if stored else None),
            artist=metadata.get('artist') or (stored.artist if stored else None),
            album=metadata.get('album') or (stored.album if stored else None),
            duration=metadata.get('duration') or (stored.duration if stored else None),
            resolver_data=dict(stored.resolver_data) if stored else {},
            provenance='library',
            capabilities=stored.capabilities if stored else MediaCapabilities(downloadable=False),
            chapters=list(stored.chapters) if stored else [],
        )
        media = _indexed_local_playback_media(media)
        library_index = _library_song_index(canonical_path)
        return entry, media, library_index if isinstance(library_index, int) else None
    if stored is None:
        raise ValueError(f'{collection_label} #{index} is unavailable')
    return entry, stored, None


def _favorite_display_label(entry: PreferenceEntry, media: MediaRef | None = None) -> str:
    """Return path- and URL-free text for favourite list and detail surfaces."""
    candidates = [media.title] if media else []
    if media and media.source == MediaSource.LOCAL and media.provenance == 'library':
        candidates.append(media.resolver_data.get('library_display_title'))
    candidates.append(entry.label)
    for candidate in candidates:
        if title := sanitize_presence_text(candidate):
            return title
    return {
        MediaSource.LOCAL: 'Local media',
        MediaSource.YOUTUBE: 'YouTube media',
        MediaSource.URL: 'Online media',
        MediaSource.PODCAST: 'Podcast',
        MediaSource.RADIO: 'Internet radio',
        MediaSource.RECOMMENDATION: 'Recommended media',
    }.get((media.source if media else entry.source), 'Media')


def _show_favorite_selection(index, entry, media, library_index, *, rated=False):
    source = media.source.value.replace('_', ' ').title()
    label = _blocked_label(_favorite_display_label(entry, media), media)
    collection_label = 'Rated' if rated else 'Favourite'
    IPrint(f'{collection_label} #{index}: {label}', visible=visible)
    IPrint(f'Favourite: {"yes" if _is_media_favorite(media) else "no"}', visible=visible)
    IPrint(f'Rating: {entry.rating}/5', visible=visible)
    IPrint(f'Source: {source}', visible=visible)
    if media.source == MediaSource.LOCAL:
        IPrint(
            f'Library: #{library_index}' if library_index is not None else 'Library: indexed item',
            visible=visible,
        )
        size, media_type = _media_listing_fields(media)
        IPrint(f'File: {size} · {media_type}', visible=visible)


def _play_favorite_selection(index, entry, media, library_index):
    """Play exactly the immutable media bound by ``_favorite_selection``."""
    _ensure_media_playable(media)
    try:
        if media.source == MediaSource.LOCAL:
            play_local_default_player(
                media.original_uri,
                _songindex=str(library_index) if library_index is not None else None,
                media=media,
            )
        else:
            stopsong()
            vas.supervisor.play(media, origin='cli')
            _set_current_media_state(media)
            _show_local_copy_hint(media)
    except (MediaFailure, OSError) as error:
        raise ValueError(f'Selected media #{index} could not be played') from error
    IPrint(f'Playing selected media #{index}: {_favorite_display_label(entry, media)}', visible=visible)
    return media


def favorite_command(arguments, *, play=False):
    """Inspect and change binary favourites without changing star assessments."""
    if play:
        if len(arguments) != 1 or not arguments[0].isdigit() or int(arguments[0]) <= 0:
            raise ValueError('Usage: .fav <favorite-index>')
        index = int(arguments[0])
        media = _play_favorite_selection(index, *_favorite_selection(index))
        _remember_navigation_context(_favorite_navigation_context(media))
        return media
    if arguments and arguments[0].casefold() in {'next', 'prev', 'previous'}:
        direction = '.prev' if arguments[0].casefold() in {'prev', 'previous'} else '.next'
        return navigation_command(direction, [*arguments[1:], '--in', 'favorites'])
    if not arguments or arguments == ['current']:
        media = _preference_media(vas.controller.snapshot().media)
        if media is None:
            raise ValueError('No current media to favorite/check')
        current = PREFERENCES.get(media)
        IPrint(
            f'Current media favourite: {"yes" if _is_media_favorite(media) else "no"}',
            visible=visible,
        )
        return current
    if arguments == ['list']:
        return list_preferences(PreferenceState.FAVORITE, [], default_limit=None)
    if len(arguments) == 1 and arguments[0] in {'!', '+', '-'}:
        return preference_command(arguments, PreferenceState.FAVORITE)
    if len(arguments) == 1 and arguments[0].isdigit() and int(arguments[0]) > 0:
        index = int(arguments[0])
        selection = _favorite_selection(index)
        _show_favorite_selection(index, *selection)
        return selection
    raise ValueError(
        'Usage: fav [list|favorite-index|current|!|+|-|next [N]|prev [N]] | '
        '.fav <favorite-index>'
    )


def _rating_value(value):
    normalized = value.casefold()
    if normalized in {'clear', 'none', 'unrated'}:
        return 0
    if not value.isdigit():
        raise ValueError('Rating must be a whole number from 1 to 5, or clear')
    rating = int(value)
    if not 1 <= rating <= 5:
        raise ValueError('Rating must be a whole number from 1 to 5, or clear')
    return rating


def rating_command(arguments, *, play=False):
    """Inspect or set the durable zero-to-five rating for current/library media."""
    usage = (
        'rating [current] | rating <1-5|clear> | '
        'rating <current|library-index> <1-5|clear> | rating show <rated-index> | '
        '.rating <rated-index>'
    )
    if play:
        if len(arguments) != 1 or not arguments[0].isdigit() or int(arguments[0]) <= 0:
            raise ValueError('Usage: .rating <rated-index>')
        index = int(arguments[0])
        return _play_favorite_selection(index, *_favorite_selection(index, rated=True))
    if len(arguments) == 2 and arguments[0].casefold() == 'show':
        if not arguments[1].isdigit() or int(arguments[1]) <= 0:
            raise ValueError(f'Usage: {usage}')
        index = int(arguments[1])
        selection = _favorite_selection(index, rated=True)
        _show_favorite_selection(index, *selection, rated=True)
        return selection
    snapshot_media = _preference_media(vas.controller.snapshot().media)
    if not arguments or arguments == ['current']:
        if snapshot_media is None:
            raise ValueError('No current media to rate')
        rating = _media_rating(snapshot_media)
        IPrint(f'Rating: {rating}/5' if rating else 'Rating: unrated', visible=visible)
        return rating

    if len(arguments) == 1:
        media = snapshot_media
        value = arguments[0]
    elif len(arguments) == 2:
        target, value = arguments
        if target.casefold() == 'current':
            media = snapshot_media
        elif target.isdigit() and int(target) > 0:
            media = _library_media(int(target))
        else:
            raise ValueError(f'Usage: {usage}')
    else:
        raise ValueError(f'Usage: {usage}')
    if media is None:
        raise ValueError('No current media to rate')
    status = _favorite_status_projection(media)
    if not status.available or not status.toggle_enabled:
        raise ValueError(status.unavailable_reason or 'Rating is unavailable')
    rating = _rating_value(value)
    changed = PREFERENCES.set_rating(media, rating)
    label = 'unrated' if rating == 0 else f'{rating}/5'
    IPrint(f'Rating: {label}' if changed else f'Rating already set: {label}', visible=visible)
    return rating


def ratings_command(arguments):
    """List all positively rated media, highest rating first within recency order."""
    return list_preferences(PreferenceState.FAVORITE, arguments, default_limit=None, rated=True)


def list_preferences(state, arguments, *, default_limit=MAX_RESULT_COUNT, rated=False):
    if len(arguments) > 1 or (arguments and not arguments[0].isdigit()):
        raise ValueError('Preference list accepts an optional numeric limit')
    limit = int(arguments[0]) if arguments else default_limit
    entries = PREFERENCES.list_rated(limit) if rated else PREFERENCES.list(state, limit)
    show_hearts = rated or PreferenceState(state) != PreferenceState.FAVORITE

    def reference(entry):
        if entry.source == MediaSource.LOCAL:
            if entry.availability != 'available' or not entry.uri:
                return 'Unavailable library item'
            target = str(Path(entry.uri).expanduser().resolve()).casefold()
            library_index = next(
                (
                    index
                    for index, path in enumerate(_sound_files, start=1)
                    if str(Path(path).expanduser().resolve()).casefold() == target
                ),
                None,
            )
            origin = f'Library #{library_index}' if library_index is not None else 'Indexed library item'
        elif entry.source == MediaSource.YOUTUBE:
            origin = 'YouTube'
        elif entry.source == MediaSource.URL:
            origin = 'Online media'
        elif entry.source is not None:
            origin = entry.source.value.replace('_', ' ').title()
        else:
            origin = 'Media'
        return origin

    rows = []
    for index, entry in enumerate(entries):
        media = PREFERENCES.media(entry.stable_id)
        listing_media = media
        if listing_media is None and entry.source == MediaSource.LOCAL and entry.uri:
            listing_media = MediaRef(
                MediaSource.LOCAL,
                entry.uri,
                stable_id=entry.stable_id,
                provenance='library',
            )
        size, media_type = _media_listing_fields(listing_media)
        row = (
            index + 1,
            _active_media_marker(listing_media),
            _blocked_label(_favorite_display_label(entry, listing_media), listing_media),
            *((_favorite_marker(listing_media),) if show_hearts else ()),
            '★' * entry.rating,
            reference(entry),
            size,
            media_type,
        )
        rows.append(row)
    headers = ('#', 'Now', 'Title', *(('Fav',) if show_hearts else ()), 'Rating', 'Source', 'Size', 'Media format')
    IPrint(
        tbl(
            rows,
            headers=headers,
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


def _scoped_search_entries(request):
    """Return stable, one-based search entries for one explicit collection."""
    if request.scope in {SearchScope.FAVORITES, SearchScope.BLOCKED}:
        state = (
            PreferenceState.FAVORITE
            if request.scope == SearchScope.FAVORITES
            else PreferenceState.BLOCKED
        )
        entries = []
        for position, preference in enumerate(PREFERENCES.list(state), 1):
            media = _preference_search_media(preference)
            label = _favorite_display_label(preference, media)
            entries.append({
                'position': position,
                'media': media,
                'stable_id': preference.stable_id,
                'label': label,
                'search': ' '.join(filter(None, (
                    label,
                    getattr(media, 'artist', None),
                    getattr(media, 'album', None),
                    getattr(media, 'provenance', None),
                ))),
            })
        return entries
    if request.scope == SearchScope.QUEUE:
        return [
            {
                'position': position,
                'media': item.media,
                'stable_id': item.media.stable_id,
                'label': _scoped_search_media_label(item.media),
                'search': ' '.join(filter(None, (
                    _scoped_search_media_label(item.media),
                    item.media.artist,
                    item.media.album,
                    item.media.provenance,
                ))),
                'queue_id': item.queue_id,
            }
            for position, item in enumerate(QUEUE.items(), 1)
        ]
    if request.scope == SearchScope.PLAYLIST:
        try:
            playlist = QUEUE.playlists.get(request.scope_name or '')
        except PlaylistError as error:
            raise ValueError(str(error)) from error
        return [
            {
                'position': position,
                'media': media,
                'stable_id': media.stable_id,
                'label': _scoped_search_media_label(media),
                'search': ' '.join(filter(None, (
                    _scoped_search_media_label(media),
                    media.artist,
                    media.album,
                    media.provenance,
                ))),
                'playlist': playlist.name,
            }
            for position, media in enumerate(QUEUE.playlists.flattened_media(playlist.tree), 1)
        ]
    raise ValueError(f'Unsupported search scope: {request.scope.value}')


def _search_scope_description(request):
    if request.scope == SearchScope.FAVORITES:
        return 'favorites'
    if request.scope == SearchScope.BLOCKED:
        return 'blocked media'
    if request.scope == SearchScope.QUEUE:
        return 'queue'
    if request.scope == SearchScope.PLAYLIST:
        return f'playlist "{request.scope_name}"'
    return 'library'


def _play_scoped_search_entry(entry, request):
    """Play the bound scoped result without converting it into a library index."""
    media = entry['media']
    if media is None:
        raise ValueError(f'Search result #{entry["position"]} is unavailable')
    _ensure_media_playable(media)
    if request.scope == SearchScope.QUEUE:
        items = QUEUE.items()
        position = next(
            (index for index, item in enumerate(items) if item.queue_id == entry['queue_id']),
            None,
        )
        if position is None:
            raise ValueError('The selected queue result is no longer available')
        return _play_queue_item(QUEUE.jump(position))
    if request.scope == SearchScope.FAVORITES:
        return _play_favorite_selection(entry['position'], *_favorite_selection(entry['position']))
    if media.source == MediaSource.LOCAL:
        library_index = _library_song_index(media.original_uri)
        if isinstance(library_index, int):
            return local_play_commands([None, str(library_index)])
        if not Path(media.original_uri).is_file():
            raise ValueError(f'Search result #{entry["position"]} is missing or unavailable')
        return play_local_default_player(media.original_uri, _songindex=None, media=media)
    stopsong()
    vas.supervisor.play(media, origin='cli')
    _set_current_media_state(media)
    _show_local_copy_hint(media)
    return media


def _advanced_scoped_search(request):
    entries = _scoped_search_entries(request)
    by_position = {entry['position']: entry for entry in entries}
    results = search_rows(
        [(entry['position'], entry['search']) for entry in entries],
        request,
    )
    if not results:
        IPrint(colored.fg('hot_pink_1a') + '-- No results found --' + colored.attr('reset'), visible=visible)
        return []
    source_scope = {
        SearchScope.FAVORITES: NavigationScope.FAVORITES,
        SearchScope.QUEUE: NavigationScope.QUEUE,
        SearchScope.PLAYLIST: NavigationScope.PLAYLIST,
    }.get(request.scope, NavigationScope.RESULTS)
    navigation_entries = tuple(
        NavigationEntry(
            media=by_position[position]['media'],
            stable_id=by_position[position]['stable_id'],
            position=position,
            label=by_position[position]['label'],
            source_scope=source_scope,
            occurrence_id=by_position[position].get('queue_id'),
        )
        for position, _search_text in results
    )
    search_context = NavigationContext(
        NavigationScope.RESULTS,
        navigation_entries,
        -1,
        f'{_search_scope_description(request)} results',
    )
    _remember_navigation_context(search_context, search=True)
    if request.action in {SearchAction.FIRST, SearchAction.INDEXED}:
        result_index = request.result_index or 1
        if len(results) < result_index:
            raise ValueError(
                f'Search found only {len(results)} match{("es" if len(results) != 1 else "")}; '
                f'result {result_index} is unavailable'
            )
        _play_scoped_search_entry(by_position[results[result_index - 1][0]], request)
        selected_context = search_context.at(result_index - 1)
        _remember_navigation_context(selected_context, search=True)
        _remember_navigation_context(selected_context)
    elif request.action == SearchAction.RANDOM:
        playable = [
            result
            for result in results
            if by_position[result[0]]['media'] is not None
            and not _is_media_blocked(by_position[result[0]]['media'])
        ]
        if not playable:
            raise ValueError('No playable search result is available; unblock an item first')
        selected = rand.choice(playable)
        _play_scoped_search_entry(by_position[selected[0]], request)
        selected_context = search_context.at(results.index(selected))
        _remember_navigation_context(selected_context, search=True)
        _remember_navigation_context(selected_context)
    else:
        marked_results = []
        for position, _search_text in results:
            entry = by_position[position]
            media = entry['media']
            size, media_type = _media_listing_fields(media)
            marked_results.append((
                position,
                _active_media_marker(media),
                _blocked_label(entry['label'], media) if media is not None else entry['label'],
                *_preference_markers(media),
                size,
                media_type,
            ))
        IPrint(
            f'Found {len(results)} match{("es" if len(results) != 1 else "")} in '
            f'{_search_scope_description(request)}: {" ".join(request.query)}',
            visible=visible,
        )
        IPrint(
            tbl(
                marked_results,
                tablefmt='mysql',
                headers=('#', 'Now', 'Media', 'Fav', 'Rating', 'Size', 'Media format'),
            ),
            visible=visible,
        )
    return [(position, by_position[position]['label']) for position, _search_text in results]


def advanced_search_command(tokens):
    request = parse_search(tokens)
    if request.scope != SearchScope.LIBRARY:
        return _advanced_scoped_search(request)
    results = search_rows(_sound_files_names_enumerated, request)
    if not results:
        IPrint(colored.fg('hot_pink_1a') + '-- No results found --' + colored.attr('reset'), visible=visible)
        return []
    navigation_entries = tuple(
        NavigationEntry(
            media=(media := _library_media(index)),
            stable_id=media.stable_id,
            position=index,
            label=title,
            source_scope=NavigationScope.LIBRARY,
            occurrence_id=index,
        )
        for index, title in results
    )
    search_context = NavigationContext(
        NavigationScope.RESULTS,
        navigation_entries,
        -1,
        'library results',
    )
    _remember_navigation_context(search_context, search=True)
    marked_results = []
    for index, title in results:
        media = _library_media(index)
        size, media_type = _media_listing_fields(media)
        marked_results.append((
            index,
            _active_media_marker(media),
            _blocked_label(title, media),
            *_preference_markers(media),
            size,
            media_type,
        ))
    if request.action in {SearchAction.FIRST, SearchAction.INDEXED}:
        result_index = request.result_index or 1
        if len(results) < result_index:
            raise ValueError(
                f'Search found only {len(results)} match{("es" if len(results) != 1 else "")}; '
                f'result {result_index} is unavailable'
            )
        _play_navigation_entry(navigation_entries[result_index - 1])
        selected_context = search_context.at(result_index - 1)
        _remember_navigation_context(selected_context, search=True)
        _remember_navigation_context(selected_context)
    elif request.action == SearchAction.RANDOM:
        playable = [result for result in results if not _is_media_blocked(_library_media(result[0]))]
        if not playable:
            raise ValueError('No playable search result is available; unblock an item first')
        selected = rand.choice(playable)
        local_play_commands([None, str(selected[0])])
        selected_context = search_context.at(results.index(selected))
        _remember_navigation_context(selected_context, search=True)
        _remember_navigation_context(selected_context)
    else:
        IPrint(
            f'Found {len(results)} match{("es" if len(results) != 1 else "")}: '
            f'{" ".join(request.query)}',
            visible=visible,
        )
        IPrint(
            tbl(
                marked_results,
                tablefmt='mysql',
                headers=('#', 'Now', 'Song', 'Fav', 'Rating', 'Size', 'Media format'),
            ),
            visible=visible,
        )
    return results


def edit_current_lyrics(*, assume_yes=False):
    global DEFAULT_EDITOR
    media = _preference_media(vas.controller.snapshot().media)
    if not media or media.source != MediaSource.LOCAL:
        raise ValueError('Lyrics can be edited only for a currently loaded local file')
    source = Path(media.original_uri)
    if not source.is_file():
        raise ValueError('The current local media file is unavailable')
    sidecar = source.with_suffix('.lrc')
    if not sidecar.exists():
        try:
            output_target = bind_output_target(sidecar)
        except OutputTargetError as error:
            raise ValueError('Lyrics sidecar destination is unsafe') from error
        if output_target.existed:
            raise ValueError('Lyrics sidecar appeared while preparing the edit; retry the command')
        identity = IDENTITY.identify(media, pcm=vas.controller.fingerprint_pcm())
        result = IDENTITY.lyrics(media, identity)
        content = result.synced or result.plain
        if not content:
            raise ValueError('No lyrics are available to create an LRC sidecar')
        if not _confirm_action(f'Create adjacent lyrics file "{sidecar}"?', assume_yes=assume_yes):
            IPrint('Lyrics edit cancelled', visible=visible)
            return None
        descriptor, temporary_name = tempfile.mkstemp(prefix=f'.{sidecar.name}.', dir=sidecar.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                stream.write(content.rstrip() + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            try:
                output_target.activate(temporary)
            except OutputTargetError as error:
                raise ValueError(str(error)) from error
        finally:
            temporary.unlink(missing_ok=True)
    if DEFAULT_EDITOR:
        sp.Popen([DEFAULT_EDITOR, str(sidecar)], shell=False)
    else:
        open_path(sidecar)
    return sidecar


def recycle_library_media(arguments):
    if not arguments:
        raise MediaRemovalError('Usage: rm|del <library-index|indexed-path> [y|yes|--yes]')
    yes, values = _confirmation_bypass(arguments, preserve_single_bare=True)
    if not values:
        raise MediaRemovalError('Usage: rm|del <library-index|indexed-path> [y|yes|--yes]')
    reference = ' '.join(values)
    if reference.isdigit():
        display_index = int(reference)
        if display_index < 1 or display_index > len(_sound_files):
            raise MediaRemovalError(f'Library index must be between 1 and {len(_sound_files)}')
        target = MEDIA_REMOVAL.resolve(_sound_files[display_index - 1])
        if target.display_index != display_index:
            raise MediaRemovalError('Library index changed; run the numeric lookup again')
    else:
        target = MEDIA_REMOVAL.resolve(reference)
    position = f'Library #{target.display_index}' if target.display_index is not None else 'Indexed library item'
    if not _confirm_action(
        f'Move {position} | "{target.title}" to the operating-system trash?\n'
        f'Library ID: {target.library_id}\nPath: "{target.path}"',
        assume_yes=yes,
    ):
        IPrint('Media removal cancelled', visible=visible)
        return None
    removed = MEDIA_REMOVAL.remove(target)
    reload_sounds(quick_load=True)
    IPrint(f'Moved to trash: {removed.path}', visible=visible)
    return removed


HELP_GROUPS = (
    ('Getting started', 'help <topic>, all, ls, <number>, now, progress'),
    ('Playback', 'play <number>, pause, stop, next, prev, mute, volume, autonext, loop status/once/infinite/off, reset, .reset, restart'),
    ('Seek and fade', 'seek <time>, fade in/out, fade to <volume>, fade from <v1> to <v2>'),
    ('Video and captions', 'play <number|path|current> --audio|--video|--auto, captions status/tracks/select/auto/language/load/replace/on/off/clear/offset/shift, avsync status/set/shift/reset, chapters list/current/show/find/goto/next/prev/first/last/restart/help'),
    ('Queue', 'queue list/tree/add/insert/remove/move/jump/order/repeat/reset, queue ys|youtube'),
    ('Search and online sources', 'find/rfind/lfind, /ys, /yl, /ml, album, station, pod/pods, /rss'),
    ('Downloads', 'dl [y|yes|--yes], download-yv|dl-yv, download-ya|dl-ya, download-ml|dl-ml'),
    (
        'Library',
        'library roots/status/scan/info/verify, reload, rename short, block/unblock, region/regions',
    ),
    ('Playlists', 'playlist list/create/show/add/remove/move/order/play/queue/import/export; transfer copy/move'),
    ('Tags', 'tag help/list/create/attach/detach/show/rename/delete/find/play/queue/group'),
    ('Lyrics', 'lyrics|lyr, lyrics edit|lyr edit, open lyrics'),
    ('Radio', 'radio search/list/play/add/info/metadata/resync/health/leveling'),
    ('Discord Presence', 'discord presence off/app/track/session/status/refresh'),
    ('Settings', 'theme, desktop close, autoplay|autonext, sleep, youtube auth, replaygain, output device, eq status/on/off/band/preamp/reset/preset, hotspots status/enable/disable/retention/logging/clear/current'),
    (
        'Diagnostics',
        'now, progress, media info/probe/fingerprint/identify/local-match, tools/setup/library status, check_dev',
    ),
    (
        'Dangerous/destructive commands',
        'rm|del, playlist delete/clear, queue clear, library clean, setup restart [y|yes|--yes]',
    ),
)

HELP_EXAMPLES = {
    'Getting started': ('all', '1', 'now', 'help playback'),
    'Playback': ('play 4', 'p', '+', 'autonext on', 'loop once', 'reset', '.reset', 'restart'),
    'Seek and fade': ('seek +30s', 'seek 50%', 'fade out 10', 'fade from 20 to 80 in 6'),
    'Video and captions': ('play current --audio', '/ys "concert" 5 --video', 'captions tracks', 'captions select 2', 'captions load "movie.srt"', 'captions shift +250', 'avsync shift -100', 'chapters next', '.chapter 3'),
    'Queue': ('queue add 4', 'queue ys "artist title" 5', '/ysq "artist title"', 'queue next'),
    'Search and online sources': ('find artist title 10', '/ys artist title 5', '/yl <YouTube URL>', '/ml <URL>'),
    'Downloads': ('dl', 'dl --yes', 'download-ya current --yes', 'download-ml <URL> mp3', 'download-ya status'),
    'Library': ('library status', 'library scan changed', 'block 4', 'region show 4', 'regions'),
    'Playlists': (
        'playlist list', 'playlist create "Road trip"', 'playlist add "Road trip" media 4 7',
        'transfer copy to playlist "Road trip" from favs items 1-3 --dry-run',
        'transfer move to favs from playlist "Road trip" items all',
    ),
    'Tags': (
        'tag help', 'tag attach current "Late night"', 'tag find --all ambient --not live',
        'tag play 1', 'tag queue 2', 'tag group create Mood',
    ),
    'Lyrics': ('lyrics', 'lyrics edit', 'open lyrics'),
    'Radio': ('radio search jazz', 'radio list', 'radio play 1', 'radio metadata'),
    'Discord Presence': ('discord presence status', 'discord presence track', 'discord presence off'),
    'Settings': ('theme list', 'desktop close status', 'autonext status', 'sleep 30m pause fade 5m', 'eq band 1khz 3', 'eq preset save "Quiet listening"'),
    'Diagnostics': ('now', 'tools status', 'library verify', 'media probe current', 'media local-match current'),
    'Dangerous/destructive commands': ('rm 4', 'playlist delete "Road trip" --yes', 'exit y'),
}

HELP_TOPIC_ALIASES = {
    'tag': 'Tags',
    'transfer': 'Playlists',
    'online': 'Search and online sources',
    'video': 'Video and captions',
    'captions': 'Video and captions',
    'avsync': 'Video and captions',
    'chapters': 'Video and captions',
    'details': 'Diagnostics',
    'app': 'Settings',
    'hotspots': 'Settings',
}


def eq_command(arguments):
    """Inspect or change local-listening EQ through the same service as desktop."""
    intent = equalizer_command_intent(arguments)
    try:
        status = EQUALIZER.apply(intent) if intent else EQUALIZER.status()
    except OSError:
        raise ValueError('Could not save equalizer settings') from None
    DESKTOP_CONTROL.emit('equalizer', status)
    IPrint(f'Equalizer: {"enabled" if status["enabled"] else "bypassed"}; '
           f'preamp {status["preamp"]:+g} dB; local output only', visible=visible)
    IPrint(tbl(zip(status['frequencies'], status['bands']), headers=('Hz', 'dB')), visible=visible)
    IPrint(f'Conservative preamp suggestion: {status["recommended_preamp"]:g} dB (not automatic); '
           f'overload blocks since reset: {status["overload_blocks"]}', visible=visible)
    if status['fault'] or status['warning']:
        IPrint(status['warning'] or 'EQ processing unavailable; playback bypassed', visible=visible)
    if arguments == ['preset', 'list']:
        IPrint(tbl([(row['name'], 'Factory' if row['factory'] else 'User') for row in status['presets']],
                   headers=('Preset', 'Origin')), visible=visible)
    return status


def _persist_playback_event_configuration(
    *,
    enabled: bool | None = None,
    retention_days: int | None = None,
    forward_to_log: bool | None = None,
):
    """Persist local event-capture controls before publishing live changes."""
    if enabled is not None and type(enabled) is not bool:
        raise ValueError('Hotspot capture setting must be true or false')
    if forward_to_log is not None and type(forward_to_log) is not bool:
        raise ValueError('Hotspot log forwarding must be true or false')
    if retention_days is not None and (
        isinstance(retention_days, bool)
        or not isinstance(retention_days, int)
        or not 1 <= retention_days <= 3650
    ):
        raise ValueError('Hotspot retention must be between 1 and 3650 days')
    with _SETTINGS_WRITE_LOCK:
        previous_present = 'playback events' in SETTINGS
        previous_section = SETTINGS.get('playback events')
        section = dict(previous_section) if isinstance(previous_section, dict) else {}
        if enabled is not None:
            section['enabled'] = enabled
        if retention_days is not None:
            section['retention days'] = retention_days
        if forward_to_log is not None:
            section['forward to log'] = forward_to_log
        SETTINGS['playback events'] = section
        try:
            save_user_settings(SETTINGS, RUNTIME_PATHS.settings)
        except Exception:
            if previous_present:
                SETTINGS['playback events'] = previous_section
            else:
                SETTINGS.pop('playback events', None)
            raise
        PLAYBACK_EVENTS.configure(
            enabled=enabled,
            retention_days=retention_days,
            forward_to_log=forward_to_log,
        )
    return PLAYBACK_EVENTS.status()


def hotspots_command(arguments):
    """Control and inspect local personal interaction hotspot capture."""
    normalized = [value.casefold() for value in arguments]
    operation = normalized[0] if normalized else 'status'
    if not normalized or normalized == ['status']:
        status = PLAYBACK_EVENTS.status()
        IPrint(
            f'Personal interaction hotspots: {"enabled" if status["enabled"] else "disabled"}; '
            f'retention {status["retention_days"]} days; stored {status["stored"]}; '
            f'pending {status["pending"]}/{status["capacity"]}; dropped {status["dropped"]}; '
            f'log forwarding {"on" if status["forward_to_log"] else "off"}',
            visible=visible,
        )
        return status
    if len(normalized) == 1 and operation in {'enable', 'disable'}:
        status = _persist_playback_event_configuration(enabled=operation == 'enable')
        IPrint(f'Personal interaction hotspot capture {operation}d.', visible=visible)
        return status
    if len(normalized) == 2 and operation == 'retention':
        try:
            days = int(normalized[1])
        except ValueError:
            raise ValueError('Hotspot retention must be a whole number of days') from None
        status = _persist_playback_event_configuration(retention_days=days)
        IPrint(f'Personal interaction hotspot retention set to {days} days.', visible=visible)
        return status
    if len(normalized) == 2 and operation == 'logging' and normalized[1] in {'on', 'off'}:
        status = _persist_playback_event_configuration(forward_to_log=normalized[1] == 'on')
        IPrint(f'Playback-event log forwarding {normalized[1]}.', visible=visible)
        return status
    if normalized == ['clear', '--yes']:
        if not PLAYBACK_EVENTS.clear():
            raise ValueError('Could not clear personal interaction hotspot history')
        IPrint('Personal interaction hotspot history cleared.', visible=visible)
        return PLAYBACK_EVENTS.status()
    if operation == 'clear':
        raise ValueError('Clearing personal interaction hotspot history requires: hotspots clear --yes')
    if operation == 'current':
        if len(normalized) > 3:
            raise ValueError('Usage: hotspots current [bin-seconds] [linear|log1p]')
        snapshot = vas.controller.snapshot()
        if snapshot.media is None:
            raise ValueError('No media is currently active')
        try:
            bin_seconds = float(normalized[1]) if len(normalized) >= 2 else 10.0
        except ValueError:
            raise ValueError('Hotspot bin width must be a positive number') from None
        raw_scaling = normalized[2] if len(normalized) == 3 else 'linear'
        if raw_scaling not in {'linear', 'log1p'}:
            raise ValueError('Hotspot scaling must be linear or log1p')
        scaling: Scaling = 'log1p' if raw_scaling == 'log1p' else 'linear'
        rows = PLAYBACK_EVENTS.aggregate(
            snapshot.media.stable_id,
            bin_seconds=bin_seconds,
            scaling=scaling,
        )
        IPrint('Personal interaction hotspots (local user actions only)', visible=visible)
        IPrint(
            tbl(
                [
                    (
                        _status_time(row['start_seconds']),
                        row['play_starts'],
                        row['play_resumes'],
                        row['pauses'],
                        row['seek_destinations'],
                        f'{row["intensity"]:.3f}',
                    )
                    for row in rows
                ],
                headers=('Position', 'Starts', 'Resumes', 'Pauses', 'Seek destinations', 'Intensity'),
                tablefmt='plain',
            ),
            visible=visible,
        )
        return rows
    raise ValueError(
        'Usage: hotspots [status|enable|disable|retention DAYS|logging on|logging off|'
        'clear --yes|current [bin-seconds] [linear|log1p]]'
    )


def loop_command(arguments):
    """Inspect or configure finite current-media looping."""
    operation = arguments[0].casefold() if arguments else 'status'
    operation = {
        '1': 'once',
        'on': 'infinite',
        'forever': 'infinite',
    }.get(operation, operation)
    if len(arguments) > 1 or operation not in {'status', 'once', 'infinite', 'off'}:
        raise ValueError('Usage: loop [status|once|infinite|off]')

    if operation == 'off':
        _set_loop_override()
        if QUEUE.state().get('repeat_mode') == 'one':
            QUEUE.set_repeat('off')
    elif operation in {'once', 'infinite'}:
        snapshot = vas.controller.snapshot()
        media = snapshot.media
        if media is None or snapshot.state in {PlaybackState.IDLE, PlaybackState.FAILED}:
            raise ValueError('No current media is available to loop')
        if not media.capabilities.finite or media.capabilities.live:
            raise ValueError('Looping requires finite media; live streams cannot be looped')
        if operation == 'once' and QUEUE.state().get('repeat_mode') == 'one':
            QUEUE.set_repeat('off')
        elif operation == 'infinite':
            QUEUE.set_repeat('one')
        _set_loop_override(operation, media)

    if operation != 'status':
        vas.controller.clear_prefetch()
    status = _loop_status()
    if status['mode'] == 'once':
        message = f"Loop: once; one replay remaining for {status['title']}"
    elif status['mode'] == 'infinite':
        message = f"Loop: infinite for {status['title']}"
    else:
        suffix = ' (queue repeat-all remains active)' if status['queue_repeat'] == 'all' else ''
        message = f'Loop: off{suffix}'
    IPrint(message, visible=visible)
    _emit_queue_desktop_state()
    return status


def restart_command(arguments):
    """Seek to the persisted preferred start without changing play/pause state."""
    if arguments:
        raise ValueError('Usage: restart')
    snapshot = vas.controller.snapshot()
    if snapshot.media is None:
        if not currentsong_length or currentsong_length == -1:
            raise ValueError('No finite audio is available to restart')
    elif (
        not snapshot.media.capabilities.finite or snapshot.media.capabilities.live
        or not snapshot.media.capabilities.seekable
    ):
        raise ValueError('No finite audio is available to restart')
    region = PLAY_REGIONS.get(snapshot.media) if snapshot.media is not None else None
    target = region.start_seconds if region is not None and region.start_seconds is not None else 0.0
    if not song_seek(timeval=target):
        raise ValueError('The current source rejected the restart seek')
    _sync_legacy_playback_state()
    return target


def help_command(arguments):
    """Display the command map, optionally narrowed to one documented category."""
    topic = ' '.join(arguments).casefold().strip() if arguments else None
    if topic == 'region':
        return region_command(['help'])
    rows = HELP_GROUPS
    if topic and topic not in {'all', 'full'}:
        aliased_topic = HELP_TOPIC_ALIASES.get(topic, topic)
        exact_rows = tuple(row for row in HELP_GROUPS if row[0].casefold() == aliased_topic.casefold())
        rows = exact_rows or tuple(row for row in HELP_GROUPS if row[0].casefold().startswith(aliased_topic))
        if not rows:
            raise ValueError(f'Unknown help topic: {topic}')
    IPrint(tbl(rows, headers=('Commands', 'Common forms'), tablefmt='plain'), visible=visible)
    if len(rows) == 1:
        examples = ', '.join(HELP_EXAMPLES.get(rows[0][0], ()))
        if examples:
            IPrint(f'Examples: {examples}', visible=visible)
    IPrint("Use 'help <topic>' to narrow this list; help.md and README.md document every command family.", visible=visible)
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
    status = DISCORD_PRESENCE.status()
    message = f'Discord presence mode set to {selected.value}.'
    if selected != PresencePrivacyMode.OFF and status.failure_code == DiscordPresenceFailureCode.NOT_CONFIGURED:
        message += f' {status.message}'
    IPrint(message, visible=visible)
    return selected


def _persist_homepage_configuration(
    *,
    show_on_startup: bool | None = None,
    online_enabled: bool | None = None,
):
    """Persist independent homepage settings and update the live service atomically."""
    if show_on_startup is not None and type(show_on_startup) is not bool:
        raise ValueError('Homepage startup setting must be true or false')
    if online_enabled is not None and type(online_enabled) is not bool:
        raise ValueError('Homepage online setting must be true or false')
    with _SETTINGS_WRITE_LOCK:
        previous_present = 'homepage' in SETTINGS
        previous_section = SETTINGS.get('homepage')
        section = dict(previous_section) if isinstance(previous_section, dict) else {}
        SETTINGS['homepage'] = section
        if show_on_startup is not None:
            section['show on startup'] = show_on_startup
        if online_enabled is not None:
            section['online content'] = online_enabled
        try:
            save_user_settings(SETTINGS, RUNTIME_PATHS.settings)
        except Exception:
            if previous_present:
                SETTINGS['homepage'] = previous_section
            else:
                SETTINGS.pop('homepage', None)
            previous = _configured_homepage(SETTINGS)
            HOMEPAGE.configure(
                show_on_startup=previous.show_on_startup,
                online_enabled=previous.online_enabled,
            )
            raise
        projection = HOMEPAGE.configure(
            show_on_startup=show_on_startup,
            online_enabled=online_enabled,
        )
        if online_enabled:
            HOMEPAGE.refresh_async()
        return projection


def _print_homepage(projection):
    state = projection['state']
    IPrint(
        f'Mariana Home | startup={"on" if projection["show_on_startup"] else "off"} | '
        f'online={"on" if projection["online_enabled"] else "off"} | {state}',
        visible=visible,
    )
    if projection.get('safe_message'):
        IPrint(projection['safe_message'], visible=visible)
    for section in projection['sections']:
        IPrint(f'\n{section["title"]}', visible=visible)
        if not section['items']:
            IPrint('  Nothing to show yet.', visible=visible)
            continue
        rows = [
            (
                item['title'],
                item['source'],
                item.get('published_at') or '',
            )
            for item in section['items']
        ]
        IPrint(tbl(rows, headers=('Title', 'Source', 'Published'), tablefmt='plain'), visible=visible)
        for item in section['items']:
            if item.get('summary'):
                IPrint(f'  {item["title"]}: {item["summary"]}', visible=visible)
            if item.get('link'):
                IPrint(f'  Original: {item["link"]}', visible=visible)


def home_command(arguments):
    """Show/configure the local-first homepage without conflating network consent."""
    normalized = [value.casefold() for value in arguments]
    if not normalized:
        projection = HOMEPAGE.snapshot()
        DESKTOP_CONTROL.emit('homepage', {**projection, 'open_requested': True})
        _print_homepage(projection)
        return projection
    if normalized in (['status'], ['current']):
        projection = HOMEPAGE.snapshot()
        IPrint(
            f'Homepage on startup: {"enabled" if projection["show_on_startup"] else "disabled"}; '
            f'online discovery: {"enabled" if projection["online_enabled"] else "disabled"}; '
            f'state: {projection["state"]}',
            visible=visible,
        )
        return projection
    if len(normalized) == 1 and normalized[0] in {'enable', 'disable'}:
        enabled = normalized[0] == 'enable'
        projection = _persist_homepage_configuration(show_on_startup=enabled)
        IPrint(f'Homepage on startup {"enabled" if enabled else "disabled"}.', visible=visible)
        return projection
    if (
        len(normalized) == 2
        and normalized[0] == 'online'
        and normalized[1] in {'enable', 'disable', 'on', 'off'}
    ):
        enabled = normalized[1] in {'enable', 'on'}
        projection = _persist_homepage_configuration(online_enabled=enabled)
        IPrint(f'Online homepage discovery {"enabled" if enabled else "disabled"}.', visible=visible)
        return projection
    if normalized == ['refresh']:
        if not HOMEPAGE.snapshot()['online_enabled']:
            raise ValueError('Online discovery is disabled; use "home online enable" first')
        if not HOMEPAGE.refresh_async():
            raise ValueError('Homepage refresh is unavailable')
        IPrint('Homepage discovery refresh started in the background.', visible=visible)
        return HOMEPAGE.snapshot()
    raise ValueError(
        'Usage: home [status|enable|disable|refresh|online enable|online disable]'
    )


def _persist_artwork_configuration(enabled: bool):
    """Persist automatic network-artwork consent, rolling back on write failure."""
    if type(enabled) is not bool:
        raise ValueError('Artwork setting must be true or false')
    with _SETTINGS_WRITE_LOCK:
        previous_present = 'artwork' in SETTINGS
        previous_section = SETTINGS.get('artwork')
        section = dict(previous_section) if isinstance(previous_section, dict) else {}
        previous_enabled = _configured_automatic_artwork(SETTINGS)
        SETTINGS['artwork'] = section
        section['automatic online retrieval'] = enabled
        try:
            save_user_settings(SETTINGS, RUNTIME_PATHS.settings)
        except Exception:
            if previous_present:
                SETTINGS['artwork'] = previous_section
            else:
                SETTINGS.pop('artwork', None)
            ARTWORK.set_automatic_online(previous_enabled)
            raise
        ARTWORK.set_automatic_online(enabled)
        return ARTWORK.projection()


def _show_current_artwork(
    *,
    fetch: bool,
    desktop: bool,
    expected_media_id: str | None = None,
):
    snapshot = vas.controller.snapshot()
    if snapshot.media is None:
        raise ValueError('No media is currently active')
    if expected_media_id is not None and snapshot.media.stable_id != expected_media_id:
        raise ValueError('Current media changed; try again')
    expected_media_id = snapshot.media.stable_id
    projection = ARTWORK.projection()
    if projection.media_id != expected_media_id:
        raise ValueError('Current media changed; try again')
    if fetch and ARTWORK.fetch_current(expected_media_id) is None:
        raise ValueError('Current media has no supported provider artwork to fetch')
    projection = ARTWORK.projection()
    if projection.media_id != expected_media_id:
        raise ValueError('Current media changed; try again')
    current_media = vas.controller.snapshot().media
    if current_media is None or current_media.stable_id != expected_media_id:
        raise ValueError('Current media changed; try again')
    if desktop:
        DESKTOP_CONTROL.emit('artwork', {**projection.to_dict(), 'show_requested': True})
        return projection
    if projection.state == ArtworkState.LOADING:
        projection = ARTWORK.wait_for_idle(timeout=12.0 if fetch else 2.0)
    current_media = vas.controller.snapshot().media
    if projection.media_id != expected_media_id or current_media is None or current_media.stable_id != expected_media_id:
        raise ValueError('Current media changed; try again')
    image = ARTWORK.current_image(projection.cache_key)
    if image is None:
        if projection.state == ArtworkState.LOADING:
            IPrint('Artwork is still loading; run "thumb show" again shortly.', visible=visible)
            return projection
        raise ValueError(projection.unavailable_reason or 'No supported artwork is available')
    current_media = vas.controller.snapshot().media
    current_projection = ARTWORK.projection()
    if (
        current_media is None or current_media.stable_id != expected_media_id
        or current_projection.media_id != expected_media_id
        or current_projection.cache_key != image.cache_key
    ):
        raise ValueError('Current media changed; try again')
    try:
        open_path(image.path)
    except (OSError, PlatformCapabilityError) as error:
        raise ValueError('Artwork viewer is unavailable on this system') from error
    IPrint('Opened current media artwork.', visible=visible)
    return projection


def thumb_command(arguments):
    """Configure and display identity-bound current-media artwork."""
    normalized = [value.casefold() for value in arguments]
    if not normalized or normalized in (['status'], ['current']):
        projection = ARTWORK.projection()
        availability = projection.state.value
        IPrint(
            f'Automatic online artwork: {"enabled" if projection.automatic_online else "disabled"}; '
            f'current artwork: {availability}',
            visible=visible,
        )
        return projection
    if len(normalized) == 1 and normalized[0] in {'enable', 'disable'}:
        enabled = normalized[0] == 'enable'
        projection = _persist_artwork_configuration(enabled)
        IPrint(f'Automatic online artwork {"enabled" if enabled else "disabled"}.', visible=visible)
        return projection
    if normalized == ['show']:
        return _show_current_artwork(
            fetch=False,
            desktop=bool(getattr(DESKTOP_CONTROL, 'enabled', False)),
        )
    if normalized == ['show', '--fetch']:
        return _show_current_artwork(
            fetch=True,
            desktop=bool(getattr(DESKTOP_CONTROL, 'enabled', False)),
        )
    raise ValueError('Usage: thumb [status|enable|disable|show [--fetch]]')


THEME_PRESETS = {
    'aurora': 'Mariana Aurora',
    'windows': 'Windows Terminal Acrylic',
    'kitty': 'Kitty / Catppuccin',
    'gruvbox': 'Gruvbox Dark',
}


def theme_command(arguments):
    with _SETTINGS_WRITE_LOCK:
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
    with _SETTINGS_WRITE_LOCK:
        appearance = SETTINGS.setdefault('appearance', {})
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


def desktop_command(arguments):
    normalized = [value.casefold() for value in arguments]
    if not normalized or normalized == ['close']:
        operation = 'status'
    elif len(normalized) == 2 and normalized[0] == 'close':
        operation = normalized[1]
    else:
        raise ValueError('Usage: desktop close [tray|quit|status]')
    current = _configured_desktop_close_behavior(SETTINGS)
    if operation in {'status', 'current'}:
        IPrint(f'Desktop close button: {current}', visible=visible)
        return current
    if operation not in {'tray', 'quit'}:
        raise ValueError('Usage: desktop close [tray|quit|status]')
    previous_section = SETTINGS.get('desktop')
    desktop_settings = previous_section if isinstance(previous_section, dict) else {}
    SETTINGS['desktop'] = desktop_settings
    previous = desktop_settings.get('close button')
    desktop_settings['close button'] = operation
    try:
        save_user_settings(SETTINGS, RUNTIME_PATHS.settings)
    except Exception:
        if not isinstance(previous_section, dict):
            if previous_section is None:
                SETTINGS.pop('desktop', None)
            else:
                SETTINGS['desktop'] = previous_section
        elif previous is None:
            desktop_settings.pop('close button', None)
        else:
            desktop_settings['close button'] = previous
        raise
    DESKTOP_CONTROL.emit('desktop-preferences', {'close_button_behavior': operation})
    IPrint(f'Desktop close button set to {operation}.', visible=visible)
    return operation


def _media_info_with_fingerprint(media, info):
    if not info.get('fingerprint') and (saved := IDENTITY.saved_fingerprint(media)):
        info['fingerprint_duration'], info['fingerprint'] = saved
    return media, info


def _prepare_fingerprint_tool():
    """Offer existing guided setup only for a genuinely missing/broken tool."""
    def working_tool():
        try:
            executable = find_fpcalc(MEDIA_TOOLS.get('fpcalc bin'))
        except PlaybackError:
            return None
        return executable if executable_version('fpcalc', executable) else None

    executable = working_tool()
    if executable is None:
        IPrint('Chromaprint calculation needs a working fpcalc tool; playback does not.', visible=visible)
        if not _confirm_action('Open guided media-tool setup to install verified tools or select an existing installation?'):
            IPrint("Fingerprint calculation cancelled. Run 'tools setup' whenever you are ready.", visible=visible)
            return False
        try:
            tools_command(['setup'])
        except (ToolchainError, RuntimeError, OSError) as error:
            IPrint(f'Tool setup did not complete: {error}', visible=visible)
            return False
        executable = working_tool()
        if executable is None:
            IPrint('fpcalc is still unavailable; no fingerprint was calculated.', visible=visible)
            return False
    # Refresh only this dependency. Never recreate a playing controller here.
    IDENTITY.fpcalc_bin = executable
    LIBRARY.fpcalc_bin = executable
    return True


def _media_fingerprint(media, info, *, full=False):
    if media.capabilities.live or not media.capabilities.finite or not media.capabilities.fingerprintable:
        IPrint("Whole-media fingerprints require finite audio.", visible=visible)
        return None
    saved = (info.get('fingerprint_duration'), info.get('fingerprint')) if info.get('fingerprint') else IDENTITY.saved_fingerprint(media)
    if saved is None:
        try:
            pcm = None if media.source == MediaSource.LOCAL else vas.controller.fingerprint_pcm(media_id=media.stable_id)
            if pcm is not None and len(pcm) < MIN_FINGERPRINT_SECONDS * SAMPLE_RATE * BYTES_PER_FRAME:
                IPrint(f'At least {MIN_FINGERPRINT_SECONDS} seconds of decoded audio are needed; let this item play, then retry media fingerprint.', visible=visible)
                return None
            if not _prepare_fingerprint_tool():
                return None
            IPrint('Calculating Chromaprint locally; this does not contact a recognition provider or change playback.', visible=visible)
            saved = IDENTITY.calculate_fingerprint(media, pcm=pcm)
        except (IdentificationError, PlaybackError, OSError) as error:
            IPrint(f'Fingerprint unavailable: {error}', visible=visible)
            return None
    duration, fingerprint = saved
    value = str(fingerprint) if full else f'{len(str(fingerprint))} characters'
    IPrint(f'Chromaprint ({duration or "unknown"} s): {value}', visible=visible)
    return fingerprint


def _media_info(arguments):
    snapshot = vas.controller.snapshot()
    target = ' '.join(arguments).strip()
    media = snapshot.media
    relative = parse_relative_reference(target)
    if relative is not None:
        media = _relative_media_reference(relative)
        target = media.original_uri if media.source == MediaSource.LOCAL else ''
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
        return _media_info_with_fingerprint(media, info)
    if media is None:
        raise ValueError('No media is currently active; pass a library index or indexed path')
    if media.source == MediaSource.LOCAL:
        info = LIBRARY.info(media.original_uri)
        if info:
            return _media_info_with_fingerprint(media, info)
    metadata = {
        'source': media.source.value,
        'title': media.title,
        'artist': media.artist,
        'album': media.album,
        'duration': media.duration or (snapshot.duration if media == snapshot.media else None),
        'provenance': media.provenance,
        'stream_title': snapshot.stream_title if media == snapshot.media else None,
    }
    metadata.update(normalized_provider_metadata(media.resolver_data.get('provider_metadata')))
    if media.source == MediaSource.PODCAST:
        librivox_book_id = media.resolver_data.get('librivox_book_id')
        librivox_section_id = media.resolver_data.get('librivox_section_id')
        if librivox_book_id and librivox_section_id:
            metadata.update({
                'provider': 'LibriVox',
                'provider_media_id': str(librivox_section_id),
                'publisher': 'LibriVox',
                'publisher_id': str(librivox_book_id),
            })
        podcast_fields = {
            'description': 'description',
            'published': 'published',
            'explicit': 'explicit',
            'artwork': 'artwork',
        }
        for output_key, resolver_key in podcast_fields.items():
            value = media.resolver_data.get(resolver_key)
            if value not in (None, ''):
                metadata[output_key] = value
    if media.source == MediaSource.URL and not media.title:
        metadata['metadata_note'] = (
            'No trusted title was supplied or found in the stream. Use the original provider page '
            'with /yl or /ml to retain provider metadata; a temporary stream URL may not contain it.'
        )
    info = {
        'library_id': media.stable_id,
        'canonical_path': media.original_uri,
        'state': snapshot.state.value if media == snapshot.media else 'inactive',
        'metadata': metadata,
    }
    return _media_info_with_fingerprint(media, info)


def _adhoc_capture_interval(status):
    start = status.captured_start_seconds
    end = status.captured_end_seconds
    if start is None or end is None:
        return 'waiting for decoded audio'
    return f'{format_region_time(start)} -> {format_region_time(end)}'


def _print_adhoc_identification(status):
    IPrint(
        f'Time-specific identification: {status.phase.value}; '
        f'captured {status.captured_seconds:.1f}/{status.target_seconds:g} seconds; '
        f'interval {_adhoc_capture_interval(status)}',
        visible=visible,
    )
    if status.reason:
        IPrint(status.reason, visible=visible)
    result = status.result
    if result is not None and hasattr(result, 'to_dict'):
        rows = [
            (key.replace('_', ' ').title(), value)
            for key, value in result.to_dict().items()
            if value not in (None, '', [], {})
        ]
        IPrint(tbl(rows, tablefmt='plain'), visible=visible)


def _adhoc_identification_update(status):
    if status.phase in {CapturePhase.COMPLETE, CapturePhase.FAILED}:
        _print_adhoc_identification(status)


def _adhoc_identification_command(arguments):
    action = arguments[0].casefold() if arguments else 'listen'
    if action in {'listen', 'start'}:
        if len(arguments) > 2:
            raise AdHocIdentificationError(
                'Usage: media identify listen [seconds] | status | stop | cancel'
            )
        try:
            duration = float(arguments[1]) if len(arguments) == 2 else DEFAULT_CAPTURE_SECONDS
        except (TypeError, ValueError, OverflowError) as error:
            raise AdHocIdentificationError('Capture duration must be a number of seconds') from error
        if not math.isfinite(duration) or not MIN_CAPTURE_SECONDS <= duration <= MAX_CAPTURE_SECONDS:
            raise AdHocIdentificationError(
                f'Capture duration must be between {MIN_CAPTURE_SECONDS:g} and {MAX_CAPTURE_SECONDS:g} seconds'
            )
        if ADHOC_IDENTIFICATION.status().phase in {CapturePhase.CAPTURING, CapturePhase.IDENTIFYING}:
            raise AdHocIdentificationError('A time-specific identification is already active')
        media, session_id, decoder_token, _position = vas.controller.identification_capture_context()
        invocation_identity = (media.stable_id, session_id, decoder_token)
        if not _prepare_fingerprint_tool():
            IPrint('Time-specific identification cancelled; no audio was captured.', visible=visible)
            return None
        # Setup may take time while playback continues. Never capture against
        # the position or source that preceded a confirmation dialog.
        media, session_id, decoder_token, position = vas.controller.identification_capture_context()
        if (media.stable_id, session_id, decoder_token) != invocation_identity:
            raise AdHocIdentificationError('Playback changed during identification setup; retry the command')
        status = ADHOC_IDENTIFICATION.start(
            media,
            session_id,
            decoder_token,
            position,
            duration,
        )
        IPrint(
            f'Listening to newly played audio for {status.target_seconds:g} seconds from '
            f'{format_region_time(position)}. Playback may continue normally.',
            visible=visible,
        )
        return status
    if len(arguments) != 1 or action not in {'status', 'stop', 'cancel'}:
        raise AdHocIdentificationError(
            'Usage: media identify listen [seconds] | status | stop | cancel'
        )
    if action == 'status':
        status = ADHOC_IDENTIFICATION.status()
    elif action == 'stop':
        status = ADHOC_IDENTIFICATION.stop()
    else:
        status = ADHOC_IDENTIFICATION.cancel()
    _print_adhoc_identification(status)
    return status


def media_command(arguments):
    operation = arguments[0].casefold() if arguments else 'info'
    if operation == 'identify' and len(arguments) >= 2 and arguments[1].casefold() in {
        'listen', 'start', 'status', 'stop', 'cancel',
    }:
        return _adhoc_identification_command(arguments[1:])
    if operation == 'local-match':
        if len(arguments) != 2 or arguments[1].casefold() != 'current':
            raise ValueError('Usage: media local-match current')
        snapshot = vas.controller.snapshot()
        result = LOCAL_MATCHER.match(_media_for_local_match(snapshot.media))
        if result.status == LocalMatchStatus.MATCHED:
            label = ' - '.join(value for value in (result.artist, result.title) if value)
            IPrint(
                f'Local copy found: library item {result.library_index} - {label or "Local media"}',
                visible=visible,
            )
            confidence = result.confidence.value if result.confidence else 'Strong match'
            IPrint(f'Confidence: {confidence}', visible=visible)
            IPrint(f'Use "path {result.library_index}" to reveal its local path.', visible=visible)
        elif result.status == LocalMatchStatus.AMBIGUOUS:
            IPrint('Multiple strong local candidates exist; no match was selected.', visible=visible)
        elif result.status == LocalMatchStatus.UNSUPPORTED:
            IPrint('Local matching requires finite online media.', visible=visible)
        else:
            IPrint('No strong indexed local match was found.', visible=visible)
        return result
    target_arguments = [value for value in arguments[1:] if value != '--full']
    media, info = _media_info(target_arguments)
    if operation in {'info', 'probe', 'metadata'}:
        rows = flattened_details(info)
        rows.append(('Preferred play region', _region_description(PLAY_REGIONS.get(media))))
        if media.source == MediaSource.LOCAL and Path(media.original_uri).is_file():
            stat = Path(media.original_uri).stat()
            rows.extend((('Filesystem created/changed', time.ctime(stat.st_ctime)),
                         ('Filesystem modified', time.ctime(stat.st_mtime))))
        IPrint(tbl(rows, tablefmt='plain'), visible=visible)
        return info
    if operation == 'fingerprint':
        return _media_fingerprint(media, info, full='--full' in arguments)
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
    raise ValueError(
        'Usage: media [info|probe|metadata|fingerprint|identify] [current|index|path] [--full] '
        '| media local-match current'
    )


def rename_command(arguments):
    global currentsong
    if not arguments or arguments[0].casefold() != 'short':
        raise ValueError(
            'Usage: rename short [current|library-index|indexed-path] [--dry-run] [y|yes|--yes]'
        )
    yes, values = _confirmation_bypass(arguments[1:], preserve_single_bare=True)
    dry_run, values = _command_flag(values, '--dry-run')
    if any(value.startswith('--') for value in values):
        raise ValueError(
            'Usage: rename short [current|library-index|indexed-path] [--dry-run] [y|yes|--yes]'
        )
    if dry_run and yes:
        raise ValueError('Rename dry-run does not accept a confirmation bypass token')
    target = ' '.join(values) or 'current'
    media, info = _media_info([target])
    if media.source != MediaSource.LOCAL or info.get('state') != 'available':
        raise ValueError('Only an available, indexed local media file can be renamed')
    bound_target = LIBRARY.bind_rename(info['library_id'])
    source = Path(info['canonical_path']).resolve()
    if os.path.normcase(os.path.abspath(source)).casefold() != os.path.normcase(
        os.path.abspath(bound_target.path)
    ).casefold():
        raise ValueError('Rename target changed; run the command again')
    source = bound_target.path
    plan = short_filename_plan(source, info.get('metadata') or {})
    if plan.filename is None:
        raise ValueError(plan.reason or 'Insufficient trusted metadata for safe rename.')
    filename = plan.filename
    destination = source.with_name(filename)
    if source.name.casefold() == destination.name.casefold():
        raise ValueError('Current filename already matches the trusted short name.')
    IPrint(
        f'Rename preview:\n  {source.name}\n  -> {destination.name}\n'
        f'Metadata confidence: {plan.confidence} ({plan.source})',
        visible=visible,
    )
    if dry_run:
        return destination
    if not _confirm_action('Apply this rename?', assume_yes=yes):
        IPrint('Rename cancelled', visible=visible)
        return None
    snapshot = vas.controller.snapshot()
    if snapshot.media and snapshot.media.stable_id == media.stable_id:
        stopsong()
    renamed = LIBRARY.rename_bound(bound_target, filename)
    if currentsong and os.path.normcase(os.path.abspath(str(currentsong))).casefold() == os.path.normcase(
        os.path.abspath(str(source))
    ).casefold():
        currentsong = str(renamed)
    reload_sounds(quick_load=True)
    IPrint(f'Renamed: {renamed}', visible=visible)
    return renamed

def get_current_progress():
    return vas.player.get_time() / 1000


def _favorite_status_projection(media: MediaRef | None) -> FavoriteStatusProjection:
    """Project independent hearts and stars without exposing their durable key."""
    if media is None:
        return FavoriteStatusProjection(False, False, False, 'No active media')
    bound = _preference_media(media)
    if bound is None:
        return FavoriteStatusProjection(False, False, False, 'Rating unavailable')
    if bound.source == MediaSource.LOCAL and bound.provenance != 'library':
        return FavoriteStatusProjection(
            False,
            False,
            False,
            'Only indexed local media can be rated',
        )
    if bound.source == MediaSource.URL and bound.provenance == 'user':
        return FavoriteStatusProjection(
            False,
            False,
            False,
            'This online source has no durable rating identity',
        )
    if bound.source == MediaSource.PODCAST and not has_durable_podcast_identity(bound):
        return FavoriteStatusProjection(
            False,
            False,
            False,
            'This podcast episode has no durable rating identity',
        )
    try:
        rating = _media_rating(bound)
        is_favorite = _is_media_favorite(bound)
    except Exception:
        return FavoriteStatusProjection(
            False,
            False,
            False,
            'Rating is temporarily unavailable',
        )
    rating = min(5, max(0, rating))
    return FavoriteStatusProjection(True, is_favorite, True, rating=rating)


def _playback_status_projection() -> PlaybackStatusProjection:
    """Return the safe, authoritative playback projection used by CLI surfaces."""
    snapshot = vas.controller.snapshot()
    stable_id = snapshot.media.stable_id if snapshot.media else None
    queue_position, queue_count = QUEUE.playback_position(stable_id)
    library_index = None
    if snapshot.media is not None and snapshot.media.source == MediaSource.LOCAL:
        candidate = _library_song_index(snapshot.media.original_uri)
        library_index = candidate if isinstance(candidate, int) else None
    blocked = _is_media_blocked(snapshot.media)
    return project_playback_status(
        snapshot,
        library_index=library_index,
        queue_position=queue_position,
        queue_count=queue_count,
        favorite=_favorite_status_projection(snapshot.media),
        policy=PlaybackPolicyProjection(
            blocked=blocked,
            playable=not blocked,
            unavailable_reason='Playback blocked for this media' if blocked else None,
        ),
    )


def _catalogue_choices(identifier, cancelled):
    entry = ENTERTAINMENT_ENTRIES.get(identifier)
    if entry is None or not entry.native or cancelled():
        raise ValueError('Catalogue selection is unavailable')
    if entry.kind == 'programme':
        choices = CATALOGUE_READER.episodes(entry, cancelled)
    elif entry.kind == 'station' and entry.station_id:
        station = RADIO.get(entry.station_id)
        endpoints = RADIO.endpoints(station)
        choices = [MediaRef(
            MediaSource.RADIO, endpoints[0], title=station.name,
            resolver_data={'station_id': station.station_id, 'endpoints': endpoints},
            capabilities=MediaCapabilities(finite=False, live=True, seekable=False, downloadable=False),
        )]
    else:
        raise ValueError('Catalogue selection is unavailable')
    for media in choices:
        media.resolver_data['catalogue_id'] = entry.id
    return choices


def _discovery_unavailable(media: MediaRef) -> str | None:
    if _is_media_blocked(media):
        return 'Playback blocked'
    if media.source == MediaSource.LOCAL:
        info = LIBRARY.info(media.original_uri)
        if (
            not info or info.get('state') != 'available'
            or info.get('library_id') != media.stable_id
            or not Path(media.original_uri).is_file()
        ):
            return 'Local media is unavailable'
    elif media.source in {MediaSource.RADIO, MediaSource.PODCAST}:
        catalogue_id = media.resolver_data.get('catalogue_id')
        entry = ENTERTAINMENT_ENTRIES.get(catalogue_id) if isinstance(catalogue_id, str) else None
        if not entry or not entry.native or ((entry.kind == 'station') != (media.source == MediaSource.RADIO)):
            return 'Unverified catalogue source'
    elif media.source != MediaSource.YOUTUBE:
        return 'Unsupported discovery source'
    return None


def _apply_discovery_selection(media: MediaRef, intent: str) -> None:
    """Apply an explicit bound choice without interpreting CLI command text."""
    if COMMAND_BUSY.is_set() or _discovery_unavailable(media):
        raise ValueError('Selected version is temporarily unavailable')
    _ensure_media_playable(media)
    if intent == 'queue':
        QUEUE.add(media)
        _emit_queue_desktop_state()
    elif intent == 'play':
        # Direct playback leaves the existing queue intact.
        vas.supervisor.play(media, origin='desktop')
        _set_current_media_state(media)
        _record_successful_start(media)
    else:
        raise ValueError('Unsupported discovery action')


def _desktop_control_request(action: str, payload: dict[str, object]) -> dict[str, object]:
    """Apply one allowlisted desktop intent against authoritative backend state."""
    if action in {'discovery.begin', 'discovery.choose', 'discovery.cancel'}:
        request_id = payload.get('request_id')
        if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{32}', request_id):
            return {'ok': False, 'error': 'Release selection request is invalid'}
        try:
            if action == 'discovery.begin':
                item_id = payload.get('item_id')
                if (set(payload) not in ({'request_id', 'item_id'}, {'request_id', 'item_id', 'page'})
                        or not isinstance(item_id, str)):
                    raise ValueError('Release selection request is invalid')
                if 'page' in payload:
                    page = payload['page']
                    if type(page) is not int:
                        raise ValueError('Release selection request is invalid')
                    DISCOVERY.begin(item_id, request_id, page=page)
                else:
                    DISCOVERY.begin(item_id, request_id)
            elif action == 'discovery.choose':
                revision, choice_id, intent = payload.get('revision'), payload.get('choice_id'), payload.get('intent')
                if (
                    set(payload) != {'request_id', 'revision', 'choice_id', 'intent'}
                    or type(revision) is not int or not isinstance(choice_id, str) or not isinstance(intent, str)
                ):
                    raise ValueError('Release selection request is invalid')
                DISCOVERY.choose(request_id, revision, choice_id, intent)
            else:
                if set(payload) != {'request_id'}:
                    raise ValueError('Release selection request is invalid')
                DISCOVERY.cancel(request_id)
        except Exception:
            return {'ok': False, 'error': 'Selection unavailable or changed; find versions again'}
        return {'ok': True}

    if action == 'homepage.open':
        if payload:
            return {'ok': False, 'error': 'Homepage request is invalid'}
        projection = HOMEPAGE.snapshot()
        DESKTOP_CONTROL.emit('homepage', {**projection, 'open_requested': True})
        return {'ok': True}

    if action == 'homepage.refresh':
        if payload:
            return {'ok': False, 'error': 'Homepage request is invalid'}
        if not HOMEPAGE.snapshot()['online_enabled']:
            return {'ok': False, 'error': 'Enable online discovery before refreshing'}
        if not HOMEPAGE.refresh_async():
            return {'ok': False, 'error': 'Homepage refresh is unavailable'}
        return {'ok': True}

    if action == 'homepage.configure':
        if set(payload) != {'setting', 'enabled'}:
            return {'ok': False, 'error': 'Homepage setting is invalid'}
        setting = payload.get('setting')
        enabled = payload.get('enabled')
        if not isinstance(setting, str) or setting not in {'startup', 'online'} or type(enabled) is not bool:
            return {'ok': False, 'error': 'Homepage setting is invalid'}
        try:
            if setting == 'startup':
                _persist_homepage_configuration(show_on_startup=enabled)
            else:
                _persist_homepage_configuration(online_enabled=enabled)
        except Exception:
            return {'ok': False, 'error': 'Could not update homepage settings'}
        return {'ok': True}

    if action == 'artwork.configure':
        enabled = payload.get('enabled')
        if set(payload) != {'enabled'} or type(enabled) is not bool:
            return {'ok': False, 'error': 'Artwork setting is invalid'}
        try:
            _persist_artwork_configuration(enabled)
        except Exception:
            return {'ok': False, 'error': 'Could not update artwork settings'}
        return {'ok': True}

    if action == 'artwork.show':
        fetch = payload.get('fetch')
        expected_media_id = payload.get('media_id')
        if (
            set(payload) != {'fetch', 'media_id'}
            or type(fetch) is not bool
            or not isinstance(expected_media_id, str)
            or not expected_media_id
        ):
            return {'ok': False, 'error': 'Artwork request is invalid'}
        try:
            _show_current_artwork(
                fetch=fetch,
                desktop=True,
                expected_media_id=expected_media_id,
            )
        except Exception as error:
            safe_error = str(error)
            if safe_error not in {
                'No media is currently active',
                'Current media changed; try again',
                'Current media has no supported provider artwork to fetch',
            }:
                safe_error = 'Current artwork is unavailable'
            return {'ok': False, 'error': safe_error}
        return {'ok': True}

    if action == 'autocomplete.catalog':
        allowed_fields = {'include_compatibility', 'typed_prefix'}
        if not set(payload).issubset(allowed_fields):
            return {'ok': False, 'error': 'Command catalog request is invalid'}
        include_compatibility = payload.get('include_compatibility', False)
        typed_prefix = payload.get('typed_prefix', '')
        if type(include_compatibility) is not bool or not isinstance(typed_prefix, str):
            return {'ok': False, 'error': 'Command catalog request is invalid'}
        if len(typed_prefix) > 64 or any(
            ord(character) < 32 or ord(character) == 127 for character in typed_prefix
        ):
            return {'ok': False, 'error': 'Command catalog request is invalid'}
        return {
            'ok': True,
            'catalog': {
                'schema_version': 1,
                'entries': serialize_command_catalog(
                    include_compatibility=include_compatibility,
                    typed_prefix=typed_prefix,
                ),
            },
        }

    if action in {'video.status', 'video.configure', 'video.captions', 'video.audio-offset'}:
        try:
            if action == 'video.status':
                if payload:
                    raise VideoUnavailable('Invalid video status request')
                state = VIDEO.status()
            elif action == 'video.configure':
                if set(payload) != {'media_id', 'mode'} or payload.get('mode') not in {'audio', 'video'}:
                    raise VideoUnavailable('Invalid video presentation request')
                snapshot = vas.controller.snapshot()
                if not payload.get('media_id') or payload['media_id'] != project_playback_status(snapshot).media_id:
                    raise VideoUnavailable('Current media changed; try again')
                _ensure_media_playable(snapshot.media)
                state = VIDEO.request(str(payload['mode']), expected_media=snapshot.media)
            elif action == 'video.captions':
                operation = payload.get('operation')
                value = payload.get('value')
                expected = {'media_id', 'operation'}
                if operation in {'load', 'replace'}:
                    expected.add('path')
                elif operation in {'shift', 'set-offset'}:
                    expected.add('value')
                elif operation == 'select':
                    expected.update({'track_id', 'revision'})
                elif operation == 'languages':
                    expected.add('languages')
                if set(payload) != expected or operation not in {
                    'load', 'replace', 'on', 'off', 'clear', 'shift', 'set-offset', 'select', 'languages', 'auto',
                } or (operation in {'shift', 'set-offset'} and type(value) is not int):
                    raise CaptionError('Invalid caption request')
                snapshot = vas.controller.snapshot()
                if not payload.get('media_id') or payload['media_id'] != project_playback_status(snapshot).media_id:
                    raise VideoUnavailable('Current media changed; try again')
                if operation == 'select':
                    track_id, revision = payload.get('track_id'), payload.get('revision')
                    if not isinstance(track_id, str) or not re.fullmatch(r'[a-f0-9]{32}', track_id) or type(revision) is not int:
                        raise CaptionError('Invalid caption selection')
                    state = VIDEO.select_caption(track_id, revision, expected_media=snapshot.media)
                elif operation == 'languages':
                    languages = payload.get('languages')
                    if not isinstance(languages, list) or any(not isinstance(item, str) for item in languages):
                        raise CaptionError('Invalid caption language preferences')
                    state = VIDEO.set_caption_languages(languages)
                elif operation == 'auto':
                    state = VIDEO.caption_automatic(expected_media=snapshot.media)
                elif operation in {'load', 'replace'}:
                    path = payload.get('path')
                    if not isinstance(path, str) or not path:
                        raise CaptionError('Caption path is invalid')
                    state = VIDEO.load_captions(path, replace=operation == 'replace', expected_media=snapshot.media)
                else:
                    state = VIDEO.configure_captions(
                        str(operation), cast(int, value) if 'value' in payload else None,
                        expected_media=snapshot.media,
                    )
            else:
                value = payload.get('value')
                relative = payload.get('relative')
                if set(payload) != {'media_id', 'value', 'relative'} or type(value) is not int \
                        or type(relative) is not bool:
                    raise VideoUnavailable('Invalid audio synchronization request')
                snapshot = vas.controller.snapshot()
                if not payload.get('media_id') or payload['media_id'] != project_playback_status(snapshot).media_id:
                    raise VideoUnavailable('Current media changed; try again')
                state = VIDEO.configure_audio_offset(
                    cast(int, value), relative=cast(bool, relative), expected_media=snapshot.media,
                )
            DESKTOP_CONTROL.emit('video', VIDEO.host_status())
            return {'ok': True}
        except (CaptionError, VideoUnavailable, PlaybackBlockedError) as error:
            return {'ok': False, 'error': str(error)}
        except Exception:
            return {'ok': False, 'error': 'Local video is unavailable'}
    if action in {'equalizer.status', 'equalizer.configure'}:
        try:
            if action == 'equalizer.status':
                if payload:
                    raise ValueError('Invalid equalizer request')
                state = EQUALIZER.status()
            else:
                if 'revision' not in payload:
                    raise ValueError('Equalizer revision is required')
                state = EQUALIZER.apply(payload)
            DESKTOP_CONTROL.emit('equalizer', state)
            return {'ok': True}
        except ValueError as error:
            return {'ok': False, 'error': str(error)}
        except Exception:
            return {'ok': False, 'error': 'Could not update equalizer settings'}

    if action == 'playback.seek':
        action_origin = payload.get('origin', 'desktop')
        if not isinstance(action_origin, str) or action_origin not in {'desktop', 'mini-player', 'cli'}:
            return {'ok': False, 'error': 'Playback action origin is invalid'}
        expected_media_id = payload.get('media_id')
        if not isinstance(expected_media_id, str) or not expected_media_id:
            return {'ok': False, 'error': 'Playback target is unavailable'}
        raw_target = payload.get('target_seconds')
        if isinstance(raw_target, bool) or not isinstance(raw_target, (int, float)):
            return {'ok': False, 'error': 'Seek target is invalid'}
        target = float(raw_target)
        if not math.isfinite(target) or target < 0:
            return {'ok': False, 'error': 'Seek target is invalid'}

        snapshot = vas.controller.snapshot()
        if snapshot.media is None or snapshot.media.stable_id != expected_media_id:
            return {'ok': False, 'error': 'Current media changed; try again'}
        if _is_media_blocked(snapshot.media):
            return {'ok': False, 'error': 'Playback is blocked for this media'}
        if snapshot.state not in {PlaybackState.PLAYING, PlaybackState.PAUSED}:
            return {'ok': False, 'error': 'Seek is unavailable in the current state'}
        capabilities = snapshot.media.capabilities
        duration = snapshot.duration
        if (
            not capabilities.finite
            or capabilities.live
            or not capabilities.seekable
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(float(duration))
            or float(duration) <= 0
        ):
            return {'ok': False, 'error': 'Current media is not seekable'}

        try:
            vas.controller.seek(min(target, float(duration)), origin=action_origin)
        except Exception:
            return {'ok': False, 'error': 'Could not seek playback'}
        DESKTOP_CONTROL.emit('playback', _playback_status_projection().to_dict())
        return {'ok': True}

    playback_actions = {
        'playback.play': 'play',
        'playback.pause': 'pause',
        'playback.previous': 'previous',
        'playback.next': 'next',
    }
    if action in playback_actions:
        action_origin = payload.get('origin', 'desktop')
        if not isinstance(action_origin, str) or action_origin not in {'desktop', 'mini-player'}:
            return {'ok': False, 'error': 'Playback action origin is invalid'}
        expected_media_id = payload.get('media_id')
        if not isinstance(expected_media_id, str) or not expected_media_id:
            return {'ok': False, 'error': 'Playback target is unavailable'}
        snapshot = vas.controller.snapshot()
        if snapshot.media is None or snapshot.media.stable_id != expected_media_id:
            return {'ok': False, 'error': 'Current media changed; try again'}
        if _is_media_blocked(snapshot.media):
            return {'ok': False, 'error': 'Playback is blocked for this media'}
        operation = playback_actions[action]
        try:
            if operation == 'play':
                if snapshot.state != PlaybackState.PAUSED:
                    return {'ok': False, 'error': 'Play is unavailable in the current state'}
                playpausetoggle(softtoggle=False, action_origin=action_origin)
                if vas.controller.snapshot().state != PlaybackState.PLAYING:
                    return {'ok': False, 'error': 'Could not resume playback'}
            elif operation == 'pause':
                if snapshot.state not in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}:
                    return {'ok': False, 'error': 'Pause is unavailable in the current state'}
                playpausetoggle(softtoggle=False, action_origin=action_origin)
                if vas.controller.snapshot().state != PlaybackState.PAUSED:
                    return {'ok': False, 'error': 'Could not pause playback'}
            elif _step_queue_playback(operation) is None:
                return {'ok': False, 'error': f'No {operation} queue item is available'}
        except Exception:
            return {'ok': False, 'error': 'Could not apply playback control'}
        DESKTOP_CONTROL.emit('playback', _playback_status_projection().to_dict())
        return {'ok': True}

    if action not in {'favorite.toggle', 'rating.set'}:
        return {'ok': False, 'error': 'Unsupported desktop control request'}
    expected_media_id = payload.get('media_id')
    if not isinstance(expected_media_id, str) or not expected_media_id:
        return {'ok': False, 'error': 'Rating target is unavailable'}

    snapshot = vas.controller.snapshot()
    if snapshot.media is None or snapshot.media.stable_id != expected_media_id:
        return {'ok': False, 'error': 'Current media changed; try again'}
    status = _favorite_status_projection(snapshot.media)
    if not status.toggle_enabled:
        return {
            'ok': False,
            'error': status.unavailable_reason or 'Rating is unavailable',
        }
    media = _preference_media(snapshot.media)
    if media is None:
        return {'ok': False, 'error': 'Rating target is unavailable'}
    try:
        if action == 'rating.set':
            rating = payload.get('rating')
            if (
                set(payload) != {'media_id', 'rating'}
                or isinstance(rating, bool)
                or not isinstance(rating, int)
                or not 0 <= rating <= 5
            ):
                return {'ok': False, 'error': 'Rating must be a whole number from 0 to 5'}
            PREFERENCES.set_rating(media, rating)
        else:
            if set(payload) != {'media_id'}:
                return {'ok': False, 'error': 'Rating request is invalid'}
            PREFERENCES.toggle(media, PreferenceState.FAVORITE)
    except Exception:
        return {'ok': False, 'error': 'Could not update rating'}

    # Publish the complete authoritative projection before acknowledging the request.
    DESKTOP_CONTROL.emit('playback', _playback_status_projection().to_dict())
    return {'ok': True}


def chapters_command(parameters: list[str]) -> None:
    """Inspect chapters or navigate through the identity-bound playback boundary."""
    usage = 'Usage: chapters [list|current|show [N]|find <text>|N|goto N|next|prev|first|last|restart|+N|-N|help]'
    values = [value.casefold() for value in parameters]
    action = values[0] if values else 'list'
    if action in {'help', '--help', '-h'}:
        IPrint(usage, visible=visible)
        IPrint('chapter is an alias. Numbers are 1-based; + / - and next / prev move one chapter; +3 or + 3 moves three.', visible=visible)
        IPrint('show inspects the current chapter; show N inspects another. find only filters the list.', visible=visible)
        IPrint('Jumps preserve pause state and do not wrap. restart returns to the current chapter start; preferred bounds still apply.', visible=visible)
        return
    if action in {'+', '-'} and len(values) == 2 and re.fullmatch(r'[0-9]{1,6}', values[1]):
        action += values[1]
        values = [action]
    number = r'[1-9][0-9]{0,5}'
    valid = (
        (len(values) <= 1 and (action in {'list', 'current', 'show', 'next', 'prev', 'previous', 'first', 'last', 'restart', '+', '-'}
                              or re.fullmatch(r'[+-]?' + number, action)))
        or (len(values) == 2 and action in {'goto', 'show'} and re.fullmatch(number, values[1]))
        or (len(values) >= 2 and action == 'find')
    )
    if not valid:
        IPrint(usage, visible=visible)
        return
    status = _playback_status_projection()
    if status.media_id is None:
        IPrint('No active media.', visible=visible)
        return
    if not status.chapter_markers:
        IPrint('No chapter timeline is available for the current media.', visible=visible)
        return
    markers = status.chapter_markers
    current = next((marker for marker in markers if marker.current), None)
    if action == 'find':
        query = ' '.join(parameters[1:]).casefold()
        markers = [marker for marker in markers if query in marker.title.casefold()]
        if not markers:
            IPrint('No matching chapters.', visible=visible)
            return
    elif action not in {'list', 'current'}:
        target_index = None
        if action in {'show', 'goto'} and len(values) == 2:
            target_index = int(values[1])
        elif action in {'first', 'last'}:
            target_index = markers[0 if action == 'first' else -1].index
        elif re.fullmatch(number, action):
            target_index = int(action)
        elif action in {'next', '+'}:
            target_index = next((marker.index for marker in markers if marker.start_time > status.position_seconds), None)
        elif action in {'prev', 'previous', '-'}:
            anchor = current.start_time if current else status.position_seconds
            target_index = next((marker.index for marker in reversed(markers) if marker.start_time < anchor), None)
        elif current:
            target_index = current.index if action in {'show', 'restart'} else current.index + int(action)
        else:
            IPrint('No current chapter at this position. Use chapters N or chapters next/prev.', visible=visible)
            return
        selected = next((marker for marker in markers if marker.index == target_index), None)
        if selected is None:
            IPrint('No chapter in that direction or at that number; chapter jumps do not wrap.', visible=visible)
            return
        if action == 'show':
            markers = [selected]
        else:
            start = status.region.start_seconds or 0.0
            end = status.region.end_seconds
            target = max(selected.start_time, start)
            if selected.end_time <= start or (end is not None and target >= end):
                IPrint('That chapter is outside the preferred play region.', visible=visible)
                return
            result = _desktop_control_request(
                'playback.seek',
                {'media_id': status.media_id, 'target_seconds': target, 'origin': 'cli'},
            )
            if not result.get('ok'):
                IPrint(str(result.get('error', 'Could not seek playback')), visible=visible)
                return
            IPrint(f'Chapter {selected.index}: {selected.title} — seeking to {_status_time(target)}', visible=visible)
            return
    IPrint(f'Chapters: {_status_media_label(status)} [{_status_source_label(status)}]', visible=visible)
    rows = [
        (
            marker.index,
            '*' if marker.current else '',
            _status_time(marker.start_time),
            _status_time(marker.end_time),
            _status_time(marker.end_time - marker.start_time),
            marker.title,
        )
        for marker in markers
    ]
    IPrint(tbl(rows, headers=('#', 'Now', 'Start', 'End', 'Duration', 'Chapter'), tablefmt='plain'), visible=visible)
    IPrint('* marks the current chapter. chapters N jumps; chapters help lists navigation and inspection commands.', visible=visible)


def captions_command(parameters: list[str]) -> None:
    """Manage the bounded caption track for the active video presentation."""
    usage = ('Usage: captions [status|tracks|select <number>|auto|language [auto|codes...]|'
             'load <file>|replace <file>|on|off|clear|offset <ms>|shift <signed-ms>]')
    action = parameters[0].casefold() if parameters else 'status'
    snapshot = vas.controller.snapshot()
    try:
        if (not parameters) or (action in {'status', 'show'} and len(parameters) == 1):
            state = cast(dict[str, object], VIDEO.status()['captions'])
        elif action == 'tracks' and len(parameters) == 1:
            state = cast(dict[str, object], VIDEO.status()['captions'])
            tracks = cast(list[dict], state.get('tracks', []))
            for index, track in enumerate(tracks, 1):
                selected = '*' if track['id'] == state.get('selected_id') else ' '
                flags = ', '.join(flag for flag in ('default', 'forced') if track.get(flag))
                IPrint(f"{selected} {index}. {track['label']} | {track['source']} | {track['codec']}"
                       f"{f' | {flags}' if flags else ''}", visible=visible)
            if not tracks:
                IPrint('No caption tracks listed for the current media. Open video and let discovery complete, '
                       'or load a subtitle file explicitly.', visible=visible)
        elif action == 'select' and len(parameters) == 2 and re.fullmatch(r'\d{1,2}', parameters[1]):
            current = cast(dict, VIDEO.status()['captions'])
            tracks = current.get('tracks', [])
            index = int(parameters[1]) - 1
            if not 0 <= index < len(tracks):
                raise CaptionError('Choose a number from captions tracks')
            state = cast(dict, VIDEO.select_caption(tracks[index]['id'], current['revision'],
                                                   expected_media=snapshot.media)['captions'])
        elif action == 'auto' and len(parameters) == 1:
            state = cast(dict, VIDEO.caption_automatic(expected_media=snapshot.media)['captions'])
        elif action == 'language':
            languages = [] if parameters[1:] == ['auto'] else parameters[1:]
            state = cast(dict, (VIDEO.set_caption_languages(languages) if len(parameters) > 1
                               else VIDEO.status())['captions'])
        elif action in {'load', 'replace'} and len(parameters) >= 2:
            state = cast(dict[str, object], VIDEO.load_captions(
                ' '.join(parameters[1:]), replace=action == 'replace', expected_media=snapshot.media,
            )['captions'])
        elif action in {'on', 'off', 'clear'} and len(parameters) == 1:
            state = cast(dict[str, object], VIDEO.configure_captions(
                action, expected_media=snapshot.media,
            )['captions'])
        elif action in {'offset', 'shift'} and len(parameters) == 2 and re.fullmatch(r'[+-]?\d{1,6}', parameters[1]):
            state = cast(dict[str, object], VIDEO.configure_captions(
                'set-offset' if action == 'offset' else 'shift', int(parameters[1]), expected_media=snapshot.media,
            )['captions'])
        else:
            raise CaptionError(usage)
        DESKTOP_CONTROL.emit('video', VIDEO.host_status())
        available = state.get('available') is True
        enabled_value = state.get('enabled') is True
        label = state.get('label')
        source = state.get('source')
        offset = state.get('offset_ms')
        languages = cast(list[str], state.get('preferred_languages', []))
        if action in {'status', 'show', 'tracks', 'language', 'auto'}:
            IPrint(f"Caption languages: {', '.join(languages) or 'automatic'}", visible=visible)
        if state.get('message'):
            IPrint(str(state['message']), visible=visible)
        if state.get('auto_status') == 'loading':
            IPrint('Caption selection is loading in the background; playback continues.', visible=visible)
        if available and isinstance(label, str) and type(offset) is int:
            enabled = 'on' if enabled_value else 'off'
            source_text = f" | {source}" if source in {'manual', 'sidecar', 'embedded'} else ''
            IPrint(
                f"Captions: {enabled} | {label}{source_text} | offset {offset:+d} ms",
                visible=visible,
            )
        else:
            automatic = state.get('auto_status')
            suffix = ' (checking local media)' if automatic == 'loading' else ''
            IPrint(f'Captions: none loaded{suffix}', visible=visible)
    except (CaptionError, OSError, VideoUnavailable) as error:
        IPrint(f'Caption error: {error}', visible=visible)


def avsync_command(parameters: list[str]) -> None:
    """Shift picture time against authoritative audio without touching the decoder."""
    usage = 'Usage: avsync [status|set <signed-ms>|shift <signed-ms>|reset]'
    action = parameters[0].casefold() if parameters else 'status'
    snapshot = vas.controller.snapshot()
    try:
        if (not parameters) or (action == 'status' and len(parameters) == 1):
            state = VIDEO.status()
        elif action == 'reset' and len(parameters) == 1:
            state = VIDEO.configure_audio_offset(0, expected_media=snapshot.media)
        elif action in {'set', 'shift'} and len(parameters) == 2 and re.fullmatch(r'[+-]?\d{1,5}', parameters[1]):
            state = VIDEO.configure_audio_offset(
                int(parameters[1]), relative=action == 'shift', expected_media=snapshot.media,
            )
        else:
            raise VideoUnavailable(usage)
        DESKTOP_CONTROL.emit('video', VIDEO.host_status())
        offset_value = state.get('audio_offset_ms')
        if type(offset_value) is not int:
            raise VideoUnavailable('Video synchronization status is unavailable')
        offset = offset_value
        IPrint(
            f'Video synchronization: audio {"later" if offset > 0 else "earlier" if offset < 0 else "aligned"}'
            f'{f" by {abs(offset)} ms" if offset else ""}',
            visible=visible,
        )
    except VideoUnavailable as error:
        IPrint(f'Video synchronization error: {error}', visible=visible)


def _status_time(seconds: float | int | None) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'


def _status_media_label(status: PlaybackStatusProjection) -> str:
    title = status.title or 'Playback'
    return f'{status.artist} — {title}' if status.artist else title


def _status_source_label(status: PlaybackStatusProjection) -> str:
    return status.source.replace('_', ' ').title() if status.source else 'Unknown source'


def _status_progress_bar(percent: float | None, width: int = 20) -> str | None:
    if percent is None:
        return None
    completed = max(0, min(width, round(width * percent / 100)))
    return f"[{'#' * completed}{'-' * (width - completed)}]"


def _status_summary(status: PlaybackStatusProjection, *, detailed: bool = False) -> str:
    """Format status without exposing transport or resolver details."""
    parts = []
    if status.live:
        parts.extend(('LIVE', f'{_status_time(status.position_seconds)} elapsed'))
    elif status.duration_seconds is not None:
        bar = _status_progress_bar(status.percent)
        if bar:
            parts.append(bar)
        parts.append(
            f'{_status_time(status.position_seconds)} / {_status_time(status.duration_seconds)}'
        )
        if status.percent is not None:
            parts.append(f'{status.percent:.0f}%')
    elif status.media_id is not None:
        parts.extend((f'{_status_time(status.position_seconds)} elapsed', 'duration unknown'))

    parts.append(status.display_state)
    if status.policy.blocked:
        parts.append('playback blocked')
    if status.region.active:
        parts.append(f'region {_region_description(status.region)}')
    if status.queue_position is not None:
        parts.append(f'queue {status.queue_position}/{status.queue_count}')
    if detailed or status.live or status.duration_seconds is None:
        parts.append('seekable' if status.seekable else 'nonseekable')
    if status.safe_error:
        parts.append(f'Error: {status.safe_error}')
    return ' | '.join(parts)


def _status_chapter_label(chapter: PlaybackChapterProjection | None) -> str | None:
    """Format a safe projected chapter without inspecting media or resolver state."""
    if chapter is None:
        return None
    title = str(chapter.title or '').strip()
    index = chapter.index
    count = chapter.count
    position = (
        f'Ch {index}/{count}'
        if isinstance(index, int)
        and isinstance(count, int)
        and 1 <= index <= count
        else ''
    )
    if position and title:
        return f'{position} · {title}'
    return position or title or None


def _playback_status_lines(
    status: PlaybackStatusProjection,
    *,
    detailed: bool = False,
    now: bool = False,
) -> list[str]:
    """Build synchronous CLI lines for now/progress commands."""
    stopped = status.display_state == 'Stopped'
    if stopped or (status.media_id is None and status.display_state != 'Failed'):
        return ['Not playing | Stopped']

    label = _status_media_label(status)
    source = _status_source_label(status)
    summary = _status_summary(status, detailed=detailed)
    if not detailed:
        prefix = 'Now' if now else 'Progress'
        if now:
            lines = [f'{prefix}: {label} [{source}]', f'Status: {summary}']
            if chapter_label := _status_chapter_label(status.chapter):
                lines.append(
                    f'{chapter_label} '
                    f'({_status_time(status.chapter.start_time)}-{_status_time(status.chapter.end_time)})'
                )
            return lines
        line = f'{label} [{source}] | {summary}'
        if chapter_label := _status_chapter_label(status.chapter):
            line += f' | {chapter_label}'
        return [line]

    lines = [f'Title: {label}', f'Source: {source}', f'State: {status.display_state}']
    if status.live:
        lines.append(f'Progress: LIVE | {_status_time(status.position_seconds)} elapsed')
    elif status.duration_seconds is not None:
        bar = _status_progress_bar(status.percent)
        percent = f'{status.percent:.0f}%' if status.percent is not None else 'unknown'
        lines.append(
            f'Progress: {bar} {_status_time(status.position_seconds)} / '
            f'{_status_time(status.duration_seconds)} ({percent})'
        )
    else:
        lines.append(f'Progress: {_status_time(status.position_seconds)} elapsed | duration unknown')
    lines.append(f'Seekable: {"yes" if status.seekable else "no"}')
    if status.region.active:
        lines.append(f'Preferred play region: {_region_description(status.region)}')
    if status.queue_position is not None:
        lines.append(f'Queue: {status.queue_position}/{status.queue_count}')
    if chapter_label := _status_chapter_label(status.chapter):
        lines.append(
            f'{chapter_label} '
            f'({_status_time(status.chapter.start_time)}-{_status_time(status.chapter.end_time)})'
        )
    if status.safe_error:
        lines.append(f'Error: {status.safe_error}')
    return lines


def _print_playback_status(*, detailed: bool = False, now: bool = False) -> None:
    for line in _playback_status_lines(
        _playback_status_projection(),
        detailed=detailed,
        now=now,
    ):
        IPrint(line, visible=visible)

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
    _disconnect_video_controller()
    if snapshot.media:
        RECOMMENDER.record_event(
            snapshot.media,
            'played_duration',
            reward=0,
            context={'position': snapshot.position, 'duration': snapshot.duration},
        )

    def close_resume():
        # Keep the final authoritative position before playback closes, but perform
        # persistence in the bounded shutdown worker rather than delaying its start.
        PLAYBACK_RESUME.capture_now(snapshot)
        PLAYBACK_RESUME.close()

    # These services are independent at shutdown. Closing them concurrently keeps
    # one slow network encoder, watcher, or device driver from serially delaying exit.
    closures = (
        ('sleep timer', SLEEP_TIMER.close),
        ('discord presence', PRESENCE.close),
        ('station', STATION.close),
        ('video', VIDEO.close),
        ('playback resume', close_resume),
        ('downloads', DOWNLOADS.close),
        ('broadcast', BROADCASTER.close),
        ('homepage', HOMEPAGE.close),
        ('catalogue', CATALOGUE_READER.close),
        ('release selection', DISCOVERY.close),
        ('artwork', _close_artwork_controller),
        ('playback events', PLAYBACK_EVENTS.close),
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


def _remember_navigation_context(context, *, search=False):
    """Retain an ordered user-selected context without changing playback."""
    global _NAVIGATION_CONTEXT, _LAST_SEARCH_CONTEXT
    if search:
        _LAST_SEARCH_CONTEXT = context
    else:
        _NAVIGATION_CONTEXT = context
    return context


def _bind_navigation_context(context, media):
    """Bind a collection snapshot to the active occurrence without guessing duplicates."""
    if context.matches(media):
        return context
    matches = [
        index
        for index, entry in enumerate(context.entries)
        if media is not None and entry.stable_id == media.stable_id
    ]
    if not matches:
        raise ValueError(f'Current media is not in {context.name or context.scope.value}')
    if len(matches) > 1:
        raise ValueError(
            f'Current media occurs more than once in {context.name or context.scope.value}; '
            'play the intended occurrence first'
        )
    return context.at(matches[0])


def _favorite_navigation_context(media):
    entries = []
    for position, preference in enumerate(PREFERENCES.list(PreferenceState.FAVORITE), 1):
        candidate = _preference_search_media(preference)
        entries.append(NavigationEntry(
            media=candidate,
            stable_id=preference.stable_id,
            position=position,
            label=_favorite_display_label(preference, candidate),
            source_scope=NavigationScope.FAVORITES,
            occurrence_id=preference.stable_id,
        ))
    if not entries:
        raise ValueError('No favorites are saved')
    previous = _NAVIGATION_CONTEXT
    cursor = previous.cursor if previous and previous.scope == NavigationScope.FAVORITES else -1
    context = NavigationContext(NavigationScope.FAVORITES, tuple(entries), cursor, 'favorites')
    return _bind_navigation_context(context, media)


def _active_playlist_name():
    previous = _NAVIGATION_CONTEXT
    if previous and previous.scope == NavigationScope.PLAYLIST and previous.name:
        return previous.name
    origin = QUEUE.origin() or ''
    if not origin.startswith('playlist:'):
        return None
    try:
        return QUEUE.playlists.get(origin.removeprefix('playlist:')).name
    except PlaylistError:
        return None


def _playlist_navigation_context(name, media):
    playlist_name = name or _active_playlist_name()
    if not playlist_name:
        raise ValueError(
            'No current playlist context; use --in playlist "<name>" or playlist play "<name>"'
        )
    try:
        playlist = QUEUE.playlists.get(playlist_name)
    except PlaylistError as error:
        raise ValueError(str(error)) from error
    entries = tuple(
        NavigationEntry(
            media=candidate,
            stable_id=candidate.stable_id,
            position=position,
            label=_scoped_search_media_label(candidate),
            source_scope=NavigationScope.PLAYLIST,
            occurrence_id=f'{playlist.playlist_id}:{position}',
        )
        for position, candidate in enumerate(QUEUE.playlists.flattened_media(playlist.tree), 1)
    )
    if not entries:
        raise ValueError(f'Playlist "{playlist.name}" is empty')
    previous = _NAVIGATION_CONTEXT
    cursor = (
        previous.cursor
        if previous
        and previous.scope == NavigationScope.PLAYLIST
        and previous.name == playlist.name
        else -1
    )
    return _bind_navigation_context(
        NavigationContext(NavigationScope.PLAYLIST, entries, cursor, playlist.name),
        media,
    )


def _library_navigation(request, media):
    if media is None or media.source != MediaSource.LOCAL:
        raise ValueError('Library navigation requires a currently active indexed library item')
    current_index = _library_song_index(media.original_uri)
    if not isinstance(current_index, int):
        raise ValueError('Current media is outside the indexed library')
    target_index = current_index + request.offset
    if target_index not in range(1, len(_sound_files) + 1):
        boundary = 'end' if request.offset > 0 else 'beginning'
        raise ValueError(f'Cannot navigate past the {boundary} of the library')
    if request.immediate:
        _ensure_media_playable(_library_media(target_index))
        local_play_commands([None, str(target_index)])
        return _library_media(target_index)
    target = _library_media(target_index)
    IPrint(
        f'@{"n" if request.offset > 0 else "p"} '
        f'{colored.fg("light_red")}library {target_index}/{len(_sound_files)}{colored.fg("aquamarine_3")} | '
        f'{_scoped_search_media_label(target)}{colored.attr("reset")}',
        visible=visible,
    )
    return target


def _play_navigation_entry(entry):
    """Play one validated occurrence through its owning collection boundary."""
    if entry.media is None:
        raise ValueError(f'{entry.label} is missing or unavailable')
    if entry.source_scope == NavigationScope.FAVORITES:
        if not any(
            item.stable_id == entry.stable_id
            for item in PREFERENCES.list(PreferenceState.FAVORITE)
        ):
            raise ValueError('Favourites changed after selection; inspect the list again')
        selection = _favorite_selection(entry.position)
        if selection[0].stable_id != entry.stable_id:
            raise ValueError('Favorites changed; run the navigation command again')
        return _play_favorite_selection(entry.position, *selection)
    if entry.source_scope == NavigationScope.QUEUE:
        item = next(
            (item for item in QUEUE.items() if item.queue_id == entry.occurrence_id),
            None,
        )
        if item is None or item.media.stable_id != entry.stable_id:
            raise ValueError('Queue results changed; search or list the queue again')
        _ensure_media_playable(item.media)
        return _play_queue_item(QUEUE.jump(QUEUE.items().index(item)))
    if entry.source_scope == NavigationScope.LIBRARY:
        current = _library_media(entry.position)
        if current.stable_id != entry.stable_id:
            raise ValueError('Library results changed; search the library again')
        _ensure_media_playable(current)
        return local_play_commands([None, str(entry.position)])
    media = entry.media
    _ensure_media_playable(media)
    if media.source == MediaSource.LOCAL:
        library_index = _library_song_index(media.original_uri)
        if isinstance(library_index, int):
            return local_play_commands([None, str(library_index)])
        if not Path(media.original_uri).is_file():
            raise ValueError(f'{entry.label} is missing or unavailable')
        return play_local_default_player(media.original_uri, _songindex=None, media=media)
    stopsong()
    vas.supervisor.play(media, origin='cli')
    _set_current_media_state(media)
    _show_local_copy_hint(media)
    return media


def _navigate_context(command, request, context):
    target = context.target(request.offset)
    if target is None:
        boundary = 'end' if request.offset > 0 else 'beginning'
        alias = ('.' if request.immediate else '') + ('+' if request.offset > 0 else '-')
        if abs(request.offset) != 1:
            alias += str(abs(request.offset))
        raise ValueError(
            f'Cannot navigate past the {boundary} of {context.name or context.scope.value} '
            f'({context.cursor + 1}/{len(context.entries)}). '
            f'To {"play" if request.immediate else "preview"} in another collection, '
            f'use "{alias} library" or "{alias} queue".'
        )
    target_index, entry = target
    if request.immediate:
        played = _play_navigation_entry(entry)
        selected_context = context.at(target_index)
        if selected_context.scope == NavigationScope.RESULTS:
            _remember_navigation_context(selected_context, search=True)
        _remember_navigation_context(selected_context)
        return played
    # Peeking into another collection is not a scope switch. Only successful
    # immediate selection above changes navigation ownership.
    IPrint(
        f'@{"n" if request.offset > 0 else "p"} '
        f'{colored.fg("light_red")}{context.name or context.scope.value} {target_index + 1}/{len(context.entries)} '
        f'({entry.source_scope.value} #{entry.position})'
        f'{colored.fg("aquamarine_3")} | '
        f'{_blocked_label(entry.label, entry.media) if entry.media else entry.label}'
        f'{colored.attr("reset")}',
        visible=visible,
    )
    return entry.media


def navigation_command(command, arguments):
    """Preview or play relative to the active or explicitly selected collection."""
    request = parse_navigation(command, arguments)
    snapshot = vas.controller.snapshot()
    media = snapshot.media
    if media is None:
        raise ValueError('Cannot navigate because no media is currently active')

    if request.scope == NavigationScope.LIBRARY:
        return _library_navigation(request, media)

    if request.scope in {NavigationScope.AUTO, NavigationScope.QUEUE}:
        active_context = _NAVIGATION_CONTEXT
        if request.scope == NavigationScope.AUTO and active_context and active_context.matches(media):
            if active_context.scope == NavigationScope.FAVORITES:
                active_context = _favorite_navigation_context(media)
            elif active_context.scope == NavigationScope.PLAYLIST:
                active_context = _playlist_navigation_context(active_context.name, media)
            return _navigate_context(command, request, active_context)
        if _navigate_active_queue(command, request.offset):
            return None
        if request.scope == NavigationScope.QUEUE:
            raise ValueError('Current media is not the active queue item')
        return _library_navigation(request, media)

    if request.scope == NavigationScope.FAVORITES:
        return _navigate_context(command, request, _favorite_navigation_context(media))
    if request.scope == NavigationScope.PLAYLIST:
        if (
            request.scope_name is None
            and (QUEUE.origin() or '').startswith('playlist:')
            and _navigate_active_queue(command, request.offset)
        ):
            return None
        return _navigate_context(
            command,
            request,
            _playlist_navigation_context(request.scope_name, media),
        )
    if request.scope == NavigationScope.RESULTS:
        if _LAST_SEARCH_CONTEXT is None:
            raise ValueError('No search results are available for navigation')
        return _navigate_context(
            command,
            request,
            _bind_navigation_context(_LAST_SEARCH_CONTEXT, media),
        )
    raise ValueError(f'Unsupported navigation collection: {request.scope.value}')


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
        try:
            _ensure_media_playable(target.media)
        except PlaybackBlockedError as error:
            SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)
            return True
        _play_queue_item(QUEUE.jump(target_position))
        return True
    library_index = _library_song_index(target.media.original_uri)
    position_label = f'queue {target_position + 1}/{len(items)}'
    if library_index != 'N/A':
        position_label += f' (library #{library_index})'
    title = _blocked_label(
        _media_display_label(target.media),
        target.media,
    )
    IPrint(
        f'@{command[0]} {colored.fg("light_red")}{position_label}'
        f'{colored.fg("aquamarine_3")} | {title}{colored.attr("reset")}',
        visible=visible,
    )
    return True


def play_local_default_player(songpath, _songindex, is_queue=False, media=None, presentation=None):
    global isplaying, currentsong, currentsong_length, songindex
    global USER_DATA, current_media_type, SONG_CHANGED

    try:
        queue_position, queue_item = _queued_local_item(songpath)
        if media is None and queue_item is not None:
            media = queue_item.media
        if not is_queue and queue_position is not None:
            QUEUE.jump(queue_position)
        if media is None:
            path = songpath[0] if isinstance(songpath, list) else songpath
            media = MediaRef(MediaSource.LOCAL, str(Path(path).resolve()))
        media = _indexed_local_playback_media(media)
        _ensure_media_playable(media)
        vas.set_media(_type='local', localpath=songpath)
        # Preserve the library/queue stable ID through decoder completion.
        vas.current_media = media
        if media is not None:
            VIDEO.expect(media, presentation)
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

    except PlaybackBlockedError:
        raise
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

def playpausetoggle(
    softtoggle=True,
    use_multi=False,
    transition_time=0.2,
    show_progress=False,
    action_origin='cli',
): # Soft pause by default
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

                vas.media_player(action='pausetoggle', origin=action_origin)

                if visible: print(' '*12, end='\r')
                IPrint("|| Paused", visible=visible)
                isplaying = False

            else:
                vas.media_player(action='pausetoggle', origin=action_origin)

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

class _PresentationOptions(TypedDict, total=False):
    presentation: str


def _presentation_options(mode: str | None) -> _PresentationOptions:
    return {'presentation': mode} if mode else {}


def local_play_commands(commandslist, _command=False):
    global cached_volume, currentsong_length, lyrics_saved_for_song
    mode = None
    if any(flag in commandslist for flag in ('--video', '--audio', '--auto')) or (
        len(commandslist) == 2 and isinstance(commandslist[1], str)
        and not commandslist[1].isnumeric()
    ):
        try:
            arguments, mode = presentation_arguments(commandslist)
            if len(arguments) != 2:
                raise VideoUnavailable('Usage: play <number|path|current> [--audio|--video|--auto]')
            if mode == 'video' and not DESKTOP_CONTROL.enabled:
                raise VideoUnavailable('Video currently requires the Mariana desktop; use --audio in this terminal')
            if arguments[1] == 'current':
                active = vas.controller.snapshot().media
                if active is None:
                    raise VideoUnavailable('No current media')
                VIDEO.expect(active, mode)
                state = VIDEO.request(mode or 'auto', expected_media=active)
                DESKTOP_CONTROL.emit('video', VIDEO.host_status())
                return
            if not arguments[1].isnumeric():
                path = Path(arguments[1]).expanduser()
                if not path.is_file():
                    raise VideoUnavailable('Choose an existing local file or library number')
                purge_old_lyrics_if_exist()
                lyrics_saved_for_song = None
                play_local_default_player(str(path.resolve()), None, presentation=mode)
                return
            commandslist = arguments
        except VideoUnavailable as error:
            IPrint(str(error), visible=visible)
            return
    # Output volume is controlled by the shared PCM stream.

    purge_old_lyrics_if_exist()
    lyrics_saved_for_song = None

    try:
        if not _command:
            if len(commandslist) == 2:
                songindex = commandslist[1]
                if songindex.isnumeric():
                    if int(songindex) in range(1, len(_sound_files)+1):
                        currentsong_length = None
                        play_local_default_player(songpath = _sound_files[int(songindex)-1],
                                                  _songindex = songindex, **_presentation_options(mode))
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
                songindices = commandslist[1:]
                indices = []
                for songindex in songindices:
                    if songindex.isnumeric():
                        indices.append(songindex)
                enqueue(indices)
        else:
            currentsong_length = None
            play_local_default_player(songpath=_command[1:], _songindex=None)
    except PlaybackBlockedError as error:
        SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

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

def _sync_legacy_playback_state():
    """Restore CLI compatibility fields from the authoritative loaded media."""
    global currentsong, currentsong_length, current_media_type, isplaying, songindex
    restored = vas.controller.snapshot()
    if restored.media is not None:
        media = restored.media
        currentsong = media.original_uri if media.source == MediaSource.LOCAL else media.title or media.original_uri
        currentsong_length = restored.duration if restored.duration is not None else media.duration or -1
        current_media_type = {
            MediaSource.YOUTUBE: 0,
            MediaSource.URL: 1,
            MediaSource.PODCAST: 1,
            MediaSource.RADIO: 2,
            MediaSource.RECOMMENDATION: 0,
        }.get(media.source)
        songindex = _library_song_index(media.original_uri) if media.source == MediaSource.LOCAL else -1
    isplaying = restored.state in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}
    return restored


def reset_playback(*, start_playing=False):
    """Rewind finite media, restoring completed playback as paused by default."""
    global isplaying

    snapshot = vas.controller.snapshot()
    media = snapshot.media
    legacy_duration = currentsong_length not in (None, 0, -1)
    if media is None and not legacy_duration:
        return False
    if media is not None and (
        not media.capabilities.finite or media.capabilities.live or not media.capabilities.seekable
    ):
        return False
    if not song_seek('0'):
        return False

    restored = _sync_legacy_playback_state()
    if start_playing and restored.state == PlaybackState.PAUSED:
        vas.controller.resume(origin='cli')
        isplaying = True
    return True


def song_seek(timeval=None, rel_val=None):
    global currentsong

    if timeval is not None:
        try:
            target = float(timeval)
            vas.player.set_time(int(target * 1000))
            media = vas.controller.snapshot().media
            if media:
                RECOMMENDER.record_event(media, 'seek', context={'target': target})
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


def parse_fade_duration(value):
    """Return one finite, non-negative fade duration in seconds."""
    try:
        duration = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError('Fade duration must be a finite non-negative number of seconds') from error
    if not math.isfinite(duration) or duration < 0:
        raise ValueError('Fade duration must be a finite non-negative number of seconds')
    return duration


def parse_fade_arguments(arguments, current_volume):
    """Parse the extended fade command without leaving partially initialized values."""
    if not arguments or arguments[0].lower() != 'fade':
        raise ValueError('Fade command must begin with "fade"')

    tokens = arguments[1:]
    if len(tokens) in {2, 3} and all(isdecimal(value) for value in tokens):
        initial, final = (float(value) / 100 for value in tokens[:2])
        duration = parse_fade_duration(tokens[2]) if len(tokens) == 3 else 5.0
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
                duration = parse_fade_duration(value)
            position += 2

        if final is None:
            if 'from' in seen:
                final = float(current_volume)
            else:
                raise ValueError('Fade command requires a final volume')

    if not all(math.isfinite(value) for value in (initial, final)) or not 0 <= initial <= 1 or not 0 <= final <= 1:
        raise ValueError('Fade volume must be between 0 and 100')
    duration = parse_fade_duration(duration)
    return initial, final, duration

def rand_song_index_generate():
    global _sound_files_names_only
    if len(_sound_files) == 0:
        SAY(visible=visible,
        log_message='User attempted to play local audio, even though there are no audios in library',
        display_message='There are no audios in library',
        log_priority=2)
        return None
    candidates = [
        index
        for index in range(len(_sound_files_names_only))
        if not _is_media_blocked(_library_media(index + 1))
    ]
    if not candidates:
        SAY(
            visible=visible,
            log_message='Every indexed library item is playback blocked',
            display_message='No playable library media is available; unblock an item first',
            log_priority=2,
        )
        return None
    return rand.choice(candidates)


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
                   show_link_chosen_msg = False, media_ref = None, presentation=None):

    global isplaying, visible, currentsong, cached_volume
    global currentsong_length, current_media_type, songindex

    if presentation == 'video' and not DESKTOP_CONTROL.enabled:
        raise VideoUnavailable('Video currently requires the Mariana desktop; use --audio in this terminal')

    if media_type == 'general' and media_ref is None and id_if_url_is_of_yt_format(media_url):
        media_type = 'video'
    elif media_type == 'general' and media_ref is None:
        registry = getattr(vas.controller, 'resolvers', None)
        recover = getattr(registry, 'recover_stream_identity', None)
        if recover:
            media_ref = recover(media_url)
            if media_ref is not None:
                IPrint('Recovered the original YouTube identity from an exact recent stream match.', visible=visible)

    prepared_media = None
    previous_media = vas.current_media

    policy_source = {
        'video': MediaSource.YOUTUBE,
        'general': MediaSource.URL,
        'redditsession': MediaSource.URL,
    }.get(media_type)
    if policy_source is not None:
        _ensure_media_playable(media_ref or MediaRef(policy_source, media_url, title=media_name))

    # Stop prev audios b4 loading VAS Media...
    stopsong()
    songindex = -1

    # VAS Media Load/Set
    if media_type == 'video':
        YT_aud_url = vas.set_media(_type='yt_video', vidurl=media_url)
        prepared_media = vas.current_media if vas.current_media is not previous_media else None
        if prepared_media is not None and media_name and not prepared_media.title:
            prepared_media.title = media_name
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
        vas.set_media(_type='audio', audurl=media_url,
                      media=media_ref or MediaRef(MediaSource.URL, media_url, title=media_name))
        prepared_media = vas.current_media if vas.current_media is not previous_media else None

        current_media_type = 1
        currentsong = media_url
        if prepared_media is not None and prepared_media.source == MediaSource.YOUTUBE:
            current_media_type = 0
            currentsong = (prepared_media.title, prepared_media.original_uri, prepared_media.original_uri)
        recents_queue_save(currentsong)
        IPrint(f"Chosen custom media url:: {text_overflow_prettify(display_media_uri(media_url))}", visible=visible*show_link_chosen_msg)

    elif media_type == 'radio':
        # Here `media_name` is actually the radio name
        vas.set_media(_type=f'radio/{media_name}') # No need for an explicit `audurl` here... (as per definition of vas.set_media)
        prepared_media = vas.current_media if vas.current_media is not previous_media else None

        current_media_type = 2
        currentsong = media_name
        recents_queue_save(currentsong)
        IPrint(f"Chosen radio: {colored.fg('light_goldenrod_1')}{currentsong}{colored.attr('reset')}", visible=visible)

    elif media_type == 'redditsession':
        vas.set_media(_type='audio', audurl=media_url)
        prepared_media = vas.current_media if vas.current_media is not previous_media else None

        current_media_type = 3
        currentsong = (media_name, media_url)
        recents_queue_save(currentsong)

    else:
        SAY(visible=visible, display_message = "Invalid media type provided", log_message = "Invalid media type provided", log_priority = 2)
        return False

    if media_type == 'video': media_type = 'youtube'
    if media_type:

        # VAS Media Play
        if prepared_media is not None:
            VIDEO.expect(prepared_media, presentation)
        vas.media_player(action='play')
        vas.player.audio_set_volume(int(cached_volume*100))

        # TODO - Save all audio info in `data` dir
        # save_song_data()

        committed_media = prepared_media or vas.controller.snapshot().media
        if committed_media is not None:
            _record_queue_history(committed_media)
            _record_successful_start(committed_media)
        else:
            # Compatibility fallback for legacy backends that cannot project MediaRef.
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
    _show_local_copy_hint(prepared_media)


def choose_media_url(media_url_choices: list, yt: bool = True, presentation=None):
    global isplaying, currentsong

    if yt:
        if len(media_url_choices) == 1:
            media_name, media_url = media_url_choices[0]
            play_vas_media(media_name=media_name, media_url=media_url, single_video=True,
                           **_presentation_options(presentation))

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
                                   single_video=False, **_presentation_options(presentation))
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
    DISCORD_PRESENCE.configure_application_id(_configured_discord_application_id(SYSTEM_SETTINGS))
    presence_mode = _configured_presence_mode(SETTINGS)
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
                episode = latest_podbeans[podbean_index]
                if caption := episode.get('caption'):
                    if visible:
                        caption_shortened_1, caption_shortened_2 = text_overflow_prettify(caption, length_thresh=200, end_length=16, as_tuple=True)
                        caption_shortened_formatted = f"{colored.fg('hot_pink_1a')}{caption_shortened_1}"\
                                                      f"{colored.fg('aquamarine_1b')}..."\
                                                      f"{colored.fg('hot_pink_1a')}{caption_shortened_2}"\
                                                      f"{colored.attr('reset')}"

                        print(caption_shortened_formatted) # This will only print if `visible` == True

                resolver_data = {
                    key: value
                    for key, value in {
                        'description': episode.get('caption'),
                        'published': episode.get('pub_date'),
                        'explicit': episode.get('is_explicit'),
                        'artwork': episode.get('artwork'),
                    }.items()
                    if value not in (None, '')
                }
                stable_id = episode.get('stable_id')
                identity_kind = episode.get('identity_kind')
                if isinstance(stable_id, str) and isinstance(identity_kind, str):
                    resolver_data['podcast_identity_kind'] = identity_kind
                else:
                    stable_id = ''
                podcast_media = MediaRef(
                    MediaSource.PODCAST,
                    episode['url'],
                    title=episode.get('title'),
                    stable_id=stable_id,
                    resolver_data=resolver_data,
                    provenance='podcast-feed',
                    capabilities=MediaCapabilities(metadata_available=True),
                )
                play_vas_media(media_url = episode['url'],
                               media_type='general',
                               show_link_chosen_msg=False,
                               media_ref=podcast_media)

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

    presentation = None
    try:
        commandslist = _expand_relative_library_target(commandslist)
    except ValueError as error:
        IPrint(str(error), visible=visible)
        return None
    if commandslist and commandslist[0] in {'/ys', '/youtube-search', '/yl', '/youtube-link', '/ml', '/media-link'}:
        try:
            commandslist, presentation = presentation_arguments(commandslist)
            if presentation == 'video' and not DESKTOP_CONTROL.enabled:
                raise VideoUnavailable('Video currently requires the Mariana desktop; use --audio in this terminal')
        except VideoUnavailable as error:
            IPrint(str(error), visible=visible)
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
            'loop': loop_command,
            'restart': restart_command,
            'discord': discord_command,
            'desktop': desktop_command,
            'theme': theme_command,
            'home': home_command,
            'thumb': thumb_command,
            'eq': eq_command,
            'chapters': chapters_command,
            'captions': captions_command,
            'avsync': avsync_command,
            'media': media_command,
            'metadata': lambda values: media_command(['metadata', *values]),
            'librivox': librivox_command,
            'rename': rename_command,
            'station': station_command,
            'download-ya': download_audio_command,
            'fav': favorite_command,
            '.fav': lambda values: favorite_command(values, play=True),
            'block': block_command,
            'unblock': lambda values: block_command(values, unblock=True),
            'blocked': blocked_command,
            'region': region_command,
            'regions': regions_command,
            'next': lambda values: navigation_command('next', values),
            'prev': lambda values: navigation_command('prev', values),
            '.next': lambda values: navigation_command('.next', values),
            '.prev': lambda values: navigation_command('.prev', values),
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
        if commandslist[0].casefold() in {'exit', 'quit'}:
            try:
                yes, values = _confirmation_bypass(commandslist[1:])
            except ValueError as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)
                return None
            if values:
                SAY(
                    visible=visible,
                    display_message='Usage: exit|quit [y|yes|--yes]',
                    log_message='Invalid exit confirmation bypass',
                    log_priority=2,
                )
                return None
            if yes:
                return False
            perm = input(colored.fg('light_red')+'Do you want to exit? [Y]es, [N]o (default = N): '+colored.fg('magenta_3c'))
            print(colored.attr('reset'), end = '')
            if perm.strip().lower() in {'y', 'yes'}:
                return False

        if commandslist in (['all'], ['all*']):
            rescount = MAX_RESULT_COUNT
            results_enum = enumerate(
                _sound_files_names_only if commandslist == ['all*'] else _sound_files_names_only[:rescount]
            )
            rows = []
            for index, name in ((i + 1, value) for i, value in results_enum):
                media = _library_media(index)
                size, media_type = _media_listing_fields(media)
                rows.append((
                    index,
                    _active_media_marker(media),
                    _blocked_label(name, media),
                    *_preference_markers(media),
                    size,
                    media_type,
                ))
            IPrint(
                tbl(
                    rows,
                    headers=('#', 'Now', 'Media', 'Fav', 'Rating', 'Size', 'Media format'),
                    tablefmt='plain',
                ),
                visible=visible,
            )

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
                            rows = []
                            for i, name in results_enum:
                                media = _library_media(i + 1)
                                size, media_type = _media_listing_fields(media)
                                rows.append((
                                    i + 1,
                                    _active_media_marker(media),
                                    _blocked_label(name, media),
                                    *_preference_markers(media),
                                    size,
                                    media_type,
                                ))
                            IPrint(
                                tbl(
                                    rows,
                                    headers=('#', 'Now', 'Media', 'Fav', 'Rating', 'Size', 'Media format'),
                                    tablefmt='plain',
                                ),
                                visible=visible,
                            )


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
            IPrint(
                f">| {last_index} | {_blocked_label(last_name, _library_media(last_index))}",
                visible=visible,
            )

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

        elif commandslist[0] == 'refresh' and (len(commandslist) == 1 or commandslist[1] == 'all'):
            if len(commandslist) > 1:
                try:
                    yes, values = _confirmation_bypass(commandslist[2:])
                except ValueError as error:
                    SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)
                    return None
                if values:
                    SAY(
                        visible=visible,
                        display_message='Usage: refresh all [y|yes|--yes]',
                        log_message='Invalid refresh-all confirmation bypass',
                        log_priority=2,
                    )
                    return None
                confirm_refresh = 'yes' if yes else input(
                    "Confirm refresh all? (This will refresh data of your library files) (y/n): "
                ).lower().strip()
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


        elif commandslist == ['now']:
            _print_playback_status(now=True)

        elif commandslist == ['now*']:
            _print_playback_status(detailed=True, now=True)

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
                    try:
                        fade_duration = parse_fade_duration(commandslist[2])
                        fade_in_out(fade_type=fade_type, fade_duration=fade_duration)
                    except ValueError as error:
                        SAY(visible=visible,
                            display_message=str(error),
                            log_message=str(error),
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
                try:
                    target = parse_seek_target(
                        commandslist[1:],
                        position=get_current_progress(),
                        duration=float(currentsong_length),
                    )
                    if song_seek(timeval=target.seconds):
                        IPrint(f"Seeking to: {target.display}", visible=visible)
                    else:
                        raise SeekSyntaxError("The current source rejected the seek operation")
                except SeekSyntaxError as error:
                    SAY(
                        visible=visible,
                        display_message=f"Error: {error}",
                        log_message=f"Seek command rejected: {error}",
                        log_priority=2,
                    )
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
            _print_playback_status(detailed=commandslist[0].endswith('*'))

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
            try:
                assume_yes, download_values = _confirmation_bypass(commandslist[1:])
            except ValueError as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)
                return None
            if len(download_values) > 1:
                SAY(
                    visible=visible,
                    display_message='Usage: download-yv [YouTube URL] [y|yes|--yes]',
                    log_message='Invalid video-download confirmation bypass',
                    log_priority=2,
                )
                return None
            commandslist = [commandslist[0], *download_values]

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
                    confirm_dl = 'yes' if assume_yes else input(
                        "Do you want to confirm VIDEO download? (y/n): "
                    ).lower().strip()
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

        elif commandslist[0].lower() in {'dl', 'download-ml'}:
            try:
                if commandslist[0].lower() == 'dl':
                    download_shortcut_command(commandslist[1:])
                else:
                    download_media_link_command(commandslist[1:])
            except (DownloadError, ValueError) as error:
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

        elif commandslist in (['reset'], ['.reset']):
            try:
                if not reset_playback(start_playing=commandslist == ['.reset']):
                    raise RuntimeError('No seekable audio is loaded')
            except Exception:
                SAY(visible=visible, display_message="Error: Can't reset this audio",
                    log_message=f'Error in resetting: {currentsong}', log_priority=2)

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
                               _blocked_label(
                                   _sound_files_names_only[(song_index_entered)-1],
                                   _library_media(song_index_entered),
                               )+\
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
                if isinstance(currentsong, str) and currentsong and current_media_type is None:
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

        elif commandslist[0] in {'bl', 'blacklisted'}:
            try:
                preference_command(
                    commandslist[1:],
                    PreferenceState.BLOCKED,
                )
            except ValueError as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)

        elif commandslist[0] in {'favs', 'blacklist'}:
            try:
                arguments = commandslist[1:]
                if commandslist[0] == 'favs' and arguments == ['list']:
                    arguments = []
                list_preferences(
                    PreferenceState.FAVORITE if commandslist[0] == 'favs' else PreferenceState.BLOCKED,
                    arguments,
                    default_limit=None if commandslist[0] == 'favs' else MAX_RESULT_COUNT,
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
            elif commandslist[1] == 'edit':
                try:
                    yes, values = _confirmation_bypass(commandslist[2:])
                    if values:
                        raise ValueError('Usage: lyrics edit [y|yes|--yes]')
                    edit_current_lyrics(assume_yes=True) if yes else edit_current_lyrics()
                except ValueError as error:
                    SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)
            else:
                SAY(
                    visible=visible,
                    display_message='Usage: lyrics [edit [y|yes|--yes]]',
                    log_message='Invalid lyrics command',
                    log_priority=2,
                )

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
                query_parts = commandslist[1:]
                # Presentation flags have already been removed by the typed parser.
                # Keep the established quoted-query/count distinction.
                quoted_query = re.search(r'["\']', command)
                if quoted_query and query_parts:
                    qr_val = query_parts[0]
                    rescount = ' '.join(query_parts[1:])
                else:
                    rescount = query_parts[-1] if len(query_parts) > 1 and query_parts[-1].isnumeric() else ''
                    qr_val = ' '.join(query_parts[:-1] if rescount else query_parts)

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
                    choose_media_url(media_url_choices=ytv_choices,
                                     **_presentation_options(presentation))

            except PlaybackBlockedError as error:
                SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)
            except Exception as error:
                report_youtube_error(error, 'search/playback')

        elif commandslist[0].lower() in ['/yl', '/youtube-link']:
            YOUTUBE_PLAY_TYPE = 0
            if len(commandslist) == 2:
                media_url = commandslist[1]
                if id_if_url_is_of_yt_format(media_url):
                    try:
                        play_vas_media(media_url=media_url, single_video=True,
                                       **_presentation_options(presentation))
                    except PlaybackBlockedError as error:
                        SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)
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
                        play_vas_media(media_url=commandslist[1], media_type='general',
                                       **_presentation_options(presentation))
                    except PlaybackBlockedError as error:
                        SAY(visible=visible, display_message=str(error), log_message=str(error), log_priority=2)
                    except Exception as error:
                        stopsong()
                        if isinstance(error, MediaFailure) and error.code != FailureCode.DECODE:
                            message = str(error)
                        else:
                            message = "The media link could not be decoded or played"
                        message = display_media_error(message)
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

        elif commandslist[0].lower() == 'hotspots':
            try:
                hotspots_command(commandslist[1:])
            except (ValueError, OSError, SQLiteError) as error:
                IPrint(str(error), visible=visible)

        elif commandslist[0].lower() == 'tag':
            try:
                tag_command(commandslist[1:])
            except (TagError, ValueError, PlaybackBlockedError) as error:
                IPrint(str(error), visible=visible)

        elif commandslist[0].lower() == 'transfer':
            try:
                transfer_command(commandslist[1:])
            except (CollectionTransferError, PlaylistError, ValueError, IndexError) as error:
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
                if commandslist[0].lower() == 'like':
                    changed = PREFERENCES.set(media, PreferenceState.FAVORITE)
                else:
                    changed = PREFERENCES.set_blocked(media)
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



def prompt_text():
    """Build the testing snapshot's richer two-line prompt from live state."""
    status_projection = _playback_status_projection()
    has_active_label = status_projection.media_id is not None and status_projection.display_state != 'Stopped'
    if has_active_label:
        title = _status_media_label(status_projection)
        prefix = f'[{status_projection.library_index}] ' if status_projection.library_index else ''
        first = (
            colored.fg('light_slate_blue') + '┏━' +
            colored.fg('navajo_white_1') +
            f' {prefix}{text_overflow_prettify(str(title), 64)} '
            f'[{_status_source_label(status_projection).lower()}]'
        )
        state = {
            'Playing': 'playing ▶',
            'Paused': 'paused Ⅱ',
            'Buffering': 'buffering …',
            'Resolving': 'resolving …',
            'Seeking': 'seeking …',
            'Crossfading': 'crossfading',
            'Failed': 'failed !',
            'Stopping': 'stopping …',
            'Finished': 'finished',
        }.get(status_projection.display_state, status_projection.display_state.lower())
        if status_projection.live:
            status = f'LIVE ━ {_status_time(status_projection.position_seconds)} ━ {state}'
        elif status_projection.duration_seconds is not None:
            status = (
                f'{_status_time(status_projection.position_seconds)} ━ '
                f'{_status_time(status_projection.duration_seconds)} ━ '
                f'{status_projection.percent:>3.0f}% ━ {state}'
            )
        else:
            status = f'{_status_time(status_projection.position_seconds)} ━ duration ? ━ {state}'
        if status_projection.queue_position is not None:
            status += f' ━ Q {status_projection.queue_position}/{status_projection.queue_count}'
        if chapter_label := _status_chapter_label(status_projection.chapter):
            status += f' ━ {truncate_display_cells(chapter_label, 36)}'
        if status_projection.safe_error:
            status += f' ━ {truncate_display_cells(status_projection.safe_error, 48)}'
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
    DESKTOP_CONTROL.start_request_listener(_desktop_control_request)
    DESKTOP_CONTROL.start_playback_monitor(_playback_status_projection)
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
        'close_button_behavior': _configured_desktop_close_behavior(SETTINGS),
    })
    homepage_projection = HOMEPAGE.snapshot()
    DESKTOP_CONTROL.emit('homepage', dict(homepage_projection))
    DESKTOP_CONTROL.emit('artwork', ARTWORK.projection().to_dict())
    if homepage_projection['online_enabled']:
        HOMEPAGE.refresh_async()
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

    if visible:
        showbanner()
        if homepage_projection['show_on_startup'] and not getattr(DESKTOP_CONTROL, 'enabled', False):
            _print_homepage(homepage_projection)
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

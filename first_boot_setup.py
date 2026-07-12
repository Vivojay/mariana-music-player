"""Interactive, resumable first-run setup."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import uuid
from pathlib import Path

from mariana.paths import runtime_paths
from mariana.setup import SetupStateError, SetupStateStore

APP_DIR = Path(__file__).resolve().parent
HTTP_TIMEOUT = (10, 60)


def _answer(prompt: str) -> bool:
    response = input(prompt).casefold().strip()
    while response not in {"y", "n", "yes", "no"}:
        response = input(f"[INVALID RESPONSE] {prompt}").casefold().strip()
    return response in {"y", "yes"}


def _path_key(value: str | Path) -> str:
    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    return os.path.normcase(os.path.realpath(expanded))


def _save_library_paths(paths: list[str]) -> None:
    destination = runtime_paths().library_file
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing = destination.read_text(encoding="utf-8").splitlines() if destination.exists() else []
    known = {_path_key(line) for line in existing if line.strip() and not line.lstrip().startswith("#")}
    output = list(existing)
    for value in paths:
        if (key := _path_key(value)) not in known:
            output.append(str(Path(value).expanduser().resolve()))
            known.add(key)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".lib.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("\n".join(output).rstrip() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def download_cloud_mariana_samples(about):
    import zipfile

    import requests
    from ruamel.yaml import YAML
    from tqdm.auto import tqdm

    from beta.mediadl import setup_dl_dir

    with runtime_paths().settings.open(encoding="utf-8") as stream:
        settings = YAML(typ="safe").load(stream)
    download_directory = setup_dl_dir(settings, about)
    if download_directory in range(4):
        return download_directory

    root = Path(download_directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    archive_path = root / f".mariana-samples-{os.getpid()}.zip"
    staging = root / f".mariana-samples-{uuid.uuid4().hex}.staging"
    destination = root / "mariana_music_samples"
    sample_url = "https://www.dropbox.com/s/s2cgmuwadkrsjl7/Mariana%20Cloud%20Music%20Collection.zip?dl=1"

    try:
        response = requests.get(sample_url, stream=True, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 178238582)
        with archive_path.open("wb") as output, tqdm(
            desc="", total=total, unit="iB", unit_scale=True, unit_divisor=1024, ncols=60
        ) as progress:
            for data in response.iter_content(chunk_size=1024):
                if data:
                    progress.update(output.write(data))
        if not zipfile.is_zipfile(archive_path):
            raise zipfile.BadZipFile("The sample download was not a valid zip archive")
        staging.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            staging_root = staging.resolve()
            for member in archive.infolist():
                member_path = (staging_root / member.filename).resolve()
                if not member_path.is_relative_to(staging_root) or stat.S_ISLNK(member.external_attr >> 16):
                    raise zipfile.BadZipFile(f"Unsafe path in sample archive: {member.filename}")
            archive.extractall(staging)
        if destination.exists():
            shutil.rmtree(staging)
        else:
            os.replace(staging, destination)
        return destination
    finally:
        archive_path.unlink(missing_ok=True)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _recover(store: SetupStateStore) -> bool:
    try:
        state = store.load()
    except SetupStateError as error:
        print(f"Setup state is corrupt: {error}")
        choice = input("Repair setup state and restart setup? (y/n): ").casefold().strip()
        if choice not in {"y", "yes"}:
            return False
        store.repair()
        return True
    if state.status not in {"failed", "in_progress"}:
        return True
    print(f"Previous setup did not complete (step: {state.current_step or 'unknown'}).")
    choice = input("[R]esume, re[S]tart, or [Q]uit setup? ").casefold().strip()
    while choice not in {"r", "resume", "s", "restart", "q", "quit"}:
        choice = input("Please enter R, S, or Q: ").casefold().strip()
    if choice in {"q", "quit"}:
        return False
    if choice in {"s", "restart"}:
        store.reset()
    return True


def fbs(about, store: SetupStateStore | None = None):
    """Run or resume first boot; return True when the player should not start."""
    store = store or SetupStateStore()
    if not _recover(store):
        return True
    with store.lock():
        state = store.load()
        if state.status == "complete":
            return False
        greet = f"Welcome to Mariana Player v{about['ver']['maj']}.{about['ver']['min']}.{about['ver']['rel']}"
        print(f"\n\n{'=' * (len(greet) + 8)}")
        print(f"||  {' ' * len(greet)}  ||\n||  {greet}  ||\n||  {' ' * len(greet)}  ||")
        print("=" * (len(greet) + 8))

        try:
            state = store.begin("library")
            if "library" not in state.completed_steps:
                directories: list[str] = []
                if _answer("Do you have any locally stored/downloaded music files? (y/n): "):
                    print('Please enter absolute music-directory paths one by one ("xxx" when done):\n')
                    index = 0
                    while True:
                        index += 1
                        value = input(f"  Enter directory path {index} ('xxx' to exit): ").strip()
                        if value.casefold() == "xxx":
                            break
                        expanded = Path(os.path.expandvars(value)).expanduser()
                        if expanded.is_dir():
                            directories.append(str(expanded.resolve()))
                        else:
                            print("This directory does not exist, please retry...")
                _save_library_paths(directories)
                state = store.complete_step("library")

            store.begin("samples")
            if "samples" not in state.completed_steps:
                if _answer(
                    "Would you like to download a signature collection of 25 sample songs by Mariana\n"
                    "(SPACE REQUIRED: 170MB)? (y/n): "
                ):
                    download_cloud_mariana_samples(about)
                state = store.complete_step("samples")

            store.begin("launch")
            run_now = _answer("\n\nWould you like to run Mariana Player now? (y/n) ")
            store.complete_step("launch")
            store.complete()
            print("\nOk, done!")
            if not run_now:
                print("Mariana Player has been installed successfully for you...")
            return not run_now
        except (KeyboardInterrupt, EOFError):
            raise
        except Exception as error:
            try:
                step = store.load().current_step
            except SetupStateError:
                step = None
            store.fail(step, error)
            raise

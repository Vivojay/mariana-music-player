"""Validate and bundle this host's frozen CLI/TUI and browser-player executables."""
import hashlib
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from check_web_release import verify

ROOT = Path(__file__).resolve().parents[1]


def main():
    src = ROOT / 'build/native'
    out = ROOT / 'build/portable'
    out.mkdir(parents=True, exist_ok=True)
    ext = '.exe' if os.name == 'nt' else ''
    cli = src / f'mariana-cli{ext}'
    web = src / f'Mariana-Web{ext}'
    subprocess.run([str(cli), '--help'], check=True, timeout=45)
    verify(web)
    name = f'Mariana-native-{sys.platform}-{platform.machine().lower()}'
    with tempfile.TemporaryDirectory() as work:
        directory = Path(work) / name
        directory.mkdir()
        for item in (cli, web, ROOT / 'LICENSE', ROOT / 'docs/PORTABLE_RELEASES.md'):
            shutil.copy2(item, directory / item.name)
        standard_license = Path(os.__file__).parent / 'LICENSE.txt'
        if standard_license.is_file():
            shutil.copy2(standard_license, directory / 'PYTHON-LICENSE.txt')
        distribution = importlib.metadata.distribution('pyinstaller')
        for source in distribution.files or ():
            if source.name == 'COPYING.txt':
                shutil.copy2(str(distribution.locate_file(source)), directory / 'PYINSTALLER-LICENSE.txt')
                break
        fmt = 'zip' if os.name == 'nt' else 'gztar'
        result = Path(shutil.make_archive(str(out / name), fmt, root_dir=work, base_dir=name))
    (out / (result.name + '.sha256')).write_bytes(
        f'{hashlib.sha256(result.read_bytes()).hexdigest()}  {result.name}\n'.encode()
    )
    print(result)


if __name__ == '__main__':
    main()

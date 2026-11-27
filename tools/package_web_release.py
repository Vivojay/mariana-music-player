"""Build the portable Mariana web player and reproducible release archives."""
import argparse
import hashlib
from pathlib import Path
import os
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from build_web_player import build

ROOT = Path(__file__).resolve().parents[1]


def archive(target, files, *, executable=False):
    with target.open('wb') as stream:
        if executable:
            stream.write(b'#!/usr/bin/env python3\n')
        with ZipFile(stream, 'w') as bundle:
            for name, path in sorted(files.items()):
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (0o100644 << 16)
                data = path.read_bytes()
                if path.suffix == '.cmd':
                    data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
                bundle.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=9)
    if executable:
        target.chmod(0o755)


def package(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as work:
        work = Path(work)
        site = work / 'web-player'
        build(site)
        assets = {p.relative_to(site).as_posix(): p for p in site.rglob('*') if p.is_file()}
        pyz, static = work / 'Mariana-Web.pyz', work / 'Mariana-Web-static.zip'
        license_path = ROOT / 'LICENSE'
        archive(pyz, {'__main__.py': ROOT / 'packaging/web/portable_web.py', 'LICENSE': license_path,
                      **{'web-player/' + n: p for n, p in assets.items()}}, executable=True)
        archive(static, {**assets, 'LICENSE': license_path})
        windows = work / 'Mariana-Web-Windows.zip'
        archive(windows, {'Mariana-Web.pyz': pyz, 'Open-Mariana.cmd': ROOT / 'packaging/web/Open-Mariana.cmd',
                          'WindowsWeb.cs': ROOT / 'packaging/web/WindowsWeb.cs', 'LICENSE': license_path})
        sums = work / 'Mariana-Web-SHA256SUMS.txt'
        sums.write_bytes(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'
                                 for p in (pyz, static, windows)).encode())
        for path in (pyz, static, windows, sums):
            target = output / path.name
            os.replace(path, target)
            print(target.resolve())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/portable')
    package(parser.parse_args().output)

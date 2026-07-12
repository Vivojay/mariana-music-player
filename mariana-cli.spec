# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path.cwd()
datas = [
    (str(root / "version.json"), "."),
    (str(root / "settings" / "system.toml"), "settings"),
    (str(root / "settings" / "settings.yml.default"), "settings"),
    (str(root / "lib.lib"), "."),
    (str(root / "user" / "user_data.yml"), "user"),
    (str(root / "res"), "res"),
    (str(root / "tools" / "manifest.json"), "tools"),
]

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "sounddevice",
        "yt_dlp",
        "watchdog.observers",
        "beta.YT_query",
        "beta.IPrint",
        "beta.podcasts",
        "lyrics_provider.get_lyrics",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mariana-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

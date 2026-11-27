# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

root = Path.cwd()
datas = [
    (str(root / "desktop" / "culture_sources.json"), "desktop"),
    *[(str(root / "web" / "player" / name), "web/player")
      for name in ("command-input.js", "command-input.css", "effect-studio.js", "effect-worklet.js", "strudel-pattern.js", "companion.html", "companion.js", "companion.css", "companion-flow.js",
                   "companion-console.js", "companion-console.css", "companion-home.js", "companion-home.css",
                   "companion-collections.js", "companion-collections.css", "companion-similar.js", "companion-similar.css", "platform.js", "player.css", "share-link.html", "snap-share.html", "public-share.js")],
    (str(root / "version.json"), "."),
    *[(str(root / "mariana" / name), "mariana")
      for name in ("command_grammar_core.json", "command_grammar_studio.json", "effect_plugin.py")],
    (str(root / "mariana" / "tone_bank.json"), "mariana"),
    (str(root / "mariana" / "video_filters.json"), "mariana"),
    (str(root / "mariana" / "theme_presets.json"), "mariana"),
    (str(root / "mariana" / "connection_providers.json"), "mariana"),
    (str(root / "settings" / "system.toml"), "settings"),
    (str(root / "settings" / "settings.yml.default"), "settings"),
    (str(root / "lib.lib"), "."),
    (str(root / "user" / "user_data.yml"), "user"),
    (str(root / "res"), "res"),
    (str(root / "tools" / "render_strudel.mjs"), "tools"),
    (str(root / "tools" / "manifest.json"), "tools"),
    (str(root / "tools" / "bootstrap-manifest.json"), "tools"),
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
        "pypresence",
        "beta.YT_query",
        "beta.IPrint",
        "beta.podcasts",
        "lyrics_provider.get_lyrics",
    ] + (["comtypes", "pycaw.pycaw"] if os.name == "nt" else []),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pedalboard"],
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

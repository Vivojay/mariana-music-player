"""Build the static PWA and both mobile bundles from the same sources."""
import argparse
import base64
import hashlib
import html
import json
import math
import os
import re
import struct
import sys
import webbrowser
import zlib
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def icon(size):
    """Draw Mariana's three-wave mark as an opaque RGB PNG with no dependencies."""
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            dx = (x + 0.5) / size
            dy = (y + 0.5) / size
            wave = 0.053 * math.sin((dx - 0.16) * math.tau * 1.65)
            distance = min(abs(dy - line - wave) for line in (0.38, 0.5, 0.62))
            alpha = max(0, min(1, (0.019 - distance) * size, (dx - 0.17) * size, (0.83 - dx) * size))
            rows.extend(round(bg + alpha * (fg - bg)) for bg, fg in zip((12, 15, 26), (108, 245, 210), strict=True))

    def chunk(tag, value):
        return struct.pack('>I', len(value)) + tag + value + struct.pack('>I', zlib.crc32(tag + value))

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, level=9)) + chunk(b'IEND', b''))


def build(destination):
    source = ROOT / 'web' / 'player'
    palettes = json.loads((ROOT / 'mariana/theme_presets.json').read_bytes())
    assets = {name: (source / name).read_bytes() for name in
              ('workspace.js', 'workspace.css', 'platform.js', 'command-input.js', 'command-input.css', 'command-match.js', 'completion-values.js', 'voice.js', 'share-link.html', 'public-share.js', 'snap-share.html', 'companion.js', 'player.css', 'clip.css', 'dj.css', 'dj.js', 'dj-engine.js', 'dj-recorder.js', 'clip-media.js', 'clip-story.js', 'clip-share.js', 'clip.js', 'directory.js', 'jams.js', 'listener-profiles.js', 'accounts.js', 'accounts.css', 'catalog.js', 'wall.js', 'index.html', 'player.js', 'strudel-pattern.js', 'strudel.js', 'tone-keys.css', 'tone-procedures.js', 'tone.js', 'speech-dsp.js', 'speech-capture.js', 'effect-studio.js', 'effect-worklet.js', 'speech-worklet.js', 'transcripts.js', 'karaoke.js', 'karaoke.css', 'karaoke-hash.js', 'karaoke-ttml.js', 'karaoke-mix.js', 'karaoke-invite.js', 'manifest.webmanifest')}
    for name in ('video-filters.js', 'video-filters.css'):
        assets[name] = (source / name).read_bytes()
    assets['video-presets.js'] = (b'globalThis.MarianaVideoPresets = '
                                 + (ROOT / 'mariana/video_filters.json').read_bytes() + b';\n')
    grammar = []
    for path in sorted((ROOT / 'mariana').glob('command_grammar_*.json')):
        rows = json.loads(path.read_bytes())['commands']
        grammar.extend(row for row in rows if row.get('surface', 'native') in ('portable', 'both'))
    if not grammar:
        raise ValueError('Portable command grammar is missing.')
    assets['command-grammar.js'] = ('globalThis.MarianaPortableGrammar = ' + json.dumps(grammar, separators=(',', ':')) + ';\n').encode()
    starter = (ROOT / 'res/strudel/starter.js').read_text(encoding='utf-8')
    assets['index.html'] = assets['index.html'].replace(b'__STRUDEL_STARTER__', html.escape(starter, quote=False).encode())
    duet = ROOT / 'res/karaoke'
    sample = {'audio': base64.b64encode((duet / 'practice-duet.wav').read_bytes()).decode('ascii'),
              'sheet': json.loads((duet / 'practice-duet.json').read_bytes())}
    assets['practice-duet.js'] = ('window.MARIANA_PRACTICE_DUET = ' + json.dumps(sample) + ';\n').encode()
    assets['themes.js'] = ('window.MARIANA_THEMES = ' + json.dumps(palettes) + ';\n').encode()
    assets['tone-bank.js'] = b'globalThis.MarianaToneBank = ' + (ROOT / 'mariana/tone_bank.json').read_bytes() + b';\n'
    # Keep the static build dependency-free when invoked directly by file path.
    import runpy
    bank = runpy.run_path(str(ROOT / 'mariana/wavetables.py'))
    coefficients = {name: bank['spectrum'](name) for name in bank['names']()}
    assets['soundbank-data.js'] = ('globalThis.MarianaTableBank = ' + json.dumps(coefficients, separators=(',', ':')) + ';\n').encode()
    assets['soundbank.js'] = (source / 'soundbank.js').read_bytes()
    directory = (ROOT / 'desktop/culture_sources.json').read_bytes()
    providers = json.loads((ROOT / 'mariana/connection_providers.json').read_bytes())
    public_id = os.environ.get('MARIANA_SPOTIFY_WEB_CLIENT_ID', '').strip()
    # Only the installation owner can designate a trusted conference origin for embedding.
    meeting = os.environ.get('MARIANA_JITSI_ORIGIN', '').strip()
    if meeting:
        parts = urlsplit(meeting)
        if not (parts.scheme == 'https' and re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]+)?', parts.netloc)
                and parts.path in ('', '/') and not parts.query and not parts.fragment):
            raise ValueError('MARIANA_JITSI_ORIGIN must be an HTTPS origin, e.g. https://meet.example.org')
        if parts.port == 0:
            raise ValueError('MARIANA_JITSI_ORIGIN needs a valid HTTPS port')
        meeting = ('https://' + parts.netloc.lower()).rstrip('/')
    assets['meeting-config.js'] = ('window.MarianaMeetingOrigin = ' + json.dumps(meeting) + ';\n').encode()
    assets['account-providers.json'] = json.dumps(providers).encode()
    assets['account-config.js'] = ('window.MarianaAccountConfig = ' + json.dumps({
        'providers': providers, 'spotifyClientId': public_id,
        'snapchatClientId': os.environ.get('MARIANA_SNAPCHAT_WEB_CLIENT_ID', '').strip(),
    }) + ';\n').encode()
    assets['directory.json'] = directory
    assets['directory-data.js'] = b'window.MARIANA_SOURCES = ' + directory + b';\n'
    for size in (192, 512):
        assets[f'icon-{size}.png'] = icon(size)
    strudel = ROOT / 'build/strudel-runtime'
    has_full_strudel = (strudel / 'index.html').is_file() and (strudel / 'runtime.js').is_file()
    assets['strudel-engine.json'] = json.dumps({'full': has_full_strudel}).encode()
    strudel_shell = ['./strudel-engine.json']
    if has_full_strudel:
        # Built from the pinned Electron lock by tools/bundle_strudel_web.mjs.
        for module in sorted(strudel.rglob('*')):
            if module.is_symlink() or not module.is_file():
                continue
            name = 'strudel-runtime/' + module.relative_to(strudel).as_posix()
            assets[name] = module.read_bytes()
            if module.suffix != '.map':
                strudel_shell.append('./' + name)
    worker = (source / 'sw.js').read_bytes()
    revision = hashlib.sha256(worker + b''.join(assets.values())).hexdigest()[:16]
    assets['sw.js'] = worker.replace(b'__REVISION__', revision.encode()).replace(
        b'/*__STRUDEL_ASSETS__*/', b''.join(b',' + json.dumps(asset).encode() for asset in strudel_shell)
    )
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in assets.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    print(f'Built {len(assets)} assets in {destination}')


def apple_icons():
    image = icon(1024)
    base = ROOT / 'build/apple-icons'
    info = {'info': {'version': 1, 'author': 'mariana'}}
    for platform in ('ios', 'watchos'):
        assets = base / f'{platform}.xcassets'
        app = assets / 'AppIcon.appiconset'
        app.mkdir(parents=True, exist_ok=True)
        (assets / 'Contents.json').write_text(json.dumps(info), encoding='utf-8')
        entry = {'filename': 'Mariana.png', 'idiom': 'universal', 'platform': platform, 'size': '1024x1024'}
        (app / 'Contents.json').write_text(json.dumps({**info, 'images': [entry]}), encoding='utf-8')
        (app / 'Mariana.png').write_bytes(image)


class PlayerRequest(SimpleHTTPRequestHandler):
    # Windows file associations can otherwise give the service worker an invalid MIME type.
    extensions_map: ClassVar[dict[str, str]] = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".webmanifest": "application/manifest+json",
    }

    def do_POST(self):
        if self.path in ('/api/accounts', '/api/jam'):
            # Building and serving the portable shell requires only the standard library.
            # Load the native account dependencies only for this local integration.
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            try:
                from mariana.connections_http import handle_accounts_post, handle_jam_post
            except ImportError:
                self.send_error(503, 'Native account dependencies unavailable')
                return
            (handle_jam_post if self.path == '/api/jam' else handle_accounts_post)(self)
            return
        self.send_error(404)

    def do_GET(self):
        if self.path.partition('?')[0] == '/favicon.ico':
            self.send_response(302)
            self.send_header('Location', '/icon-192.png')
            self.end_headers()
            return
        super().do_GET()


def serve(destination, port, view=None, open_browser=False):
    """Serve the built player from its absolute path, independently of the shell directory."""
    directory = destination.resolve()
    if not (directory / 'index.html').is_file():
        raise SystemExit(f'Cannot serve Mariana: index.html is missing from {directory}')
    if not 0 <= port <= 65535:
        raise SystemExit('Choose a port between 0 and 65535 (0 picks an available port).')
    handler = partial(PlayerRequest, directory=str(directory))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', port), handler)
    except OSError as error:
        raise SystemExit(f'Cannot start the player on port {port}: {error}. Try --port 8768.') from error
    with server:
        address = f'http://127.0.0.1:{server.server_port}/'
        if view:
            address += f'?view={view}'
        print(f'Mariana is ready at {address}', flush=True)
        print(f'Serving {directory}. Press Ctrl+C to stop.', flush=True)
        try:
            if open_browser:
                webbrowser.open(address)
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/web-player')
    parser.add_argument('--apple-icons', action='store_true', help='Generate the Xcode asset catalogs as well.')
    parser.add_argument('--serve', action='store_true', help='Launch the built player on localhost.')
    parser.add_argument('--port', type=int, default=8767, help='Local web port for --serve (default: 8767).')
    parser.add_argument('--view', choices=('console', 'flow', 'voice'), help='Initial browser view.')
    parser.add_argument('--open', action='store_true', help='Open the ready address in your default browser.')
    args = parser.parse_args()
    if (args.view or args.open) and not args.serve:
        parser.error('--view and --open require --serve')
    build(args.output)
    if args.apple_icons:
        apple_icons()
    if args.serve:
        serve(args.output, args.port, args.view, args.open)

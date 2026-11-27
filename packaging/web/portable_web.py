"""Serve the bundled Mariana browser player on a stable loopback origin."""
import argparse
from functools import partial
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import webbrowser
from zipfile import ZipFile

MIME = {
    '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
    '.html': 'text/html; charset=utf-8', '.json': 'application/json', '.png': 'image/png',
    '.webmanifest': 'application/manifest+json', '.svg': 'image/svg+xml',
    '.wav': 'audio/wav', '.wasm': 'application/wasm', '.ico': 'image/x-icon',
}


def load_assets():
    if getattr(sys, 'frozen', False):
        directory = Path(sys._MEIPASS, 'web-player')
        files = {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    else:
        with ZipFile(sys.argv[0]) as bundle:
            files = {k.removeprefix('web-player/'): bundle.read(k) for k in bundle.namelist()
                     if k.startswith('web-player/') and not k.endswith('/')}
    if 'index.html' not in files or 'sw.js' not in files:
        raise ValueError('The portable release is missing its player assets.')
    return {name: (body, '"' + sha256(body).hexdigest() + '"') for name, body in files.items()}


class Player(BaseHTTPRequestHandler):
    def __init__(self, *args, assets, **kwargs):
        self.assets = assets
        super().__init__(*args, **kwargs)

    def allowed_host(self):
        port = self.server.server_port
        allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if port == 80:
            allowed.update(('127.0.0.1', 'localhost'))
        return self.headers.get('Host', '').lower() in allowed

    def reply(self, status, content_type, data=b'', etag=None):
        self.send_response(status)
        self.send_header('Cache-Control', 'no-cache' if etag else 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        if etag:
            self.send_header('ETag', etag)
        if status != 304:
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if self.command != 'HEAD' and data:
            self.wfile.write(data)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.allowed_host():
            self.reply(403, 'text/plain', b'Use the local address printed by Mariana.')
            return
        path = self.path.partition('?')[0]
        if path == '/healthz':
            self.reply(200, 'application/json', b'{"status":"ready","surface":"web"}')
            return
        name = {'/': 'index.html', '/favicon.ico': 'icon-192.png'}.get(path, path.removeprefix('/'))
        if name not in self.assets:
            self.reply(404, 'text/plain', b'File not found')
            return
        data, etag = self.assets[name]
        if self.headers.get('If-None-Match') == etag:
            self.reply(304, '', etag=etag)
            return
        self.reply(200, MIME.get(Path(name).suffix.lower(), 'application/octet-stream'), data, etag)

    def do_POST(self):
        path = self.path.partition('?')[0]
        if self.allowed_host() and path in ('/api/accounts', '/api/jam'):
            error = 'The native account and room bridge requires the Mariana Python player. Start tools/build_web_player.py --serve from a checkout with its dependencies installed.'
            self.reply(503, 'application/json', json.dumps({'error': error}).encode())
        else:
            self.reply(404, 'text/plain', b'File not found')

    def log_message(self, format, *args):
        # OAuth callbacks may carry a code in the query string.
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767, help='default 8767; port 0 is useful for testing')
    parser.add_argument('--view', choices=('console', 'flow', 'voice'), default=None,
                        help='choose an initial view or restore the saved preference')
    parser.add_argument('--no-open', action='store_true', help='print the address without launching a browser')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('port must be between 0 and 65535')
    handler = partial(Player, assets=load_assets())
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    except OSError as error:
        parser.exit(1, f'Could not start Mariana on port {args.port} ({error}). Close the previous server or pass --port 8768.\n')
    with server:
        url = f'http://127.0.0.1:{server.server_port}/' + (f'?view={args.view}' if args.view else '')
        print(f'Mariana is ready at {url}', flush=True)
        print('Press Ctrl+C in this window to quit.', flush=True)
        if not args.no_open:
            try:
                webbrowser.open(url)
            except webbrowser.Error:
                pass
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()

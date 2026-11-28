"""Exercise the packaged browser player from another directory over real HTTP."""
import argparse
import http.client
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def verify(artifact):
    artifact = artifact.resolve()
    command = ([sys.executable, str(artifact)] if artifact.suffix == '.pyz' else [str(artifact)])
    with tempfile.TemporaryDirectory() as work:
        process = subprocess.Popen([*command, '--no-open', '--view', 'flow', '--port', '0'],
                                   cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output = process.stdout
        try:
            if output is None:
                raise RuntimeError("The packaged server output could not be opened.")
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(output.readline()), daemon=True).start()
            try:
                first = lines.get(timeout=45)
            except queue.Empty as exc:
                raise RuntimeError('Timed out waiting for the packaged server.') from exc
            prefix = 'Mariana is ready at '
            if not first.startswith(prefix):
                raise RuntimeError(first or 'The packaged server exited before startup.')
            url = urlsplit(first[len(prefix):].strip())
            if url.query != 'view=flow' or url.hostname != '127.0.0.1':
                raise RuntimeError('The requested Flow view did not start on loopback.')
            origin = f'http://{url.netloc}'

            def get(path, content_type):
                with urlopen(origin + path, timeout=8) as response:
                    assert response.status == 200
                    assert response.headers.get_content_type() == content_type
                    return response.read()

            assert json.loads(get('/healthz', 'application/json'))['status'] == 'ready'
            assert b'player.js' in get('/', 'text/html')
            assert b'__REVISION__' not in get('/sw.js', 'text/javascript')
            assert json.loads(get('/manifest.webmanifest', 'application/manifest+json'))['name']
            assert get('/icon-192.png', 'image/png').startswith(b'\x89PNG')
            with urlopen(Request(origin + '/player.js', method='HEAD'), timeout=8) as reply:
                assert reply.status == 200 and reply.headers['Content-Length'] and not reply.read()
                tag = reply.headers['ETag']
            try:
                urlopen(Request(origin + '/player.js', headers={'If-None-Match': tag}), timeout=8).close()
            except HTTPError as exc:
                assert exc.code == 304
            else:
                raise AssertionError('Missing cache revalidation')
            client = http.client.HTTPConnection('127.0.0.1', url.port, timeout=8)
            try:
                client.request('GET', '/', headers={'Host': 'other.invalid'})
                assert client.getresponse().status == 403
            finally:
                client.close()
            try:
                urlopen(Request(origin + '/api/accounts', data=b'{}'), timeout=8).close()
            except HTTPError as exc:
                assert exc.code == 503 and 'native' in json.load(exc)['error'].lower()
            else:
                raise AssertionError('A standalone web bundle must identify the unavailable native bridge.')
        finally:
            if os.name == 'nt' and process.poll() is None:
                # A frozen one-file executable starts a separate runtime process.
                subprocess.run(['taskkill', '/t', '/f', '/pid', str(process.pid)], capture_output=True)
            elif process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if output is not None:
                output.close()
    print(f'Packaged player smoke test passed: {artifact.name}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact', type=Path)
    verify(parser.parse_args().artifact)

"""Exercise the documented launcher from a different working directory."""
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import ProxyHandler, build_opener

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("view", [None, "flow", "voice"])
def test_launcher_builds_and_serves_from_an_unrelated_workdir(tmp_path, view):
    target = tmp_path / "Mariana player"
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "tools/build_web_player.py"), "--serve", "--port", "0", "--output", str(target),
         *(["--view", view] if view else [])],
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        assert proc.stdout is not None
        assert "Built" in proc.stdout.readline()
        url = proc.stdout.readline().strip().split()[-1]
        assert url.startswith("http://127.0.0.1:")
        if view:
            assert url.endswith("/?view=" + view)
        browser = build_opener(ProxyHandler({}))
        with browser.open(url, timeout=4) as response:
            assert response.status == 200
            assert response.read() == (target / "index.html").read_bytes()
        for asset, content_type in (("sw.js", "text/javascript"), ("manifest.webmanifest", "application/manifest+json")):
            with browser.open(urljoin(url, asset), timeout=4) as response:
                assert response.headers.get_content_type() == content_type
                assert response.read() == (target / asset).read_bytes()
        with browser.open(urljoin(url, "favicon.ico"), timeout=4) as response:
            assert response.read() == (target / "icon-192.png").read_bytes()
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        if proc.stdout:
            proc.stdout.close()

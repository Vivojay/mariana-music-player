import json

import pytest

from tools import build_web_player as player


def test_build_writes_config_and_offline_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("MARIANA_JITSI_ORIGIN", "https://Meet.Example.org/")
    player.build(tmp_path)
    assert json.loads((tmp_path / "manifest.webmanifest").read_bytes())
    assert '"https://meet.example.org"' in (tmp_path / "meeting-config.js").read_text()
    assert b"__REVISION__" not in (tmp_path / "sw.js").read_bytes()
    assert (tmp_path / "icon-192.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("origin", ["http://meet.example.org", "https://meet.example.org/path", "https://meet.example.org:0"])
def test_build_rejects_invalid_meeting_origin(tmp_path, monkeypatch, origin):
    monkeypatch.setenv("MARIANA_JITSI_ORIGIN", origin)
    with pytest.raises(ValueError, match="MARIANA_JITSI_ORIGIN"):
        player.build(tmp_path)
    assert not (tmp_path / "index.html").exists()

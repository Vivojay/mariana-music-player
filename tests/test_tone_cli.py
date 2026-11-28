import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import main


def test_tone_dispatches_with_normal_transport_and_ephemeral_metadata(monkeypatch, tmp_path):
    preview = Mock()
    monkeypatch.setattr(main, "play_local_default_player", preview)
    monkeypatch.setattr(main, "IPrint", Mock())
    with tempfile.TemporaryDirectory(dir=tmp_path) as workdir:
        monkeypatch.setattr(main, "_TONE_SESSION", SimpleNamespace(name=workdir))
        main.process("tone harmony 200 400 --seconds 0.1")
        path = Path(preview.call_args.args[0])
        media = preview.call_args.kwargs["media"]
        assert path.is_file() and path.parent == Path(workdir)
        assert media.title == "Sine harmony · 200 + 400 Hz"
        assert media.duration == 0.1 and media.provenance == "tone-generator"
        assert preview.call_args.kwargs["ephemeral"] and media.capabilities.seekable
        preview.reset_mock()
        main.process("help tone")
        assert "tone sweep" in main.IPrint.call_args.args[0]
        preview.assert_not_called()


def test_saved_arrangement_uses_same_seekable_transport(monkeypatch, tmp_path):
    preview = Mock()
    monkeypatch.setattr(main,"play_local_default_player",preview)
    monkeypatch.setattr(main,"IPrint", Mock())
    monkeypatch.setattr(main,"RUNTIME_PATHS",SimpleNamespace(state=lambda name:tmp_path/name))
    monkeypatch.setattr(main,"_TONE_SESSION",SimpleNamespace(name=str(tmp_path)))
    main.process("tone procedure play twinkle")
    media=preview.call_args.kwargs["media"]
    assert media.title=="Twinkle, Twinkle, Little Star" and media.duration==28.8
    assert media.provenance=="tone-generator" and media.capabilities.seekable
    assert preview.call_args.kwargs["ephemeral"] and Path(media.original_uri).is_file()

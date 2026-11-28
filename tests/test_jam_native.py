"""Exercise jam commands through the main native CLI, TUI and Electron command router."""
from types import SimpleNamespace


def test_jam_process_sends_then_applies_verified_cue(monkeypatch):
    import main
    from mariana import jams

    state = main.PlaybackState
    media = SimpleNamespace(title="Evening Piece", stable_id="current-media")
    snap = SimpleNamespace(state=state.PAUSED, media=media, duration=120.0, position=9.5)
    events, output, controls = [], [], []
    monkeypatch.setattr(main, "vas", SimpleNamespace(controller=SimpleNamespace(snapshot=lambda: snap)))
    monkeypatch.setattr(main, "IPrint", lambda text, **kw: output.append(text))
    monkeypatch.setattr(main, "SAY", lambda **kw: output.append(kw["display_message"]))

    def room(args):
        events.append(args)
        if args[0] == "cue":
            return {"message": "sent"}
        return {"message": "host cue", "cue": {"title": "Evening Piece", "action": "play", "seconds": 14.0}}

    def transport(operation, payload):
        controls.append((operation, payload))
        return {"ok": True}

    monkeypatch.setattr(jams, "run", room)
    monkeypatch.setattr(main, "_desktop_control_request", transport)
    main.process("jam send !Rehearsal:example")
    main.process("jam apply !Rehearsal:example")
    assert events == [["cue", "!Rehearsal:example", "pause", "9.5", "Evening Piece"], ["current", "!Rehearsal:example"]]
    assert controls == [("playback.seek", {"media_id": "current-media", "target_seconds": 14.0, "origin": "cli"}),
                        ("playback.play", {"media_id": "current-media"})]
    media.title = "Different title"
    main.process("jam sync !Rehearsal:example")
    assert len(controls) == 2
    assert "Load the matching track first" in output[-1]

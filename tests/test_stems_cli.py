from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.playback import PlaybackError
from mariana.stems import StemError, StemJobStatus, StemManifest


class FakeLease:
    def __init__(self, paths):
        self.paths = tuple(paths)
        self.released = False

    def release(self):
        self.released = True


def current_media() -> MediaRef:
    return MediaRef(
        MediaSource.URL,
        "https://public.example.test/watch/track",
        stable_id="track-1",
        title="Example Track",
        duration=180,
        capabilities=MediaCapabilities(finite=True, live=False, seekable=True, downloadable=True),
    )


@pytest.fixture
def stem_controls(monkeypatch, tmp_path):
    media = current_media()
    calls = []
    messages = []
    leases = []
    paths = {name: tmp_path / f"{name}.wav" for name in ("vocals", "drums", "bass", "other")}
    manifest = StemManifest(media.stable_id, media.title or "Track", "htdemucs", paths, 1.0)
    state = SimpleNamespace(
        media=media,
        playback=PlaybackState.PLAYING,
        manifest=manifest,
        installed=True,
        active=False,
        transitioning=False,
        job=StemJobStatus(
            state="ready", media_id=media.stable_id, title=media.title,
            model=manifest.model, available_stems=tuple(paths), progress=1.0,
        ),
    )

    def record(name, result=None):
        def invoke(*args, **kwargs):
            calls.append((name, args, kwargs))
            return result
        return invoke

    def acquire(media_id, names):
        assert media_id == media.stable_id
        lease = FakeLease(paths[name] for name in names)
        leases.append(lease)
        calls.append(("acquire", (media_id, names), {}))
        return lease

    controller = SimpleNamespace(
        snapshot=lambda: PlaybackSnapshot(state.playback, media=state.media, duration=media.duration),
        stem_analysis_source=record("source", ("https://private.example.test/audio?token=private", {})),
        configure_stem_monitor=record("monitor"),
        stem_monitor_status=lambda: {"active": state.active, "transitioning": state.transitioning},
    )
    service = SimpleNamespace(
        status=lambda: state.job,
        manifest=lambda media_id: state.manifest if media_id == media.stable_id else None,
        separator_available=lambda: state.installed,
        prepare=record("prepare", state.job),
        cancel=record("cancel", True),
        clear=record("clear", True),
        export=record("export", tuple(paths.values())),
        acquire=acquire,
    )
    monkeypatch.setattr(main, "vas", SimpleNamespace(controller=controller))
    monkeypatch.setattr(main, "STEMS", service)
    monkeypatch.setattr(main, "_STEM_SELECTION", {"media_id": None, "names": ()})
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: messages.append(str(value)))
    monkeypatch.setattr(main, "_confirm_action", lambda *_args, **_kwargs: True)
    return SimpleNamespace(
        state=state, controller=controller, service=service, calls=calls, messages=messages, leases=leases,
    )


def test_stems_prepare_is_confirmed_identity_bound_and_hides_private_input(monkeypatch):
    media = current_media()
    calls = []
    prompts = []
    service = SimpleNamespace(
        separator_available=lambda: True,
        prepare=lambda selected, source, stem_count: calls.append((selected, source, stem_count))
        or StemJobStatus(state="preparing", media_id=selected.stable_id, title=selected.title, model="htdemucs"),
    )
    monkeypatch.setattr(main, "STEMS", service)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media, duration=media.duration),
    )
    monkeypatch.setattr(
        main.vas.controller,
        "stem_analysis_source",
        lambda media_id: ("https://signed.private.test/audio?token=secret", {"Authorization": "secret"})
        if media_id == media.stable_id
        else None,
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "y")
    monkeypatch.setattr(main, "IPrint", lambda *args, **_kwargs: calls.append(("print", args)))

    result = main.stems_command(["prepare", "4"])

    assert isinstance(result, dict)
    assert result["state"] == "preparing"
    assert calls[0][0] == media
    assert calls[0][1].uri.startswith("https://signed.private.test/")
    assert calls[0][2] == "4"
    assert media.title in prompts[0]
    assert "signed.private" not in prompts[0] and "secret" not in prompts[0]


def test_stems_solo_and_karaoke_apply_prepared_paths_without_changing_media(monkeypatch, tmp_path: Path):
    media = current_media()
    paths = {}
    for name in ("vocals", "drums", "bass", "other"):
        paths[name] = tmp_path / f"{name}.wav"
        paths[name].write_bytes(b"stem")
    manifest = StemManifest(media.stable_id, media.title or "Track", "htdemucs", paths, 1.0)
    service = SimpleNamespace(
        manifest=lambda media_id: manifest if media_id == media.stable_id else None,
        acquire=lambda _media_id, names: FakeLease(paths[name] for name in names),
    )
    applied = []
    monkeypatch.setattr(main, "STEMS", service)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PAUSED, media=media, duration=media.duration),
    )
    monkeypatch.setattr(
        main.vas.controller,
        "configure_stem_monitor",
        lambda media_id, sources, **_kwargs: applied.append((media_id, tuple(sources))),
    )
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)

    assert main.stems_command(["solo", "acapella"]) == ("vocals",)
    assert applied[-1] == (media.stable_id, (paths["vocals"],))
    assert main.stems_command(["solo", "karaoke"]) == ("drums", "bass", "other")
    assert applied[-1] == (media.stable_id, (paths["drums"], paths["bass"], paths["other"]))
    with pytest.raises(StemError, match="stems mix"):
        main.stems_command(["solo", "vocals+drums"])
    main.stems_command(["original"])
    assert applied[-1] == (media.stable_id, ())


@pytest.mark.parametrize("arguments", [["prepare"], ["export", "chosen-folder"], ["clear"]])
def test_declined_stem_actions_do_not_read_transport_or_start_work(stem_controls, monkeypatch, arguments):
    monkeypatch.setattr(main, "_confirm_action", lambda *_args, **_kwargs: False)
    assert main.stems_command(arguments) is None
    assert stem_controls.calls == []
    assert "cancelled" in stem_controls.messages[-1]


def test_prepare_uses_current_identity_after_confirmation_and_explicit_model(stem_controls, monkeypatch):
    prompts = []
    monkeypatch.setattr(
        main, "_confirm_action", lambda text, **kwargs: prompts.append((text, kwargs)) or True,
    )
    result = main.stems_command(["prepare", "6", "--yes"])
    assert isinstance(result, dict)
    assert result["media_id"] == stem_controls.state.media.stable_id
    assert prompts[0][1] == {"assume_yes": True}
    assert "model weights" in prompts[0][0]
    assert [call[0] for call in stem_controls.calls] == ["source", "prepare"]
    _, (media, source), kwargs = stem_controls.calls[-1]
    assert media is stem_controls.state.media
    assert source.uri == "https://private.example.test/audio?token=private"
    assert kwargs == {"stem_count": "6"}
    assert "private.example" not in " ".join([*stem_controls.messages, prompts[0][0]])


def test_replaced_media_during_confirmation_cannot_prepare_new_transport(stem_controls, monkeypatch):
    def changed_source(media_id):
        assert media_id == stem_controls.state.media.stable_id
        raise PlaybackError("Current media changed")

    monkeypatch.setattr(stem_controls.controller, "stem_analysis_source", changed_source)
    with pytest.raises(PlaybackError, match="Current media changed"):
        main.stems_command(["prepare"])
    assert stem_controls.calls == []


@pytest.mark.parametrize("playback", [PlaybackState.IDLE, PlaybackState.STOPPING, PlaybackState.FAILED])
def test_stopped_or_failed_media_cannot_start_stem_monitor(stem_controls, playback):
    stem_controls.state.playback = playback
    with pytest.raises(StemError, match="current media"):
        main.stems_command(["solo", "vocals"])
    assert stem_controls.calls == []


@pytest.mark.parametrize("capabilities", [
    MediaCapabilities(live=True, finite=False),
    MediaCapabilities(live=False, finite=False),
])
def test_unbounded_media_refused_before_preparation_consent(stem_controls, monkeypatch, capabilities):
    stem_controls.state.media.capabilities = capabilities
    monkeypatch.setattr(main, "_confirm_action", lambda *_args, **_kwargs: pytest.fail("unexpected prompt"))
    with pytest.raises(StemError, match="live or unbounded"):
        main.stems_command(["prepare"])
    assert stem_controls.calls == []


def test_missing_separator_explained_without_installing_or_prompting(stem_controls, monkeypatch):
    stem_controls.state.installed = False
    monkeypatch.setattr(main, "_confirm_action", lambda *_args, **_kwargs: pytest.fail("unexpected prompt"))
    with pytest.raises(StemError, match="separator is not installed"):
        main.stems_command(["prepare"])
    assert stem_controls.calls == []
    main.stems_command(["status"])
    assert any("not installed" in value for value in stem_controls.messages)


@pytest.mark.parametrize("arguments", [["solo", "vocals"], ["mix", "drums", "bass"], ["original"]])
def test_monitor_failure_does_not_publish_a_new_selection(stem_controls, monkeypatch, arguments):
    previous = {"media_id": "previous-media", "names": ("other",)}
    monkeypatch.setattr(main, "_STEM_SELECTION", previous)

    def rejected(*_args, **_kwargs):
        raise PlaybackError("Current media changed")

    monkeypatch.setattr(stem_controls.controller, "configure_stem_monitor", rejected)
    with pytest.raises(StemError, match="Current media changed"):
        main.stems_command(arguments)
    assert main._STEM_SELECTION is previous
    assert stem_controls.messages == []
    assert all(lease.released for lease in stem_controls.leases)


def test_mix_updates_only_the_local_monitor_selection(stem_controls):
    assert main.stems_command(["mix", "drums", "bass"]) == ("drums", "bass")
    manifest = stem_controls.state.manifest
    lease = stem_controls.leases[-1]
    assert stem_controls.calls == [
        ("acquire", (manifest.media_id, ("drums", "bass")), {}),
        ("monitor", (manifest.media_id, (manifest.stems["drums"], manifest.stems["bass"])), {"lease": lease}),
    ]
    assert not lease.released  # The decoder owns the pin until it has actually stopped.
    expected_selection = {"media_id": manifest.media_id, "names": ("drums", "bass")}
    assert expected_selection == main._STEM_SELECTION
    assert main.stems_command(["off"]) == ()
    assert main._STEM_SELECTION == {"media_id": None, "names": ()}


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_unexpected_monitor_failure_releases_acquired_result(stem_controls, monkeypatch, error_type):
    previous = {"media_id": "previous", "names": ("other",)}
    monkeypatch.setattr(main, "_STEM_SELECTION", previous)

    def interrupted(*_args, **_kwargs):
        raise error_type("interrupted")

    monkeypatch.setattr(stem_controls.controller, "configure_stem_monitor", interrupted)
    with pytest.raises(error_type, match="interrupted"):
        main.stems_command(["solo", "vocals"])
    assert len(stem_controls.leases) == 1
    assert stem_controls.leases[0].released
    assert main._STEM_SELECTION is previous


@pytest.mark.parametrize("arguments", [["solo", "vocals"], ["export", "chosen-folder"]])
def test_unprepared_media_cannot_monitor_or_export(stem_controls, arguments):
    stem_controls.state.manifest = None
    with pytest.raises(StemError, match=r"Prepare stems|No prepared stems"):
        main.stems_command(arguments)
    assert stem_controls.calls == []


@pytest.mark.parametrize("active,transitioning", [(True, False), (False, True), (True, True)])
def test_clear_refuses_active_or_retiring_monitor(stem_controls, active, transitioning):
    stem_controls.state.active = active
    stem_controls.state.transitioning = transitioning
    with pytest.raises(StemError, match="transition finish"):
        main.stems_command(["clear", "--yes"])
    assert stem_controls.calls == []


def test_clear_after_monitor_retirement_resets_selection(stem_controls, monkeypatch):
    monkeypatch.setattr(main, "_STEM_SELECTION", {"media_id": "track-1", "names": ("vocals",)})
    assert main.stems_command(["clear", "--yes"]) is True
    assert stem_controls.calls == [("clear", ("track-1",), {})]
    assert main._STEM_SELECTION == {"media_id": None, "names": ()}


@pytest.mark.parametrize("confirmed", [False, True])
def test_export_preserves_explicit_overwrite_choice(stem_controls, tmp_path, confirmed):
    target = tmp_path / "Selected export"
    arguments = ["export", str(target)] + (["--yes"] if confirmed else [])
    exported = main.stems_command(arguments)
    assert exported == tuple(stem_controls.state.manifest.stems.values())
    assert stem_controls.calls == [("export", ("track-1", target), {"overwrite": confirmed})]


@pytest.mark.parametrize("arguments", [
    ["prepare", "5"], ["prepare", "4", "6"], ["solo"], ["solo", "vocals", "bass"],
    ["mix"], ["mix", "original"], ["original", "extra"], ["export"],
    ["export", "one", "two"], ["clear", "extra"], ["cancel", "extra"], ["unknown"],
])
def test_invalid_stem_commands_do_not_start_work(stem_controls, arguments):
    with pytest.raises(StemError):
        main.stems_command(arguments)
    assert stem_controls.calls == []


def test_status_and_cancel_are_available_without_active_media(stem_controls):
    stem_controls.state.media = None
    stem_controls.state.transitioning = True
    status = main.stems_command([])
    assert isinstance(status, dict)
    assert status["selection"] == ()
    assert any("original mix (transitioning)" in value for value in stem_controls.messages)
    assert main.stems_command(["cancel"]) is None
    assert stem_controls.calls == [("cancel", (), {})]

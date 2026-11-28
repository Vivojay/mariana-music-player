from types import SimpleNamespace

import pytest

from mariana.web_session import NativeSession
from mariana.web_transport import apply, prepare

PLAYBACK = {
    "media_id": "recording", "occurrence": "instance-one", "state": "playing",
    "duration_seconds": 120, "seekable": True, "live": False,
}


def test_seek_binds_to_the_current_occurrence_and_is_direct():
    data = {"action":"seek", "value":37.25, "occurrence":"instance-one"}
    intent = prepare(data, PLAYBACK)
    assert intent.direct and intent.value == 37.25

    calls = []
    snapshot = SimpleNamespace(session_id="instance-one", media=SimpleNamespace(stable_id="recording"))
    def control(action, fields):
        calls.append((action, fields))
        return {"ok":True}
    assert apply(intent, snap=lambda: snapshot, dispatch=None, control=control)["ok"]
    assert calls == [("playback.seek", {"media_id":"recording", "target_seconds":37.25, "origin":"web"})]

    # Starting the same recording again invalidates a seek begun on its earlier play.
    snapshot.session_id = "instance-two"
    assert not apply(intent, snap=lambda: snapshot, dispatch=None, control=control)["ok"]
    assert len(calls) == 1


def test_control_rejects_bad_values_and_keeps_nontransport_reviewed():
    for value in [True, -1, float("nan"), float("inf"), 121, "10"]:
        with pytest.raises(ValueError):
            prepare({"action":"seek","value":value,"occurrence":"instance-one"}, PLAYBACK)
    with pytest.raises(ValueError):
        prepare({"action":"seek","value":5,"occurrence":"instance-one"}, {**PLAYBACK,"live":True})
    with pytest.raises(ValueError):
        prepare({"action":"rating","value":True,"occurrence":"instance-one"}, PLAYBACK)

    session = NativeSession()
    session.controls = True
    session.playback = PLAYBACK
    _, paired = session.request("pair", session.invite, {}, [])
    token = paired["token"]
    assert session.request("control", token, {"action":"favorite","occurrence":"instance-one"}, [])[0] == 202
    assert session.take() == "fav !"
    assert session.browser_policy("fav !") == (True, False)
    session.finish("Skipped at the Mariana terminal.")
    assert session.request("control", token, {"action":"seek","value":37.25,"occurrence":"instance-one"}, [])[0] == 202
    assert session.take() == "seek 37.250s"
    assert session.browser_policy("seek 37.250s") == (False, True)
    session.finish("Control applied.", ok=True)
    assert session.request("state", token, {}, [])[1]["job"]["ok"] is True


def test_queue_settings_and_playback_volume_bind_to_native_commands():
    called = []
    for data, text in [
        ({"action":"shuffle","value":True},"queue order shuffle"),
        ({"action":"repeat","value":"all"},"queue repeat all"),
        ({"action":"volume","value":63},"volume 63"),
    ]:
        intent = prepare(data,PLAYBACK)
        result = apply(intent, snap=None, dispatch=called.append, control=None)
        assert result["ok"] and called[-1] == text


def test_collection_commands_check_the_binding_again_before_dispatch():
    class Rows:
        def command(self, choice, token):
            assert token and choice == {"key":"key","action":"play"}
            return "queue jump 2"
    session = NativeSession()
    session.collections, session.library = Rows(), list
    _, paired = session.request("pair", session.invite, {"library":True}, [])
    token = paired["token"]
    binding = {"key":"key","action":"play"}
    assert session.request("command", token, {"command":"queue remove 2","collectionAction":binding}, [])[0] == 400
    assert session.request("command", token, {"command":"queue jump 2","collectionAction":binding}, [])[0] == 202
    assert session.collection_request == binding

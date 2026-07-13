from types import SimpleNamespace

import pytest

import beta.IPrint as iprint
import beta.master_volume_control as master_volume
import beta.redditsessions as reddit
import first_boot_welcome_screen as welcome
import lyrics_provider.lyrics_window_spawn as lyrics_window
import main


def test_interactive_print_helpers(capsys):
    iprint.IPrint("visible")
    iprint.IPrint("hidden", visible=False)
    assert capsys.readouterr().out.strip() == "visible"
    rendered = iprint.Coloured("text", fg="white", bg="black", disableprint=True)
    assert "text" in rendered
    iprint.Coloured("printed")
    iprint.blue_gradient_print("ab", [("black", "white")])
    output = capsys.readouterr().out
    assert "printed" in output
    assert "a" in output and "b" in output
    assert iprint.loading("ignored") is None


def test_master_volume_get_set_and_zero(monkeypatch):
    calls = []
    endpoint = SimpleNamespace(
        GetMasterVolumeLevelScalar=lambda: 0.456,
        SetMasterVolumeLevelScalar=lambda value, context: calls.append((value, context)),
    )
    monkeypatch.setattr(master_volume, "device_refresh", lambda: endpoint)
    assert master_volume.get_master_volume() == 46
    master_volume.set_master_volume(80)
    master_volume.set_master_volume(0)
    assert calls == [(0.8, None), (0.0, None)]


def test_legacy_master_volume_import_is_optional(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "pycaw", None)
    monkeypatch.setitem(__import__("sys").modules, "pycaw.pycaw", None)
    with pytest.raises(RuntimeError, match="requires pycaw on Windows"):
        master_volume.device_refresh()


def test_main_master_volume_accepts_zero_and_reports_unavailable(monkeypatch):
    calls = []
    messages = []
    monkeypatch.setattr(main, "comtypes_load_error", False)
    monkeypatch.setattr(main, "set_master_volume", lambda value: calls.append(value))
    monkeypatch.setattr(main, "SAY", lambda **kwargs: messages.append(kwargs))
    main.setmastervolume(0)
    main.setmastervolume(101)
    assert calls == [0]
    assert messages[-1]["log_priority"] == 2

    monkeypatch.setattr(main, "comtypes_load_error", True)
    main.setmastervolume(50)
    assert "unavailable" in messages[-1]["display_message"].lower()


def test_reddit_retirement_shim_is_stable():
    assert reddit.get_redditsessions() == []
    rows, headers = reddit.display_seshs_as_table([{"ignored": True}])
    assert rows == []
    assert headers == ("title", "upvotes", "downvotes")
    assert reddit.WARNING == reddit.RETIRED_MESSAGE


class FakeWidget:
    def __init__(self, *_args, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.values = {}

    def configure(self, **kwargs):
        self.calls.append(("configure", kwargs))

    config = configure

    def pack(self, **kwargs):
        self.calls.append(("pack", kwargs))

    def grid(self, **kwargs):
        self.calls.append(("grid", kwargs))

    def delete(self, *args):
        self.calls.append(("delete", args))

    def insert(self, *args):
        self.calls.append(("insert", args))

    def yview(self, *args):
        self.calls.append(("yview", args))

    def set(self, *args):
        self.calls.append(("set", args))

    def __setitem__(self, key, value):
        self.values[key] = value


class FakeRoot(FakeWidget):
    def __init__(self):
        super().__init__()
        self.mainloop_called = False

    def after(self, *args):
        self.calls.append(("after", args))

    def destroy(self):
        self.calls.append(("destroy", ()))

    def winfo_screenwidth(self):
        return 1000

    def winfo_screenheight(self):
        return 800

    def geometry(self, value):
        self.calls.append(("geometry", value))

    def overrideredirect(self, value):
        self.calls.append(("overrideredirect", value))

    def resizable(self, *args):
        self.calls.append(("resizable", args))

    def wm_attributes(self, *args):
        self.calls.append(("wm_attributes", args))

    def title(self, value):
        self.calls.append(("title", value))

    def grid_columnconfigure(self, *args, **kwargs):
        self.calls.append(("grid_columnconfigure", args, kwargs))

    def grid_rowconfigure(self, *args, **kwargs):
        self.calls.append(("grid_rowconfigure", args, kwargs))

    def iconphoto(self, *args):
        self.calls.append(("iconphoto", args))

    def mainloop(self):
        self.mainloop_called = True


def test_first_boot_welcome_window_contract(monkeypatch):
    root = FakeRoot()
    image = SimpleNamespace(resize=lambda dimensions: ("resized", dimensions))
    monkeypatch.setattr(welcome.tk, "Tk", lambda: root)
    monkeypatch.setattr(welcome.tk, "Label", FakeWidget)
    monkeypatch.setattr(welcome.Image, "open", lambda _path: image)
    monkeypatch.setattr(welcome.ImageTk, "PhotoImage", lambda value: ("photo", value))

    welcome.notify(Time=123)

    assert root.mainloop_called is True
    assert ("after", (123, root.destroy)) in root.calls
    assert any(call[0] == "geometry" for call in root.calls)


def test_lyrics_window_widget_contract(monkeypatch):
    root = FakeRoot()
    widgets = []

    def widget(*args, **kwargs):
        value = FakeWidget(*args, **kwargs)
        widgets.append(value)
        return value

    monkeypatch.setattr(lyrics_window.tk, "Tk", lambda: root)
    monkeypatch.setattr(lyrics_window.tk, "PhotoImage", lambda **kwargs: kwargs)
    monkeypatch.setattr(lyrics_window.tk, "Label", widget)
    monkeypatch.setattr(lyrics_window.tk, "Text", widget)
    monkeypatch.setattr(lyrics_window.ttk, "Scrollbar", widget)

    lyrics_window.spawn_lyrics_window("line one", "Artist", "Provider")

    assert root.mainloop_called is True
    text_widget = next(item for item in widgets if item.kwargs.get("height") == 10)
    assert ("insert", ("end", "\nline one")) in text_widget.calls
    assert "yscrollcommand" in text_widget.values

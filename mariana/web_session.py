"""Single-browser, loopback presentation of the owning Mariana terminal session."""
from __future__ import annotations

import asyncio
import hmac
import json
import math
import re
import secrets
import sys
import threading
import time
import unicodedata
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .command_parser import split_command
from .web_console_style import styled_console_output
from .web_transport import prepare as prepare_control
from .terminal_player import _TERMINAL_CODES, _OutputTail

# These exact noninteractive commands can run without additional approval.
TRANSPORT = frozenset(("p", ".next", ".prev", "seek -10s", "seek +10s", "now", "progress"))
SESSION_LIMIT = 8 * 3600
ACTION_LIMIT = 20
BROWSER_VIEWS = frozenset(("console", "flow"))
BROWSER_FOCUS = frozenset(("command", "search", "library", "now"))
PUBLIC_STATE = ("title", "artist", "display_state", "position_seconds", "duration_seconds",
                "queue_position", "queue_count")
PLAYBACK_CONTROLS = ("occurrence", "playback_rate", "state", "media_id", "seekable", "live",
                     "source", "library_index", "favorite", "queue_order", "queue_repeat",
                     "buffered_seconds", "region", "volume", "muted")
FILES = {"/": ("companion.html", "text/html; charset=utf-8"),
         "/command-input.js": ("command-input.js", "text/javascript"),
         "/command-input.css": ("command-input.css", "text/css"),
         "/companion-flow.js": ("companion-flow.js", "text/javascript"),
         "/companion-similar.js": ("companion-similar.js", "text/javascript"),
         "/companion-similar.css": ("companion-similar.css", "text/css"),
         "/companion-console.js": ("companion-console.js", "text/javascript"),
         "/companion-console.css": ("companion-console.css", "text/css"),
         "/companion-home.js": ("companion-home.js", "text/javascript"),
         "/companion-home.css": ("companion-home.css", "text/css"),
         "/companion-collections.js": ("companion-collections.js", "text/javascript"),
         "/companion-collections.css": ("companion-collections.css", "text/css"),
         "/companion.js": ("companion.js", "text/javascript"),
         "/platform.js": ("platform.js", "text/javascript"),
         "/companion.css": ("companion.css", "text/css"), "/player.css": ("player.css", "text/css")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src blob:; "
       "form-action 'none'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")


class _PublishedOutput:
    """Continue local output and share only approved, foreground command writes."""
    def __init__(self, stream, capture):
        self.stream = stream
        self.capture = capture
        self.owner = threading.get_ident()

    def __getattr__(self, key):
        return getattr(self.stream, key)

    def write(self, value):
        written = self.stream.write(value)
        if threading.get_ident() == self.owner:
            self.capture.write(value)
        return written

    def writelines(self, lines):
        for line in lines:
            self.write(line)


def clean_command(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 2048 or not text.strip():
        raise ValueError("Enter a command between 1 and 2048 characters.")
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in text):
        raise ValueError("Use a single line without control characters.")
    command = text.strip()
    words = split_command(command)
    if not words or not words[0]:
        raise ValueError("Enter a Mariana command.")
    if words[0].casefold() == "web":
        raise ValueError("The native browser session is already open.")
    return command


def assist_command(data):
    """Expose the installed command syntax to the paired tab using DOM cursor offsets."""
    from .command_assist import command_corrections, command_suggestions

    line, cursor = data.get("line"), data.get("cursor")
    reviewing = data.get("correctionsOnly", False)
    if (not isinstance(line, str) or len(line) > 2048 or type(cursor) is not int
            or type(reviewing) is not bool or any(unicodedata.category(c) in
                {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in line)):
        raise ValueError("Invalid command text or cursor.")
    # JavaScript uses UTF-16 units. Reject a cursor that bisects a surrogate pair.
    offsets = [0]
    for char in line:
        offsets.append(offsets[-1] + (2 if ord(char) > 0xffff else 1))
    try:
        index = offsets.index(cursor)
    except ValueError as error:
        raise ValueError("Invalid command cursor.") from error
    matches = command_corrections(line) if reviewing else command_suggestions(line, index, limit=20)
    results = []
    for match in matches:
        text = line[:match.start] + match.text + line[match.end:]
        if text.strip().split(maxsplit=1)[0].casefold() == "web":
            continue
        results.append({"start": offsets[match.start], "end": offsets[match.end], "value": match.text,
                        "label": match.label, "description": match.summary, "correction": match.kind == "correction"})
    return {"suggestions": results}


class NativeSession:
    def __init__(self, *, clock=time.monotonic, trusted=False, share_output=False):
        self.lock = threading.Lock()
        self.clock = clock
        self.started = self.last_contact = clock()
        self.invite = secrets.token_urlsafe(32)
        self.token = None
        self.closed = False
        self.playback = {}
        self.job = None
        self.wake = threading.Event()
        self.share_library = False
        self.library = None
        self.library_path = None
        self.library_request = None
        self.homepage = None
        self.homepage_image = None
        self.similarity = None
        self.similarity_lock = threading.Lock()
        self.collections = None
        self.collection_request = None
        self.controls = False
        self.control_request = None
        self.trusted = trusted
        self.share_output = trusted and share_output
        self.browser_action = None
        self.browser_result = ""
        self.action_deadline = 0.0

    def expired(self):
        now = self.clock()
        return (self.closed or now - self.started >= SESSION_LIMIT or
                (now - self.last_contact >= (90 if self.token else 300)))

    def _policy(self):
        return {"mode": "session" if self.trusted else "review",
                "shareOutput": self.share_output,
                "expirySeconds": max(0, math.ceil(SESSION_LIMIT - (self.clock() - self.started)))}

    def _change_policy(self, trusted, share_output=False):
        self.trusted = trusted
        self.share_output = trusted and share_output
        return self._policy()

    def approve(self, share_output=False):
        with self.lock:
            if not self.token or self.expired():
                raise ValueError("Connect the browser before changing its approval.")
            self._change_policy(True, share_output)

    def review(self):
        with self.lock:
            self._change_policy(False)

    def _expire_action(self):
        if self.browser_action and self.clock() >= self.action_deadline:
            self.browser_action = None
            self.browser_result = "Browser action expired before acknowledgement."

    def push_browser(self, action, value=None):
        with self.lock:
            if not self.token or self.expired():
                raise ValueError("Connect the browser before sending an action.")
            self._expire_action()
            if self.browser_action:
                raise ValueError("The previous browser action is still waiting for acknowledgement.")
            self.browser_action = {"id": secrets.token_hex(8), "action": action, "value": value}
            self.action_deadline = self.clock() + ACTION_LIMIT
            self.browser_result = "Browser action queued."

    def status(self):
        with self.lock:
            self._expire_action()
            policy = ("Approved for this session; command output "
                      + ("shared." if self.share_output else "private.")) if self.trusted else "Review each browser command."
            return " ".join(filter(None, ("Browser connected." if self.token else "Waiting for browser.",
                                         policy, self.browser_result)))

    def queued(self):
        with self.lock:
            return bool(self.job and self.job["state"] == "queued")

    def browser_policy(self, cmd):
        with self.lock:
            transport = (self.control_request.direct if self.control_request else cmd in TRANSPORT)
            review = not (transport or self.trusted)
            if review and self.job:
                self.job = dict(self.job, state="review")
            return review, transport or self.share_output

    def library_key(self, path):
        return hmac.new(self.token.encode(), str(path).encode('utf-8', 'surrogatepass'), 'sha256').hexdigest()

    def library_page(self, data):
        query, offset = data.get("query", ""), data.get("offset", 0)
        if not isinstance(query, str) or len(query) > 160 or type(offset) is not int or offset < 0:
            raise ValueError("Invalid library search.")
        words = query.casefold().split()
        page = []
        total = 0
        for number, (title, detail, _, path) in enumerate(self.library(), 1):
            if not all(word in (title + " " + detail).casefold() for word in words):
                continue
            if offset <= total < offset + 40:
                page.append({"number": number, "title": title[:300], "detail": detail[:300],
                             "key": self.library_key(path)})
            total += 1
        return {"rows": page, "total": total, "offset": offset}

    def library_matches(self, number, key):
        path = self.library_path(number) if self.library_path else None
        return path is not None and hmac.compare_digest(key, self.library_key(path))

    def similarity_page(self, bearer, data):
        from .media_similarity import MODES

        with self.lock:
            if self.expired():
                return 410, {"error": "The connection ended. Run web session in Mariana again."}
            if not self.token or not hmac.compare_digest(bearer, self.token) or not self.share_library:
                return 403, {"error": "Native library access is required to find similar recordings."}
            if not self.similarity:
                return 404, {"error": "Similarity is unavailable in this session."}
            self.last_contact = self.clock()
            number, key, occurrence = data.get("number"), data.get("key"), data.get("occurrence")
            mode, limit = data.get("mode", "hybrid"), data.get("limit", 12)
            if mode not in MODES or type(limit) is not int or not 1 <= limit <= 20:
                return 400, {"error": "Choose a similarity mode and a result limit of 1–20."}
            source = None
            if "number" in data or "key" in data:
                if type(number) is not int or not 1 <= number <= 100_000_000 or occurrence is not None:
                    return 400, {"error": "Invalid library selection."}
                if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
                    return 400, {"error": "Invalid library selection."}
                source = self.library_path(number) if self.library_path else None
                if source is None or not hmac.compare_digest(key, self.library_key(source)):
                    return 409, {"error": "The library changed. Select the recording again."}
            elif not isinstance(occurrence, str) or not occurrence or occurrence != self.playback.get("occurrence"):
                return 409, {"error": "Choose a recording in the native library or play it first."}
        if not self.similarity_lock.acquire(blocking=False):
            return 409, {"error": "A similarity search is still running. Try again shortly."}
        try:
            page = self.similarity(source, occurrence, mode, limit, self.library_key)
        except ValueError as error:
            return 400, {"error": str(error)}
        finally:
            self.similarity_lock.release()
        with self.lock:
            if self.expired():
                return 410, {"error": "The connection ended. Run web session in Mariana again."}
            if occurrence is not None and occurrence != self.playback.get("occurrence"):
                return 409, {"error": "Playback changed. Choose the recording again."}
        return 200, page

    def request(self, route, bearer, data, catalog):
        if route == "similarity":
            return self.similarity_page(bearer, data)
        if route == "homepage-image":
            return self.homepage_image_request(bearer, data)
        with self.lock:
            if self.expired():
                return 410, {"error": "The connection ended. Run web session in Mariana again."}
            if route == "pair":
                if self.token or not self.invite or not hmac.compare_digest(bearer, self.invite):
                    return 403, {"error": "This invitation is invalid or has already been used."}
                self.token, self.invite = secrets.token_urlsafe(32), None
                self.last_contact = self.clock()
                self.share_library = data.get("library") is True and self.library is not None
                return 200, {"token": self.token, "catalog": catalog, "library": self.share_library,
                             "session": self._policy(), "homepage": self.homepage is not None,
                             "collections": self.share_library and self.collections is not None,
                             "controls": self.controls,
                             "similarity": self.share_library and self.similarity is not None}
            if not self.token or not hmac.compare_digest(bearer, self.token):
                return 403, {"error": "Pair this browser with the running Mariana session."}
            self.last_contact = self.clock()
            if route == "state":
                self._expire_action()
                return 200, {"playback": self.playback, "job": self.job, "session": self._policy(),
                             "browserAction": self.browser_action}
            if route == "revoke":
                return 200, {"session": self._change_policy(False)}
            if route == "browser-ack":
                key, error = data.get("id"), data.get("error", "")
                if (not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{16}", key)
                        or not isinstance(error, str) or len(error) > 200):
                    return 400, {"error": "Invalid browser action acknowledgement."}
                self._expire_action()
                if self.browser_action and self.browser_action["id"] == key:
                    self.browser_result = "Browser could not apply the action." if error else "Browser acknowledged the action."
                    self.browser_action = None
                return 200, {"acknowledged": True}
            if route == "homepage" and self.homepage:
                return 200, self.homepage(self.share_library)
            if route == "collections" and self.collections:
                if not self.share_library:
                    return 403, {"error": "Native collections were not enabled at pairing."}
                try:
                    return 200, self.collections.read(data, self.token)
                except ValueError as error:
                    return 400, {"error": str(error)}
            if route == "library":
                if not self.share_library:
                    return 403, {"error": "Library browsing was not enabled at pairing."}
                try:
                    return 200, self.library_page(data)
                except ValueError as error:
                    return 400, {"error": str(error)}
            if route == "assist":
                try:
                    return 200, assist_command(data)
                except ValueError as error:
                    return 400, {"error": str(error)}
            if route == "close":
                self.closed = True
                self.wake.set()
                return 200, {"closed": True}
            if route not in {"command", "control"} or (route == "control" and not self.controls):
                return 404, {"error": "Unknown action."}
            if self.job and self.job["state"] != "done":
                return 409, {"error": "Finish the current command before starting another."}
            intent = binding = None
            try:
                if route == "control":
                    intent = prepare_control(data, self.playback)
                cmd = intent.label if intent else clean_command(data.get("command"))
                binding = data.get("collectionAction") if not intent else None
                if binding is not None and (not self.share_library or not self.collections
                                            or self.collections.command(binding, self.token) != cmd):
                    raise ValueError("The collection changed. Refresh and select the item again.")
            except ValueError as error:
                return 400, {"error": str(error)}
            request = None
            key = data.get("libraryKey")
            if key is not None:
                if binding is not None or intent is not None:
                    return 400, {"error": "Choose one recording target."}
                action = re.fullmatch(r"(?:play|queue add) ([1-9][0-9]{0,9})", cmd)
                if not (self.share_library and action and isinstance(key,str) and re.fullmatch(r"[0-9a-f]{64}", key)):
                    return 400, {"error": "Invalid library selection."}
                number = int(action[1])
                if not self.library_matches(number, key):
                    return 409, {"error": "The library changed. Refresh the results before trying again."}
                request = number, key
            self.library_request = request
            self.collection_request = binding
            self.control_request = intent
            self.job = {"id": secrets.token_hex(8), "state": "queued", "command": cmd, "output": ""}
            self.wake.set()
            return 202, {"id": self.job["id"]}

    def homepage_image_request(self, bearer, data):
        with self.lock:
            if self.expired():
                return 410, {"error": "The connection ended. Run web session in Mariana again."}
            if not self.token or not hmac.compare_digest(bearer, self.token):
                return 403, {"error": "Pair this browser with the running Mariana session."}
            key = data.get("key")
            if set(data) != {"key"} or not isinstance(key, str) or len(key) > 69:
                return 400, {"error": "Invalid homepage artwork request."}
            self.last_contact = self.clock()
        # Reading and validating image bytes must not block playback controls.
        thumbnail = self.homepage_image(key) if self.homepage_image else None
        with self.lock:
            if self.expired():
                return 410, {"error": "The connection ended. Run web session in Mariana again."}
        if thumbnail is None:
            return 404, {"error": "Homepage artwork is unavailable."}
        content, mime = thumbnail
        return 200, content, mime

    def take(self):
        with self.lock:
            if self.expired() or not self.job or self.job["state"] != "queued":
                return None
            direct = self.control_request.direct if self.control_request else self.job["command"] in TRANSPORT
            auto = self.trusted or direct
            self.job = dict(self.job, state="running" if auto else "review")
            return self.job["command"]

    def finish(self, text, *, ok=None, styled=""):
        with self.lock:
            self.job = dict(self.job, state="done", output=text)
            if ok is not None:
                self.job["ok"] = ok
            if styled:
                self.job["ansiOutput"] = styled


def make_server(session, assets: Path, catalog, available=lambda: True):
    # Read only these trusted app assets, never files named by an HTTP request.
    content = {route: ((assets / name).read_bytes(), mime) for route, (name, mime) in FILES.items()}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, fmt, *args):
            pass

        def reply(self, status, body, mime="application/json"):
            if isinstance(body, dict):
                body = json.dumps(body, ensure_ascii=True, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(body)

        def host_ok(self):
            return self.headers.get_all("Host") == [f"127.0.0.1:{self.server.server_port}"]

        def do_GET(self):
            if not self.host_ok():
                self.reply(403, {})
                return
            # Query parameters may contain only the cosmetic view preference.
            parts = urlsplit(self.path)
            if parts.scheme or parts.netloc or parts.path not in content:
                self.reply(404, {})
                return
            self.reply(200, *content[parts.path])

        def do_POST(self):
            expected = f"http://127.0.0.1:{self.server.server_port}"
            if (not self.host_ok() or self.headers.get_all("Origin") != [expected]
                    or self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin"):
                self.reply(403, {})
                return
            if (self.headers.get_content_type() != "application/json"
                    or self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1):
                self.reply(415, {})
                return
            length = self.headers["Content-Length"]
            if not re.fullmatch(r"[0-9]{1,5}", length) or not 0 < int(length) <= 12288:
                self.reply(413, {})
                return
            authorization = self.headers.get("Authorization", "")
            if not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", authorization):
                self.reply(403, {})
                return
            if self.path not in {"/api/pair", "/api/state", "/api/command", "/api/close", "/api/assist", "/api/library",
                                 "/api/browser-ack", "/api/revoke", "/api/control", "/api/homepage", "/api/collections",
                                 "/api/similarity", "/api/homepage-image"}:
                self.reply(404, {})
                return
            try:
                data = json.loads(self.rfile.read(int(length)))
                if not isinstance(data, dict):
                    raise ValueError
            except (ValueError, RecursionError):
                self.reply(400, {})
                return
            if not available():
                self.reply(410, {"error": "Native session closed."})
                return
            reply = session.request(self.path[5:], authorization[7:], data, catalog)
            if self.path in {"/api/similarity", "/api/homepage-image"} and not available():
                self.reply(410, {"error": "Native session closed."})
                return
            self.reply(*reply)

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def _read_while(message, active, prompt=None, draft="", *, close_on_interrupt=False, details=None):
    """Read on the owning terminal and return its draft if the prompt yields."""
    from .terminal_io import current_session

    host = current_session()
    if host is not None:
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout.containers import HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.widgets import TextArea

        def submit(buffer):
            host.close_view((True, buffer.text) if active() else (False, buffer.text))
            return True

        def label():
            if not active():
                host.close_view((False, editor.text))
            return message

        editor = TextArea(text=draft, multiline=False, height=1, accept_handler=submit)
        editor.buffer.cursor_position = len(draft)
        keys = KeyBindings()

        @keys.add("escape")
        @keys.add("c-c")
        def skip(event):
            host.close_view((None if close_on_interrupt else True, ""))

        contents = [Window(FormattedTextControl(label), wrap_lines=True), editor]
        if details:
            contents.insert(0, Window(FormattedTextControl(details), wrap_lines=True, dont_extend_height=True))
        container = HSplit(contents)
        result = host.run_view(container, focus=editor, bindings=keys, refresh_interval=.20)
        if isinstance(result, tuple):
            if result[0] is None:
                raise KeyboardInterrupt
            return result
        return False, draft

    if prompt is None:
        from prompt_toolkit import PromptSession
        prompt = PromptSession()

    async def watch_session():
        while active():
            await asyncio.sleep(.15)
        if prompt.app.is_running:
            prompt.app.exit(result=None)

    result = prompt.prompt(message, default=draft, pre_run=lambda: prompt.app.create_background_task(watch_session()))
    return (True, result) if isinstance(result, str) else (False, prompt.default_buffer.text)


def review_at_terminal(message, active):
    """Leave the review prompt when the initiating browser disconnects or is restricted."""
    submitted, answer = _read_while(message, active)
    return answer if submitted and active() else ""


def terminal_control(session, line, write):
    """Route browser controls typed by the host. Return False for ordinary Mariana commands."""
    parts = line.split(maxsplit=2)
    if not parts or parts[0].casefold() != "web":
        return False
    verb = parts[1].casefold() if len(parts) > 1 else "help"
    value = parts[2] if len(parts) > 2 else ""
    option = value.casefold()
    try:
        if verb == "status" and not value:
            write(session.status())
        elif verb == "approve" and option in {"", "private", "share"}:
            session.approve(share_output=option == "share")
            write(session.status())
        elif verb == "revoke" and not value:
            session.review()
            write(session.status())
        elif verb in {"close", "stop"} and not value:
            with session.lock:
                session.closed = True
        elif verb == "view" and option in BROWSER_VIEWS:
            session.push_browser("view", option)
            write("Browser view change queued.")
        elif verb == "focus" and option in BROWSER_FOCUS:
            session.push_browser("focus", option)
            write("Browser focus change queued.")
        elif verb == "notice" and value and len(value) <= 500 and value.isprintable():
            session.push_browser("notice", value)
            write("Browser notice queued.")
        elif verb == "draft":
            session.push_browser("draft", clean_command(value))
            write("Browser command draft queued.")
        elif verb == "library" and len(value) <= 160 and (not value or value.isprintable()):
            session.push_browser("library", value)
            write("Browser library search queued.")
        elif verb == "clear" and not value:
            session.push_browser("clear")
            write("Browser transcript clear queued.")
        else:
            write("Paired controls: web status | web approve [private|share] | web revoke | "
                  "web view flow|console | web focus command|search|library|now | web library [QUERY] | "
                  "web draft COMMAND | web notice TEXT | web clear | web close")
    except ValueError as error:
        write(str(error))
    return True


def serve_session(*, assets, catalog, project, dispatch, available, open_browser, palette=lambda: {}, read=None, write=print,
                  view=None, library=None, library_path=None, trusted=False, share_output=False, terminal_read=None,
                  control=None, homepage=None, homepage_image=None, collections=None, similarity=None):
    from .terminal_io import current_session

    host = current_session()

    def running():
        return (host is None or not host.cancelled.is_set()) and available()

    session = NativeSession(trusted=trusted, share_output=share_output)
    session.library, session.library_path = library, library_path
    session.homepage, session.homepage_image, session.collections = homepage, homepage_image, collections
    session.similarity = similarity
    session.controls = control is not None

    def connected():
        with session.lock:
            return not session.expired() and running()

    # Browser and native commands both run on the foreground owner. Publish only a
    # compact snapshot after each command for the TUI view's rendering thread.
    latest_terminal_output = ""

    def report(message):
        nonlocal latest_terminal_output
        latest_terminal_output = message
        write(message)

    def details():
        with session.lock:
            pending_invitation = url if not session.token else ""
        tail = _TERMINAL_CODES.sub("", latest_terminal_output).splitlines()[-8:]
        return "\n".join(filter(None, (pending_invitation, "\n".join(tail)[-2200:])))

    next_update = 0.

    def publish_playback():
        nonlocal next_update
        now = time.monotonic()
        if now < next_update:
            return
        projection = project()
        playback = ({name: projection.get(name) for name in (*PUBLIC_STATE, *PLAYBACK_CONTROLS)}
                    if isinstance(projection, dict)
                    else {name: getattr(projection, name, None) for name in PUBLIC_STATE})
        playback["palette"] = palette()
        with session.lock:
            session.playback = playback
        next_update = now + .45

    def idle():
        if not connected():
            return False
        publish_playback()
        return not session.queued()

    draft = ""
    if terminal_read is None and read is None:
        from prompt_toolkit import PromptSession
        from .terminal_history import SessionHistory

        prompt = None if host is not None else PromptSession(history=SessionHistory())
        terminal_read = lambda active, text: _read_while(
            "Paired Mariana (web help for browser controls) › ", active, prompt, text,
            close_on_interrupt=True, details=details if host is not None else None)

    with make_server(session, assets, catalog, running) as server:
        query = "?view=flow" if view == "flow" else ""
        url = f"http://127.0.0.1:{server.server_port}/{query}#pair={session.invite}"
        thread = threading.Thread(target=server.serve_forever, daemon=True, name="Mariana web session")
        thread.start()
        try:
            write("Open this private invitation in a browser on this computer, then choose Connect.")
            write(url)
            write("Type native commands normally here. Use web help for browser controls, web close to disconnect.")
            if trusted:
                write("The invited tab may dispatch commands until you revoke approval or this session ends."
                      + (" Its printed command output will be shown in that tab." if share_output else " Output stays in this terminal."))
            try:
                open_browser(url)
            except OSError:
                pass
            while connected():
                publish_playback()
                command = session.take()
                if command is None:
                    if terminal_read is None:
                        session.wake.wait(0.5)
                        session.wake.clear()
                        continue
                    submitted, draft = terminal_read(idle, draft)
                    if submitted:
                        line, draft = draft.strip(), ""
                        if line and connected() and not terminal_control(session, line, report):
                            if host is None:
                                if dispatch(line) is False:
                                    return False
                            else:
                                local_output = _OutputTail(2200)
                                with redirect_stdout(_PublishedOutput(sys.stdout, local_output)):
                                    if dispatch(line) is False:
                                        return False
                                latest_terminal_output = local_output.text() or "Command finished."
                        next_update = 0.
                    continue
                review, publish = session.browser_policy(command)
                if review:
                    write(f"Browser requests this Mariana command: {command}")
                    question = ("Run once privately [r], run once and share output [s], "
                                "approve this session privately [a], approve and share output [as], or Enter to skip: ")
                    if host is not None:
                        question = f"Browser requests: {command}\n{question}"
                    answer = (read(question) if read else review_at_terminal(question, connected)).strip().lower()
                    if answer not in {"r", "s", "a", "as"}:
                        session.finish("Skipped at the Mariana terminal.")
                        continue
                    publish = answer in {"s", "as"}
                    if answer in {"a", "as"} and connected():
                        try:
                            session.approve(share_output=publish)
                        except ValueError:
                            break
                        report(session.status())
                with session.lock:
                    if session.expired():
                        break
                    selection = session.library_request
                    binding = session.collection_request
                    intent = session.control_request
                    if selection is not None and not session.library_matches(*selection):
                        selection = False
                if selection is False:
                    session.finish("The library changed during review. Refresh the results and select the recording again.")
                    continue
                if binding is not None:
                    try:
                        matches = session.collections.command(binding, session.token) == command
                    except ValueError:
                        matches = False
                    if not matches:
                        session.finish("The collection changed during review. Refresh and select the item again.")
                        continue
                if not running():
                    break
                output = _OutputTail(32000)

                def invoke():
                    if intent is None:
                        return dispatch(command)
                    response = control(intent)
                    if not response.get("ok"):
                        return str(response.get("error", "Playback control failed."))
                    return None

                try:
                    if publish:
                        # Keep stderr, subprocess output and typed answers on the host terminal.
                        with redirect_stdout(_PublishedOutput(sys.stdout, output)):
                            result = invoke()
                    else:
                        result = invoke()
                except (KeyboardInterrupt, EOFError):
                    session.finish("Command cancelled in the terminal.")
                    continue
                if result is False:
                    return False
                text = _TERMINAL_CODES.sub("", output.text()).strip()
                if output.trimmed:
                    text = "[Earlier output trimmed.]\n" + text
                next_update = 0.
                publish_playback()
                if intent is not None:
                    session.finish(result if isinstance(result, str) else "Control applied.", ok=not isinstance(result, str))
                else:
                    styled = styled_console_output(output.text()).strip() if publish and text else ""
                    session.finish((text or "Command finished.") if publish else "Command finished in the terminal.",
                                   styled=styled if "\x1b[" in styled else "")
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            with session.lock:
                session.closed = True
            server.shutdown()
            thread.join(timeout=2)
    return None

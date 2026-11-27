import getpass
import json
import unittest
import warnings
from unittest.mock import MagicMock, patch

from mariana import fanrooms


class Store(dict):
    def set(self, key, value):
        self[key] = value

    def delete(self, key):
        self.pop(key, None)


class FanRoomTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.packets = []

    def call(self, *args, replies=()):
        expected = iter(replies)

        def request(origin, token, method, path, **kwargs):
            self.assertEqual(origin, "https://example.org")
            self.assertEqual(token, "test-matrix-token")
            self.packets.append((method, path, kwargs))
            return next(expected)

        return fanrooms.run(list(args), secrets=self.store, prompt=lambda _: "test-matrix-token", request=request)

    def login(self):
        self.assertIn("@fan", self.call("login", "https://example.org/", replies=[{"user_id": "@fan:example.org"}]))

    def test_account_join_read_post_reply_react_report_leave(self):
        self.login()
        self.assertNotIn("test-matrix-token", self.call("status"))
        self.assertIn("!r", self.call("join", "#public:example.org", replies=[{"room_id": "!r"}]))
        self.assertEqual(self.packets[-1][1], "join/%23public%3Aexample.org")
        self.assertEqual(self.call("rooms", replies=[{"joined_rooms": ["!r"]}]), "!r")
        self.call("post", "!r", "hello", replies=[None, {"event_id": "$new"}])
        self.assertEqual(self.packets[-2][1], "rooms/%21r/state/m.room.encryption")
        self.assertTrue(self.packets[-1][1].startswith("rooms/%21r/send/m.room.message/"))
        self.assertEqual(self.packets[-1][2]["json"]["body"], "hello")
        self.call("reply", "!r", "$new", "reply", replies=[None, {"event_id": "$r"}])
        self.assertEqual(self.packets[-1][2]["json"]["m.relates_to"]["m.in_reply_to"]["event_id"], "$new")
        self.call("react", "!r", "$new", "🎵", replies=[None, {"event_id": "$reaction"}])
        self.assertEqual(self.packets[-1][2]["json"]["m.relates_to"]["rel_type"], "m.annotation")
        self.assertIn("/send/m.reaction/", self.packets[-1][1])
        recent = self.call("read", "!r", "5", replies=[{"chunk": [
            {"type": "m.room.encrypted", "sender": "@x", "event_id": "$two"},
            {"type": "m.room.message", "sender": "@x\x1b", "event_id": "$one",
             "content": {"msgtype": "m.text", "body": "old\ntext\x1b"}},
        ]}])
        self.assertLess(recent.index("$one"), recent.index("$two"))
        self.assertIn("old text", recent)
        self.assertNotIn("\x1b", recent)
        self.call("report", "!r", "$bad", "spam", replies=[{}])
        self.assertEqual(self.packets[-1], ("POST", "rooms/%21r/report/%24bad", {"json": {"reason": "spam"}}))
        self.call("leave", "!r", replies=[{}])
        self.assertEqual(self.packets[-1][1], "rooms/%21r/leave")
        self.call("forget")
        self.assertIn("No saved", self.call("status"))

    def test_wait_is_scoped_to_one_room_with_server_cursor(self):
        self.login()
        result = self.call("wait", "!room", "3", replies=[
            {"next_batch": "s4"},
            {"rooms": {"join": {"!room": {"timeline": {"events": [
                {"type": "m.room.message", "content": {"msgtype": "m.text", "body": "concert"}, "event_id": "$ok"}
            ]}}}}},
        ])
        self.assertIn("concert", result)
        args = self.packets[-1][2]["params"]
        self.assertEqual(json.loads(args["filter"])["room"]["rooms"], ["!room"])
        self.assertEqual((args["since"], args["timeout"]), ("s4", 3000))
        with self.assertRaisesRegex(ValueError, "25"):
            self.call("wait", "!room", "26")

    def test_encrypted_rooms_receive_no_writes(self):
        self.login()
        for args in (("post", "!r", "hello"), ("reply", "!r", "$e", "reply"), ("react", "!r", "$e", "+1")):
            with self.assertRaisesRegex(ValueError, "encryption"):
                self.call(*args, replies=[{"algorithm": "m.megolm.v1.aes-sha2"}])
            self.assertEqual(self.packets[-1][0], "GET")

    def test_rejects_non_origins_and_echoing_token_prompts(self):
        for origin in ("http://example.org", "https://foo@example.org", "https://example.org/?secret=x",
                       "https://example.org/path", "https://example.org:0", "https://example.org\\@elsewhere"):
            with self.assertRaises(ValueError):
                self.call("login", origin)
        def echoing(*_):
            warnings.warn("could echo", getpass.GetPassWarning, stacklevel=2)

        with patch.object(getpass, "getpass", side_effect=echoing), self.assertRaisesRegex(ValueError, "hidden"):
            fanrooms._secret_prompt("https://example.org")
        with self.assertRaisesRegex(ValueError, "hidden prompt"):
            self.call("login", "https://example.org", "token-on-command-line")
        self.assertEqual(self.store, {})

    @patch("mariana.fanrooms.requests.request")
    def test_wire_limits_redirects_errors_and_encryption_state(self, send):
        reply = MagicMock()
        send.return_value.__enter__.return_value = reply
        def respond(code, payload):
            reply.status_code = code
            reply.iter_content.return_value = iter([payload])
        respond(200, b'{"joined_rooms": []}')
        self.assertEqual(fanrooms._request("https://example.org", "abc", "GET", "joined_rooms"), {"joined_rooms": []})
        self.assertFalse(send.call_args.kwargs["allow_redirects"])
        self.assertTrue(send.call_args.kwargs["stream"])
        self.assertEqual(send.call_args.kwargs["headers"]["Authorization"], "Bearer abc")
        respond(404, b'{"errcode":"M_NOT_FOUND"}')
        self.assertIsNone(fanrooms._request("https://example.org", "abc", "GET", "state", missing=True))
        for code, payload in ((401, b'{"errcode":"M_UNKNOWN_TOKEN"}'), (404, b'{}'), (302, b'{}'),
                              (200, b"X"*524289)):
            respond(code, payload)
            with self.assertRaises(ValueError):
                fanrooms._request("https://example.org", "abc", "GET", "state", missing=True)

    def test_thread_paging_deduplicates_and_validates_room_sender_and_root(self):
        self.login()
        root = {"event_id": "$root", "sender": "@a:example.org", "room_id": "!r", "type": "m.room.message",
                "content": {"msgtype": "m.text", "body": "concert?"}}
        relation = {"rel_type": "m.thread", "event_id": "$root"}
        reply = {**root, "event_id": "$r1", "content": {"msgtype": "m.text", "body": "Friday", "m.relates_to": relation}}
        bad_root = {**reply, "content": {**reply["content"], "m.relates_to": {**relation, "event_id": "$another"}}}
        page = {"next_batch": "older", "chunk": [reply, reply, {**reply, "room_id": "!other"},
                                                  {**reply, "sender": 3}, bad_root]}
        display = self.call("thread", "!r", "$root", "page1", replies=[root, page])
        self.assertEqual(display.count("Friday"), 1)
        self.assertLess(display.index("concert?"), display.index("Friday"))
        self.assertIn("replies on this page: 1", display)
        self.assertIn("cursor: older", display)
        self.assertEqual(self.packets[-1][2]["version"], "v1")
        self.assertEqual(self.packets[-1][2]["params"]["from"], "page1")
        for broken in ({**root, "event_id": "$other"}, {**root, "room_id": "!other"}, reply):
            with self.assertRaisesRegex(ValueError, "thread root"):
                self.call("thread", "!r", "$root", replies=[broken])
        root["unsigned"] = {"m.relations": {"m.thread": {"latest_event": reply}}}
        self.call("thread-post", "!r", "$root", "Saturday", replies=[root, None, {"event_id": "$new"}])
        payload = self.packets[-1][2]["json"]["m.relates_to"]
        self.assertEqual((payload["rel_type"], payload["event_id"]), ("m.thread", "$root"))
        self.assertEqual(payload["m.in_reply_to"]["event_id"], "$r1")
        with self.assertRaisesRegex(ValueError, "encryption"):
            self.call("thread-post", "!r", "$root", "Saturday", replies=[root, {}])

    def test_poll_creation_voting_results_and_ending(self):
        from mariana import fan_polls as polls

        self.login()
        self.call("poll", "!r", "When?", "Friday", "Sunday", replies=[None, {"event_id": "$p"}])
        content = self.packets[-1][2]["json"]
        self.assertTrue(self.packets[-1][1].startswith("rooms/%21r/send/" + polls.START))
        keys = [a["id"] for a in content[polls.START]["answers"]]
        start = {"room_id": "!r", "sender": "@fan:example.org", "type": polls.START, "event_id": "$p", "content": content}
        self.call("vote", "!r", "$p", "2", replies=[start, {"chunk": []}, None, {"event_id": "$v"}])
        self.assertEqual(self.packets[-1][2]["json"][polls.VOTE]["answers"], [keys[1]])
        self.call("poll-end", "!r", "$p", replies=[start, {"chunk": []}, None, {"event_id": "$end"}])
        self.assertEqual(self.packets[-1][2]["json"][polls.END], {})
        with self.assertRaisesRegex(ValueError, "creator"):
            self.call("poll-end", "!r", "$p", replies=[{**start, "sender": "@other:example.org"}])
        with self.assertRaisesRegex(ValueError, "visible poll"):
            self.call("poll-show", "!r", "$p", replies=[{**start, "room_id": "!other"}])
        hidden = {**content, polls.START: {**content[polls.START], "kind": "unknown"}}
        with self.assertRaisesRegex(ValueError, "disclosed"):
            self.call("poll-show", "!r", "$p", replies=[{**start, "content": hidden}])
        relation = {"rel_type": "m.reference", "event_id": "$p"}

        def event(n, sender, choice):
            return {"room_id": "!r", "event_id": "$event" + str(n), "type": polls.VOTE, "sender": sender,
                    "origin_server_ts": n, "content": {"m.relates_to": relation, polls.VOTE: {"answers": [choice]}}}

        a = "@a:example.org"
        b = "@b:example.org"
        old, new, spoiled = event(2, a, keys[0]), event(3, a, keys[1]), event(4, b, "unknown")
        end = {"room_id": "!r", "event_id": "$end", "type": polls.END, "sender": start["sender"], "origin_server_ts": 8,
               "content": {"m.relates_to": relation, polls.END: {}}}
        wrong_room = {**event(7, b, keys[1]), "room_id": "!other"}
        wrong_parent = event(6, b, keys[0])
        wrong_parent["content"]["m.relates_to"] = {**relation, "event_id": "$elsewhere"}
        pages = [{"chunk": [event(9, a, keys[0]), end, wrong_room, wrong_parent], "next_batch": "p2"},
                 {"chunk": [old, new, new, event(1, b, keys[0]), spoiled]}]
        self.assertEqual(self.call("poll-show", "!r", "$p", replies=[start, *pages]),
                         "When? [closed]\n1. Friday — 0 votes\n2. Sunday — 1 votes")
        self.assertEqual(self.packets[-1][2]["params"]["from"], "p2")
        with self.assertRaisesRegex(ValueError, "closed"):
            self.call("vote", "!r", "$p", "1", replies=[start, *pages])
        with self.assertRaisesRegex(ValueError, "pagination"):
            self.call("poll-show", "!r", "$p", replies=[start, {"chunk": [], "next_batch":"x"},
                                                         {"chunk": [], "next_batch":"x"}])
        with self.assertRaisesRegex(ValueError, "encryption"):
            self.call("poll", "!r", "Question", "A", "B", replies=[{}])

    def test_invalid_poll_closure_sender_and_moderator_authority(self):
        from mariana import fan_polls as polls

        self.login()
        self.call("poll", "!r", "Encore?", "Yes", "No", replies=[None, {"event_id": "$p"}])
        start = {"event_id": "$p", "room_id": "!r", "sender": "@author:example.org", "type": polls.START,
                 "content": self.packets[-1][2]["json"]}
        closer = "@peer:example.org"
        end = {"event_id": "$end", "sender": closer, "room_id": "!r", "origin_server_ts": 10, "type": polls.END,
               "content": {polls.END: {}, "m.relates_to": {"rel_type": "m.reference", "event_id": "$p"}}}
        for power, expected in ((0, "open"), (50, "closed")):
            context = {"event": end, "state": [
                {"type": "m.room.create", "state_key": "", "sender":"@admin:example.org", "content":{"room_version":"10"}},
                {"type":"m.room.power_levels", "state_key":"", "content":{"redact":50,"users":{closer:power}}}
            ]}
            self.assertIn(f"[{expected}]", self.call("poll-show", "!r", "$p", replies=[start, {"chunk":[end]}, context]))
            self.assertEqual(self.packets[-1][2]["params"]["limit"], 0)
        with self.assertRaisesRegex(ValueError, "verify"):
            self.call("poll-show", "!r", "$p", replies=[start, {"chunk": [end]}, {}])

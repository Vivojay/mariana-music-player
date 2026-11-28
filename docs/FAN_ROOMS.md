# Artist conversations with Matrix

Use a Matrix account on a homeserver you trust and a dedicated Mariana session/token from that server. Each command makes an explicit request. Run the commands in Mariana's terminal or desktop terminal. Room identifiers in the examples are placeholders.

```text
fanroom login https://matrix.example.org
fanroom status
fanroom join #indie-listeners:example.org
fanroom rooms
fanroom read !the-room-id 12
fanroom post !the-room-id Have you heard this recording?
fanroom reply !the-room-id $original-event Yes, the live version.
fanroom react !the-room-id $original-event 🎵
fanroom thread-post !the-room-id $original-event More about the live recording
fanroom thread !the-room-id $original-event
fanroom poll !the-room-id "Best set time?" "Friday night" "Saturday noon"
fanroom poll-show !the-room-id $poll-id
fanroom vote !the-room-id $poll-id 2
fanroom poll-end !the-room-id $poll-id
fanroom wait !the-room-id 15
fanroom report !the-room-id $original-event Spam
fanroom leave !the-room-id
fanroom forget
```

Login prompts privately for an existing Matrix access token, checks the account with the specified HTTPS homeserver and stores the account in the OS credential vault. Use the homeserver's actual client API origin (it can differ from the domain in your Matrix ID). A supported protected keyring and an interactive hidden prompt are required for login. `forget` removes the saved local login; use the homeserver's device/session controls to revoke an issued token. Mariana accepts one active account. It never prompts for a Matrix password.

`join` prints the actual room ID. Use this ID for membership, reading and posting. Anyone with access to the room under its homeserver's rules may see what you send. Text, reply, thread and emoji publishing check the room's encryption setting and refuse encrypted rooms. An encrypted event is labeled in the timeline. Use a full Matrix client for end-to-end encrypted conversations, account setup, device verification, contact blocking or room administration. Reports go to the configured homeserver. Room membership, messages and reports are external actions.

`read` shows up to 50 recent events in chronological order and includes the event ID for replies, reactions and reports. `wait` opens a single bounded long poll after establishing a current sync cursor, expires in up to 25 seconds plus network time, and displays the arriving events for that room. A homeserver can answer early, and `read` retrieves the latest messages between polls. There is no permanent connection, push notification or silent polling. If sending times out after the server might have accepted a message, check the room before repeating it.

`thread` shows the original post followed by chronological replies on the requested page. It validates the room, parent, sender and relation, removes duplicate events, and prints a cursor for older replies. `thread-post` uses Matrix’s standard thread relation and includes a reply fallback for older clients.

Polls use the deployed MSC3381 namespaced events. They are disclosed, single-choice room polls with 2–20 choices. Anyone with permission to read the room can inspect individual vote events. Mariana shows aggregate counts, supports changing votes and lets the poll creator close the poll. It resolves historical room power levels before honoring another person’s moderator closure. It uses the latest pre-close vote per sender, ignores cross-room/parent events and stops instead of reporting partial tallies when it cannot verify the result. One refresh reads at most 500 related events and checks at most five disputed closure events. Undisclosed or multi-select polls, encrypted rooms and interoperability with other clients need separate work or verification. [Matrix poll proposal and interoperable event format](https://github.com/matrix-org/matrix-spec-proposals/blob/main/proposals/3381-polls.md)

Eight deterministic tests cover the protocol exchange, encrypted-room refusal, response handling, hidden prompts, room/sender/parent validation and thread pagination. A separate loopback HTTPS smoke test used a trusted temporary certificate and two fixture accounts to join a room, send/read a message, post a thread reply and read its aggregate through the real HTTP client. The same fixture created a poll, accepted and replaced the second account’s vote, tallied it and closed the poll. Live interoperation with accounts on independent Matrix servers, the native OS credential vault, server-side moderation outcomes, encrypted rooms, always-on notifications, poll support on third-party clients and mobile chat UI require further implementation or release testing as applicable. [Matrix client-server specification](https://spec.matrix.org/latest/client-server-api/)

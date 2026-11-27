# Private listening rooms

Two people can sign in with different Matrix accounts, meet in an invite-only room, suggest tracks and share play, pause and seek cues. Each person loads their own copy of the track. Suggestions and cues contain a title, with the action and position included for cues. Playback starts only when a participant applies a cue. Matching uses the displayed title, so choose the same recording and edition.

## Try a two-person jam

Use separate computers or OS user profiles. Each profile keeps one Matrix account in the system credential store. An existing Matrix account and a reachable homeserver are required.

1. In each Mariana terminal, run `jam login https://YOUR-HOMESERVER`. Sign in through the browser the player opens. The homeserver must support Matrix SSO and allow the desktop loopback return. On a token-only server, `fanroom login https://YOUR-HOMESERVER` accepts an existing Matrix access token at a hidden native prompt. Both commands use the same account.
2. Alice runs `jam create Evening rehearsal`, then `jam invite !ROOM:server @bob:server`, using the exact ID returned by create. Room IDs on some homeservers have no colon.
3. Bob runs `jam invites`, copies the room ID and runs `jam join !ROOM:server`. Both people can run `jam members !ROOM:server` and `jam rooms`. The rooms and invitations lists include other Matrix rooms on this account.
4. Bob runs `jam suggest !ROOM:server Practice piece`. Alice reads it with `jam timeline !ROOM:server`. The timeline shows the latest 50 jam events. The room's host sets playback cues. For example, `jam cue !ROOM:server play 12.5 Practice piece` shares a play cue at 12.5 seconds. To share the loaded track and current playhead, use `jam send !ROOM:server`.
5. Bob loads the track titled `Practice piece`, runs `jam current !ROOM:server` to inspect the cue, then `jam apply !ROOM:server` to seek and play on his own device. Paused and playing tracks with a finite seekable timeline are supported. **Apply** uses the shared mark. **Sync to host position** (`jam sync !ROOM:server`) also advances a play cue by the time since the homeserver timestamped it. This is a one-time alignment at normal playback speed. Clock differences and network latency affect accuracy. Ask the host to send a new cue after changing track, speed or position.
6. Each participant can run `jam leave !ROOM:server`. `jam logout` revokes the current Matrix session and removes its credential. `fanroom forget` removes only the locally saved credential if the server is unreachable. Other room members retain the room history according to the homeserver's configuration.

## Surfaces

| Surface | Listening room access |
| --- | --- |
| Native CLI, full-screen TUI, Electron terminal | Same `jam` commands. In the TUI press `:` then type the command. |
| Local web Console and Flow | Start `python tools/build_web_player.py --serve` on the computer. Open its printed URL. Choose **Listening rooms** or type `jam help`. **Share my playhead** sends the current track title, position and play/pause state. **Apply cue** targets this browser's loaded track. |
| Native companion browser session | Commands operate the connected native player's audio. |
| Static hosted web build, standalone Android/iOS wrapper, watches | The Matrix room client currently requires the native runtime or the desktop loopback launcher. The hosted/static shell displays that requirement. Watch standalone sessions and dedicated native mobile account transport are pending. |
| Voice and video | To open the separate opt-in conference panel on the computer, run `python tools/build_web_player.py --serve --view voice`. Joining a Matrix room and joining a conference are independent actions. |

The homeserver manages identities, membership and history. Mariana uses its HTTP API on demand. Browser login opens the selected server's SSO flow and exchanges a one-use login token. The loopback web player calls the local runtime, which owns the access token. Private Matrix listening rooms use access-controlled membership and readable room events. Homeservers can read room metadata. The client refuses to publish suggestions or cues in encrypted rooms. A listener does not receive another participant's media bytes, microphone, or remote-control access.

For text chat, replies, reactions and polls in a joined jam, run `fanroom help` and use the same room ID. A supported desktop browser can [record one mix of the selected meeting tab and local microphone](LIVE_SPEECH.md) with participant agreement. Continuous audio relay, a shared transport clock, isolated participant recordings, host transfer and an in-app standalone mobile room client remain pending. See the release status before testing a specific platform.

The room workflow uses Matrix private room creation, membership, state events, the message timeline, SSO and logout. [Matrix client-server specification](https://spec.matrix.org/latest/client-server-api/)

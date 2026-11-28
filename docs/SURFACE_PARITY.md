# Using Mariana across players

The portable web player runs on its own device. A browser on the computer running Mariana can also use the native player's library, audio output, and command dispatcher. These are separate listening sessions. The native browser workspace shows which player is active.

## Connect a browser to the native player

1. Run `web session flow` or `web session console` at the native Mariana prompt. Open the private invitation and choose **Connect native session**.
2. For the first browser command needing approval, enter **a** in Mariana to approve the tab for this session while keeping command output in the terminal. Enter **as** to share browser-requested commands' printed output too. Use **r** or **s** to approve only the current command, or Enter to skip it. Playback shortcuts, `now`, and `progress` run directly.
3. To grant approval when starting the session, run `web session flow --trust`. Add `--share-output` when you want results in the browser. The invitation is a credential. Open it in the browser tab you intend to control the native player and keep it private.
4. Use **Review commands again** in the browser or `web revoke` in Mariana to return to individual approval. Native command-specific confirmations, follow-up questions and dialogs still use the host. Closing or reloading the tab, or losing connectivity until the session expires, requires a new invitation and approval.

The paired native prompt stays interactive. Run regular Mariana commands there while the browser is connected. The browser shows the shared player's playback state, queue position and color palette. A browser command can briefly take the prompt while it runs. The terminal restores unsubmitted text when the paired prompt returns.

| Enter in the paired Mariana terminal | Effect in the browser |
| --- | --- |
| `web view flow` or `web view console` | Switch the paired tab's layout. |
| `web focus command`, `web focus search`, `web focus library`, `web focus now` | Focus the requested part of the tab. |
| `web draft search lyrics` | Put a command in the browser editor for review. It runs when the browser user submits it. |
| `web library Miles Davis` | Search native library titles and tags in the paired tab when library browsing is enabled. |
| `web notice Playback is ready` / `web clear` | Post a plain-text notice or clear the paired command transcript. |
| `web status` | Show approval, output visibility and the most recent browser action's acknowledgement. |
| `web approve private`, `web approve share`, `web revoke` | Change the current tab's approval from the terminal. |
| `web close` | Disconnect the browser and return to the ordinary Mariana prompt. |

In standalone FLOW, **Connect native player** accepts a private invitation. In Console, enter `native` to open the same invitation control. The paired page can browse the native library if **Show my library titles and tags in this tab** is enabled. Play and Queue buttons use the same approval policy as other typed native commands.

The [follow-up status](STUDIO_NEXT.md), [workbench matrix](STUDIO_WORKBENCH.md) and [release matrix](PORTABLE_RELEASES.md) describe synths, real-time effects, native plug-in rendering, profiles, input recall and current distribution artifacts.

## Paired Flow and Console

Flow exposes the native Home, library, queue, playlists, albums, liked recordings, live radio and command catalog. Its playback controls include a scrubber with local preview and a media-bound seek, likes and ratings, volume, repeat and shuffle. The paired Console uses the native prompt and shared keyboard-first scrollback. [Control and command coverage](CLI_FLOW_COVERAGE.md)

## Capabilities by surface

| Capability | Native CLI, TUI and desktop terminal | Paired browser Console and Flow | Standalone browser, Android and iOS web player | Watch releases |
| --- | --- | --- | --- | --- |
| Command parser and transport | Same native dispatcher and audio session. | The same dispatcher runs on the host. The browser selects a command, shows playback and can display its output. | Portable JavaScript commands and device playback. Native commands require a computer with `web session`. | Dedicated watch playback and its documented subset. |
| Library, queues, playlists, tone, discovery, artists, social and DSP commands | Native library and backend. Some operations depend on a configured provider, executable or device. | Use the host's commands, settings, library and dependencies. Playback comes from the host. | Imported library with search, local file/URL playback, independent local queue and theme, browser tone rendering, feeds, catalog, music wall and other portable controls. Browser libraries and native file paths are separate. | See [platform support](WEB_MOBILE_WATCH.md). |
| Karaoke and sharing a clip | Commands and dialogs use native files, timing documents, encoders and OS share support. | Native commands operate on the host's loaded media and files. Use the portable player for the browser karaoke stage or the local browser share sheet. | Portable controls operate on media loaded into the browser player. File formats, media identity, browser decoding and OS share targets determine availability. | Both watches support the [offline duet and selected-range WAV sharing](WATCH_PRACTICE.md). External score imports, stream slicing and direct-account publishing remain open. |
| Interactive workflows | Terminal questions and native dialogs. Electron can open its own panels. | Browser command requests use the current review or session approval policy. Answer native interactive questions in Mariana. Native `tui`, video and Electron windows stay on the host. `web session` itself cannot be nested from the browser. | Browser forms, system file selectors and native share sheet where available. | Dedicated watch controls only. |
| Sync across devices | Native state belongs to the running host. | Track state is polled directly from the same native session. | Hosted sites and phones on another device cannot attach to a desktop through its loopback address. Cross-device command transport and automatic library sync remain open. | Standalone app state. |

## Connection boundaries

The native command listener exists only while the foreground `web session` command is running. It binds to an ephemeral port on 127.0.0.1 and serves the paired workspace and its command editor assets. The invitation is consumed once, travels in a URL fragment and is removed from the address bar. An unused invitation expires after five minutes. A connected tab expires after 90 seconds without authenticated contact and has an eight-hour absolute limit. Session credentials stay in the tab's memory. Each API request checks an exact loopback Host, a same-origin POST, a matching credential and JSON body. Command suggestions are read-only and use the installed native grammar. Suggestions use syntax without looking at host files or credentials. The separate authorized library endpoint returns only bounded pages of titles and tags, library indices, and opaque selection keys. The API does not offer CORS or read arbitrary files by HTTP path. Browser command submissions are serialized and the native dispatcher applies its regular focus/replay rules. A hidden or restricted native session drops access.

Command output returned to the tab is limited to the latest 32,000 characters per submitted command, and its on-page log retains 64,000 characters. The backend shares foreground printing when requested. Approval lives only in the pairing process. Browser actions use a fixed vocabulary, one outstanding action at a time, and expire after 20 seconds without acknowledgement. System stderr, native child windows and answers entered into native prompts stay on the host.

The component and API regressions cover one-use pairing, foreign origins, changing visibility, expiry, single-command ownership, explicit approval and private versus shared output. Acceptance in signed native mobile/watch packages, physical audio routing and OS-specific dialogs remains open.

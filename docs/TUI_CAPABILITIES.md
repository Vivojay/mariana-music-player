# Terminal player capabilities

Start in an interactive terminal with `python main.py --tui` or `python main.py tui`. The full-screen player uses the current session, library, queue, audio output and appearance. From a browsing view, **Q**, **Esc** or **Ctrl+C** asks to exit Mariana. Declining keeps the player open. When visibility is off, focus mode is active or a recipe owns playback, the direct launcher displays only controls for restoring access or exiting. It restores the workspace as soon as the restriction clears. Entering `tui` at the ordinary Mariana prompt instead opens a nested view. Closing that view returns to its originating prompt. The command `exit` in either view closes the app after confirmation.

Direct launch skips the CLI banner, homepage printout and optional Tk splash. On a fresh or interrupted installation, the full-screen setup view walks you through media tools, library folders and optional samples. It also hosts the one-time media-tool repair offer for older installations. Type your answer and press **Enter**, or select **Yes** or **No** when offered. **Page Up/Down** scrolls the output. **Esc** leaves setup at the next prompt or progress update. Run the same launch command to resume. When setup finishes, the player opens in the same terminal screen. Fatal startup failures are printed in the launching terminal. For a browser interface to this native session, see [native Console and Flow](SURFACE_PARITY.md).

Commands run in the open workspace. The output view updates during execution. When a command asks for a selection or confirmation, enter the answer in the field inside the TUI. Passwords are masked. **Esc** cancels an active question. Use **Page Up** or **Page Down** to read earlier options while preserving your partially typed answer. In the workspace or transcript, **Ctrl+C** requests cancellation of a running command and discards queued commands. Commands that support cancellation stop at their next check. The command `clear` empties the transcript and its dashboard preview. The playback strip, selection and recent command output share the available space. Widen the window for a side-by-side inspector, or press **i** to inspect the selection on a narrow terminal. You can click the view names, transport controls and footer actions in terminals with mouse support.

| View or control | How to use it |
| --- | --- |
| F2 Player | Inspect playback, use Space to pause or resume, use Left/Right to seek ten seconds, and use the bracket keys for previous/next. T cycles the saved theme. |
| F3 Library | Browse indexed titles, artists and albums with the arrow keys. Filter with `/`, then press Enter on a recording to play it. Untagged files show their filename, format and folder. |
| F4 Queue | Navigate and filter the live queue. Enter on a recording jumps to it. Library and queue rows recheck the selected identity when activated. |
| F5 Discover | Browse actions for artists, releases, radio, and spoken media. Select a command to review and fill its arguments. |
| F6 Commands | Search the native command catalog and completion grammar by name, description, alias or argument. Select a form to see its syntax, choices and flags. Enter places an editable command prefix in the editor. |
| F7 Keys | Show keyboard controls. Tab and Shift+Tab switch views while browsing. |
| F8 DJ | View both playheads, load local tracks, play, pause, seek, set hotcues, loop, adjust deck gain/rate and the crossfader, record, export and share. |
| F1 or `:` | Enter any command accepted by the Mariana prompt. Tab completes the word under the cursor, including known options and locally available values. On a suspected typo, Enter offers an edit. Use Shift+Tab to cycle alternatives. Press Tab to accept an edit, then Enter to run. Esc keeps the original text. Up/Down recall commands submitted in this workspace. |
| Ctrl+K | Open the command palette from the workspace, output or editor. Type to search forms, aliases and descriptions. Arrow keys or Page Up/Down select a match. Enter or a click copies it into the command editor. Esc restores the previous view and draft. |
| Ctrl+R | Search command history, most recent first. Enter edits the selected line. Up/Down in the command editor also recalls prior entries and restores the unfinished draft. |
| Ctrl+O | Read the output transcript. Ctrl+Up/Down jumps between command blocks. The heading shows running or elapsed time and queued command count. Up/Down and Page Up/Page Down scroll, Home/End jump to its boundaries, and Escape returns to browsing. The newest 524,288 characters are retained for this TUI session. Exiting `tui` discards its transcript. |

Interactive operations use the regular command dispatcher, including confirmation questions, focus-mode and session-replay restrictions, and online settings. Select a library recording or queue row to play immediately. Selecting a command template lets you edit it before submission. See the [command reference](../help.md).

## Sound design and arrangements

In **F2 Player** select **Twinkle · harmony and chorus** to put `tone procedure play twinkle` in the editor. Enter plays it. Select **Effects rack** to inspect what is active with `fx status`. Search **Ctrl+K** for the full command forms. See the [score syntax](TONE_PROCEDURES.md) and the [effects and microphone controls](SOUND_DESIGN.md).

## Karaoke, clips and connected services

Press `:` and enter `karaoke demo` for the singing view. Karaoke, the lyrics reader and live speech captions open inside the same TUI. Press **Q** to return. In live captions, press **S** to stop recording and return. Use `karaoke status` to inspect the active recording’s timing confidence. `clip range 0:15 0:25` followed by `clip share` prepares a ten-second file from eligible audio or video. `accounts` lists sign-in and profile options. The [surface guide](SURFACE_PARITY.md) covers how these operations work from the portable player and watches.

## Lyrics, library and history files

`lyrics edit` opens the loaded local track’s adjacent LRC file. If lyrics are available and the sidecar is missing, Mariana asks before creating it. `open lyrics` opens the generated lyrics text, and `open library` opens the library file. Edit either in the terminal, press **Ctrl+S** to save and return, or press **Esc** twice to discard changes. The editor accepts UTF-8 files up to 512 KiB, retains an existing byte-order mark and existing line endings, and reports a conflict if another program changes the file while you edit. Reopen the file to edit the newer version.

Input recall defaults to 100 distinct printable commands in memory per interactive reader. In the TUI history palette use **Ctrl+S** (or **F9**) to enable or disable saving for the active listener profile. While enabled the CLI and TUI share recent safe playback commands such as `seek +10s` or `video open`. Free-text searches, paths, URLs, credentials, and other unrecognized command forms stay out of persistent recall. Setup answers, PINs and hidden prompts bypass the command editor. Disabling saving erases saved rows. Press **Ctrl+X** twice in history to clear this reader’s recall and the profile’s saved rows. In the ordinary interactive CLI, use Up/Down or Ctrl+R to recall inputs. In the portable web Console, FLOW command bar, and paired web session, select **History**, or focus the command field and press **Ctrl+R**, to filter this tab’s submitted lines. Enter puts a result in the field. Use Up/Down when suggestions are closed, or Alt+Up/Down while suggestions are open, to recall lines and restore an unfinished draft. Reloading or disconnecting clears browser recall.

Use `open history` to read the newest 512 KiB of Mariana’s playback activity log. Press **Q** or **Esc** to return. The ordinary CLI continues to use the configured editor or the operating system’s registered file handler.

## Releases, episodes and radio

1. Use `home online enable` to enable online discovery. Run `home picks` or `home picks <words>` to list eligible release, programme and station cards. For every match Mariana prints its exact `home pick <card-id>` command.
2. Run that command and use `home choices` to read the result when the lookup finishes. For a release, use the displayed `home versions <revision> <track-row>` to inspect candidate recordings. A programme or station lists available media directly. The listing includes a next-page command when applicable.
3. Run the displayed `home play <revision> <row>` or `home queue <revision> <row>` after checking the version. The revision binds the row to what you saw. If a selection changes, read `home choices` again. `home cancel` closes the current selection.

The terminal and desktop use the same selection service, edition checks, ten-minute expiry, online consent, and media-availability checks. Artist identity, follows, releases and updates are available through the [artist commands](ARTIST_DISCOVERY.md).

## Features that depend on the host

| Feature | Status in an ordinary terminal | Electron or other host |
| --- | --- | --- |
| Library and playlists, queue groups, albums, download jobs, podcasts and audiobooks | Use the dedicated library and queue views or the normal commands, including `queue tree`, `playlist list`, `album search`, `download-ya status` and `librivox search`. | From the desktop terminal, `desktop open queue`, `playlists`, `albums` and `downloads` open the corresponding drawers. Each panel name follows `desktop open`. |
| Sleep timer and station recommendations | `sleep` and `station` accept the same settings and operations as the player. | `desktop open sleep` and `desktop open station` open the existing controls. |
| Tones, DSP, themes, lyrics and chapters | Use `tone help`, `eq status`, `eq deesser gentle`, `theme colors`, `lyrics` and `chapters list`. Playback uses Mariana's audio engine. | Terminal colors depend on terminal emulator support. Theme configuration is shared across the Python surfaces. |
| Strudel composition | `strudel new "Evening Pattern"`, then `strudel export "Evening Pattern" "evening.js"`. Edit the UTF-8 file and run `strudel import "Evening Pattern" 1 "evening.js" 12` if the exported revision was 1. This saves a 12-second preview duration. Subsequent edits require the new revision. | `strudel play "Evening Pattern"` requests the isolated desktop renderer. `strudel render "Evening Pattern" "evening.wav"` writes a standalone oscillator preview with Node.js. Arbitrary Strudel evaluation and an in-terminal code editor still require another surface. |
| Video picture, captions over video, mini-player and cover images | Enter `play current --video` or `video open` for a separate picture window on a graphical desktop. Pause and seek from the TUI. Enter `video close` to keep listening without the picture. | `desktop open mini` opens the native mini-player in the attached desktop session. Native window sizing, always-on-top and video overlays belong to the graphical host. |
| Release and programme cards | Search and select real recordings with the native terminal workflow above. | Card images and visual layouts require a graphical renderer. |
| Desktop host controls | A terminal emulator controls its fonts, windows, tabs, graphical scrollback search and system menus. The TUI has no updater, system tray, desktop shortcut editor, or graphical resume-offer overlay. | Host-owned actions and corresponding graphical views require the desktop build and platform support. |
| Web FLOW, device and watch interfaces | The TUI runs in a terminal attached to the Python player. Scrollable command output and keyboard pages are its user interface. | Browser FLOW and device builds have their own rendering and release status. See the [platform tracker](PLAYER_EXPANSION_STATUS.md). |

The workspace has dedicated Player, Library, Queue, Discover, Commands, Keys and DJ views. Other command families, including fan rooms, Music Wall, sessions, paired desktops and broadcasting, use their existing text commands and output. Dedicated graphical-style forms for every command family and end-to-end checks on physical Windows/macOS terminals and native Electron windows are pending.

## Windows native commands

The TUI gives its serial command worker a Windows COM apartment. This lets `mvol` reach the default Core Audio endpoint and lets the Windows shell resolve a registered file or browser handler on the calling thread. Endpoint discovery retains its existing PortAudio fallback. Electron handles copying terminal selections through its main-process clipboard bridge. [Windows COM initialization](https://learn.microsoft.com/en-us/windows/win32/learnwin32/initializing-the-com-library) · [ShellExecuteW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecutew)

Physical Windows acceptance is pending. On the development laptop, launch `python main.py --tui`, press **:**, run `output device`, then run `mvol`. Set `mvol` to the percentage just reported and confirm the next `mvol` shows the same value. In Electron, select and copy command output, paste it into a text editor, and open a local media item in Explorer. The worker tests use a real Python thread with simulated Core Audio and shell APIs.

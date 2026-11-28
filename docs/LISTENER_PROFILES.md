# Listener profiles

Use a listener profile when two people share a player or when you want to keep a studio library separate from everyday listening.

## Native CLI, TUI and Electron

Enter these commands in Mariana. From the TUI, open the command field with `:`.

```text
profile list
profile create "Studio Sessions"
profile use "Studio Sessions"
```

Quit and reopen the player. The switch takes effect at startup, when Mariana opens its library, settings, logs and credential store. A running session keeps its original profile, including any recording or playback in progress. Use `profile current` to check which profile owns this session. `profile list` also identifies the profile selected for the next launch.

`profile rename "Studio Sessions" "Practice Room"` preserves the same database, files and keychain entries. `profile use Default` selects your original installation. From PowerShell, `& .\.venv\Scripts\python.exe .\main.py tui --profile "Practice Room"` opens an **existing** profile for a single run. Electron offers list, create and select in **Connections → Listener profiles**.

New profiles start with the packaged settings template, an empty library index and fresh setup. They have their own settings, library roots, play counts, subscriptions, application state, cached media, sessions, and native account/Matrix/broadcast keychain namespaces. Legacy data and keychain references remain under Default. Media files and explicit exports in folders you choose are shared filesystem resources. Publisher-supplied app credentials, system software, and the browser session used for provider sign-in are installation resources. A listener profile organizes personal data under the current OS account. OS logins provide access control between people.

The registry resides under `MARIANA_DATA_DIR` or Mariana's platform data directory. The native CLI and TUI share their data root. Electron ordinarily uses its own `userData/runtime` directory and has its own registry. First-boot and release checks for each target are tracked in the release status documentation.

## Portable player, FLOW and mobile web shells

Open **Connections → Listener profiles** or enter `profile create Studio`, then `profile use Studio`. Switching reloads the tab and stops its current media. The selected profile stays with that tab across reloads. Profile names and data remain available to other tabs on the same origin. Each independent tab starts in Default. The origin's original queue and settings remain in Default.

Profiles separate the browser queue, bookmarks, imported audio database, preferences, public account links, pending browser grants, music walls, public feed shelf and Strudel draft. Browser OAuth access tokens remain in page memory. A named browser profile uses browser-supported connections. Default can also use the local launcher's native account and jam sessions. An explicitly paired companion controls its paired native player. Static, native and mobile/WebView storage are independent. Browser onboarding and local playback do not require a cloud account.

## Other identities in Mariana

`wall profile` edits the public-facing artist/listener wall identity inside a profile. `accounts` manages individual service connections. Jam sign-in authenticates with a homeserver. Cloud login, server-backed device synchronization, listener-level parental controls, profile merging, GUI profile deletion, and cross-device recovery remain open. Use [the connection guide](CONNECTIONS.md) for provider-specific capabilities and setup.

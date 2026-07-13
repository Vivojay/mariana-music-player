# Mariana architecture

Mariana has one command surface and two hosts. `main.py` owns the interactive
REPL. A direct terminal runs it normally; Electron runs the same process in a
native PTY and renders it with xterm.js. UI buttons send ordinary commands to
the PTY. The authenticated side channel reports state but cannot execute
commands.

Electron may render several terminal tabs, but they are views of that one PTY,
not additional Mariana processes. The host retains a bounded ANSI stream for
new views and resets it on terminal-clear sequences. Search is performed by
each view's xterm.js SearchAddon. Theme selection is a normal CLI command and a
structured state event keeps the settings file and React selector synchronized.

Media references are persisted using canonical, non-secret identifiers. Source
resolvers create short-lived playback URLs immediately before use. The playback
supervisor owns retries and failover; the playback controller owns FFmpeg
decoder sessions, bounded PCM, output state, gain stages, and process cleanup.

The program-audio path is:

```text
resolver -> FFmpeg decoder -> ReplayGain/live leveling -> crossfade/program mix
         -> broadcast tap -> user volume/mute/sleep gain -> sounddevice
```

The output supervisor polls the operating-system default endpoint while audio
is active. Endpoint identity comes from Windows Core Audio where available,
then maps to a WASAPI route; a bounded stream replacement follows Bluetooth or
other default-device changes without restarting the decoder or queue item.

SQLite stores queues, library occurrences, jobs, identities, lyrics, loudness,
radio health, recommendations, media preferences, removal journals, and migrations. The library profiler uses
leased resumable stages so discovery, probing, fingerprinting, loudness, and
optional network enrichment can recover after interruption.

The initial persistent queue is a projection of available library occurrences
in canonical library order. It continues tracking library scans until an
explicit queue mutation marks it custom; `queue reset` deliberately recreates
the projection. Direct local selection reuses the queued library identity, so
decoder completion advances exactly one authoritative queue rather than a
separate legacy playlist.

First-run setup is a small state machine in the writable data directory. Its
atomic state file and PID/creation-time lock make each library/sample/launch
step resumable and idempotent. Completion is recorded before the optional
“run now” choice returns, so a declined launch cannot cause another wizard.
Existing pre-state-file installations are marked migrated/complete.

Safe media removal crosses a filesystem/database transaction boundary using a
small SQLite journal. Mariana validates an indexed local occurrence, asks for
confirmation, sends it through Send2Trash, then tombstones the occurrence and
removes queued copies. Startup recovery reconciles a successful trash action
whose database update was interrupted; permanent deletion is never a fallback.

External tools are resolved from an explicit setting, Mariana's verified
managed-tool directory, a legacy local tool directory, then `PATH`. Managed
activation uses same-volume renames and restores the prior version if the new
directory cannot be activated.
The first-run bundle contains FFmpeg/FFprobe/FFplay, fpcalc, rsgain, and Deno;
downloads are checksum-verified in staging and expose bounded progress updates.
The setup-complete marker remains authoritative, while older installations get
at most one versioned tool-bundle repair offer instead of rerunning the wizard.

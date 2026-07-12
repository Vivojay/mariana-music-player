# Mariana architecture

Mariana has one command surface and two hosts. `main.py` owns the interactive
REPL. A direct terminal runs it normally; Electron runs the same process in a
native PTY and renders it with xterm.js. UI buttons send ordinary commands to
the PTY. The authenticated side channel reports state but cannot execute
commands.

Media references are persisted using canonical, non-secret identifiers. Source
resolvers create short-lived playback URLs immediately before use. The playback
supervisor owns retries and failover; the playback controller owns FFmpeg
decoder sessions, bounded PCM, output state, gain stages, and process cleanup.

The program-audio path is:

```text
resolver -> FFmpeg decoder -> ReplayGain/live leveling -> crossfade/program mix
         -> broadcast tap -> user volume/mute/sleep gain -> sounddevice
```

SQLite stores queues, library occurrences, jobs, identities, lyrics, loudness,
radio health, recommendations, and migrations. The library profiler uses
leased resumable stages so discovery, probing, fingerprinting, loudness, and
optional network enrichment can recover after interruption.

External tools are resolved from an explicit setting, Mariana's verified
managed-tool directory, a legacy local tool directory, then `PATH`. Managed
activation uses same-volume renames and restores the prior version if the new
directory cannot be activated.

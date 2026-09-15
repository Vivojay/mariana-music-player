# Personal interaction hotspots

Mariana can optionally capture successful play, pause, and seek actions for a
progress-bar hotspot overlay. Capture is local and disabled by default.
It measures this installation's explicit interactions; it is not global
popularity, audience analytics, or listening-duration measurement.

## Capture contract

The authoritative playback controller submits one immutable event only after an
action succeeds. Each event contains a random event ID, Unix timestamp, opaque
stable media identity, playback-session ID, action origin, and source position.
Play events distinguish starts from resumes. Seek events retain both origin and
effective destination positions after duration and preferred-region clamping.

No path, credential, title, provider URL, resolved playback URL, or terminal
command is stored. CLI, main-desktop, and Mini-player actions are distinct from
automatic queue promotion, output recovery, and system automation. Automatic and
recovery events are retained for diagnostics when capture is enabled but are
excluded from personal-interest aggregation by default.

Submission uses a 512-item nonblocking queue. A background worker writes batches
of up to 32 events to SQLite, normally within 250 milliseconds. A full queue
drops the new event and increments the visible dropped-event counter; playback
never waits or fails. Shutdown drains the queue for up to two seconds. Persistence
failures are counted and isolated from playback. Event IDs are unique, so a
repeated submission is ignored instead of double-counted.

Optional log forwarding reuses the successfully persisted structured event and
is independent of capture. Changing diagnostic log level never enables, disables,
or reconstructs event persistence, and logs are never parsed as an event source.

## Commands and retention

```text
hotspots status
hotspots enable
hotspots disable
hotspots retention 90
hotspots logging on|off
hotspots clear --yes
hotspots current [bin-seconds] [linear|log1p]
```

Retention accepts 1–3650 days and defaults to 90. Disabling capture stops new
events without deleting existing history. Clear is explicitly confirmed and
removes events already ordered before that request; a concurrent later action can
still be captured. Expired rows are purged on startup, after retention changes,
and hourly during long-running sessions. All controls persist through the normal
settings mechanism.

## Aggregation and visualization

An event at position `p` belongs to bin `floor(p / width)`. Each bin preserves
separate counts for play starts, play resumes, pauses, and seek destinations.
Seek origins are retained in storage but do not contribute to destination bins.
Bin widths must be finite and positive. A width too small to represent a stored
position's bin index is rejected without changing the width or stored history.

The default linear intensity is `bin_count / maximum_bin_count`. Optional
`log1p` intensity is `log1p(bin_count) / log1p(maximum_bin_count)` and can make a
long tail visible without changing bin membership or event counts. These are two
normalization choices; neither is statistical standardization. Any future chart
is labelled **Personal interaction hotspots**, exposes its scale, and keeps the
underlying action types distinguishable in the stored and projected counts.

The desktop overlay and its typed projection are a separate delivery. This batch
provides local capture, persistence, command controls, and tested aggregation only.

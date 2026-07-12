# Mariana test suites

The deterministic Python suite mocks network and audio-device boundaries while
using real SQLite transactions. Real-process tests generate WAV, MP3, FLAC,
OGG, AAC, and WebM media and exercise FFmpeg, FFprobe, Chromaprint, and encoded
Opus/MP3 broadcast output when those tools are installed.

The frontend uses Vitest for renderer, preload-facing state, accessibility, and
terminal lifecycle behavior. Playwright launches Electron with the real
node-pty to verify commands, ANSI-compatible output, history, resizing, theme
changes, timer controls, restart, and process-tree shutdown.

Canonical commands, live-test policy, mutation scoring, coverage thresholds,
packaged testing, manual acceptance, and the eight-hour soak are documented in
[the testing guide](../docs/TESTING.md). Current feature-to-evidence status is
tracked in the [verification matrix](../docs/VERIFICATION_MATRIX.md).

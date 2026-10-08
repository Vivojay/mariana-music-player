# Local listening equalizer

Open **EQ** in the desktop toolbar, or use `eq` / `eq status` in the terminal.
New installations default to bypass, ten flat bands, and 0 dB preamp. Settings and
user presets are stored in the existing user settings file; explicit saved values
are preserved. Invalid saved EQ data falls back to bypass with a warning without
overwriting that data merely on startup.

## Controls

```text
eq on
eq off
eq band 125 -3
eq band 1k 2.5
eq preamp -8
eq reset
eq preset list
eq preset apply "Bass Boost"
eq preset save "Evening listening"
eq preset delete "Evening listening"
```

Bands: 31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000 Hz, each -12 to +12 dB.
Frequency suffixes are case-insensitive: `1000`, `1000Hz`, `1k`, and `1kHz` identify
the same band. No nearest-band rounding. Preamp range: -36 to +12 dB. Numeric values
must be finite; desktop sliders use 0.5 dB steps. CLI accepts fractional dB values.

Reset restores flat bands and 0 dB preamp **without changing enabled/bypassed state**.
Applying a preset also preserves that state. Factory Flat, Bass Boost, Treble Boost,
and Vocal Clarity presets are tonal preferences, not objectively better sound or
stem isolation. Factory names are protected. Saving requires a new user name;
existing names are never overwritten implicitly. At most 32 user presets, with
1-48 character names. Deletion names an exact user preset and cannot delete factory
presets. No filesystem or terminal command is derived from a preset name.

## Signal path and ownership

```text
FFmpeg decode / optional live leveling
  -> per-source ReplayGain -> existing crossfade/program mix
  -> broadcast tap (unchanged)
  -> local stereo EQ and EQ preamp
  -> user volume / mute × sleep automation gain
  -> existing output clipping -> audio device
```

All sources routed through the authoritative controller share this path: local,
online, podcast, radio, and video audio decoded there. Separate external players
and exported/downloaded files are not processed. EQ never restarts a decoder,
changes the queue or playback position, or modifies the broadcast signal.

The desktop uses only validated `equalizer.status` and `equalizer.configure`
requests. Each write carries the acknowledged backend revision. CLI writes use
the same serialized service and atomic settings save. The renderer coalesces
pending values per slider, sends one request at a time, and submits the final
value after acknowledgement. Rejected stale writes require refreshed state; they
are not blindly replayed over another controller's changes. The Mini-player API
is unchanged. No EQ action writes terminal text.

## Filters, updates and real-time limits

Ten cascaded RBJ peaking biquads, constant Q = sqrt(2) (approximately one octave at
low frequencies), normalized a0, float64 coefficients and independent left/right
delay state. Constant Q means bandwidth narrows in octaves near Nyquist; this is
reflected in the calculated response, not disguised by a decorative slider curve.
The implementation follows the [W3C Audio EQ Cookbook](https://www.w3.org/TR/audio-eq-cookbook/).
[SciPy sosfilt](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfilt.html)
provides compiled direct-form-II-transposed filtering instead of a Python
sample-by-sample loop. SciPy is the only added runtime dependency.

Filter design, response calculation, ramp/delay allocation and settings saves run
outside the audio callback. A latest-value mailbox publishes prepared banks. At
most two banks run during a 100 ms sample ramp; intermediate pending updates are
coalesced. Stable banks are crossfaded rather than interpolating pole coefficients.
Block processing still allocates bounded NumPy/SciPy output arrays: this is not a
hard-real-time guarantee, and the controller's pre-existing locks remain unchanged.

Current decoders and device streams use 48 kHz stereo PCM. The processor accepts
8-192 kHz rates, excluding bands at or above 0.45 times the processing rate. Those
bands are bypassed and marked unavailable while their settings are retained. A
future output-rate change must construct a new processor outside the callback;
device switching currently retains 48 kHz. No source-file rate is mistaken for
the processing rate.

State persists across blocks and continuous crossfades/source promotion. Pause
freezes filter/ramp state. Explicit seek, stop and replacement playback publish a
reset token, clearing delay memories at the next processing block. Resume continues
the pending ramp. There is no EQ worker/thread to leak on shutdown. Processing
failure/non-finite output returns the original input and sets an unavailable
indicator; a new prepared control update can retry. Missing DSP runtime also
preserves bypassed playback.

## Headroom and response display

Boosts overlap. Factory preamp cuts use the sum of positive band gains plus 1 dB
margin (except Flat), rather than the single largest gain. The visible manual
suggestion is minus the sum of positive boosts, capped at the -36 dB preamp limit.
It is **not applied automatically**. This conservative frequency-domain guideline
does not guarantee transient/true-peak safety, especially with already overloaded
program audio. There is no added compressor, limiter, normalization or main-volume
change. Existing output clipping remains the final device guard.

The overload indicator counts blocks whose EQ output exceeds full scale, before
local volume/mute/sleep gain; it can therefore warn even when listening quietly.
It resets on the next processed block after seek/stop. It is not a true-peak meter
or a retrospective indicator of clipping that happened upstream. Lower preamp if
it lights. The response chart evaluates the actual steady-state coefficients plus
preamp on 128 log-spaced frequencies (20 Hz to min(20 kHz, 0.45 Fs)); the chart shows
-36 to +36 dB and does not depict the temporary two-bank transition.

## Verification and acceptance

Deterministic tests cover impulse/FFT response at seven rates, individual peaks,
combined boosts, flat/bypass identity, stereo isolation, finite extreme output,
block continuity, smooth preamp updates, newest-value delivery, reset, persistence,
factory protection, invalid input, stale control rejection and safe save failures.
Controller tests compare pre-EQ broadcast PCM and post-EQ local output for both
NumPy and byte buffers, including independent mute/sleep/user gains and unchanged
decoder identity/position on configuration.

Desktop tests cover bounded projections, narrow intents, accessible controls,
coalescing, backend revisions and absence of terminal writes. Native geometry tests
are distinct from listening acceptance. Audible click/tonal evaluation on actual
devices, physical Windows DPI settings, and packaged multi-OS acceptance still need
separate verification; source tests alone do not establish those results.

The focused native Electron EQ test passed at 760x520, 1280x820, and 1920x1080,
plus 1.25 and 1.5 renderer zoom. It verifies keyboard updates against the real
backend, zero terminal writes during EQ interaction, modal bounds, reachable reset,
and return focus. Opening a modal itself can emit xterm's normal focus-out report;
that terminal protocol is distinct from executing a command. In-memory visual
inspection led to an opaque themed panel backing so terminal text cannot bleed
through the controls. No visual comparison snapshots are retained.

Local Windows measurement (Python 3.12, 48 kHz stereo, 3,000 warmed blocks per size,
both filter banks active):

| Frames | Median | 99th percentile | Maximum observed | Block deadline |
| --- | --- | --- | --- | --- |
| 128 | 0.097 ms | 0.377 ms | 0.930 ms | 2.667 ms |
| 256 | 0.138 ms | 0.395 ms | 0.819 ms | 5.333 ms |
| 512 | 0.142 ms | 0.458 ms | 1.049 ms | 10.667 ms |
| 1024 | 0.220 ms | 0.598 ms | 1.575 ms | 21.333 ms |

No measured EQ block exceeded its deadline. These timings cover the EQ processor,
not the complete device callback, and are not a guarantee for other hardware or
operating-system scheduling. The real-decoder regression additionally verifies a
44.1 kHz FLAC tone resampled to 48 kHz, measured +3 dB net EQ gain, unchanged decoder
process/position on adjustment, and decoder cleanup.

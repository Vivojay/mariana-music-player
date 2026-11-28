# Mariana wavetable bank

The bank contains 64 original morphing wavetables across reed, organ, vowel, brass, glass, string, pulse and bass. Each table has eight phase-aligned 2,048-sample frames. The native and portable players generate the same harmonic coefficients. Previews sweep through the frames over two seconds, limit the number of harmonics at high pitches and play through the ordinary local transport.

| At the Mariana prompt | Result |
| --- | --- |
| `soundbank list` or `soundbank list glass` | Browse the whole bank or a family |
| `soundbank play glass-opal 330` | Hear the table at 330 Hz in the CLI, TUI, desktop terminal, portable Console or FLOW |
| `soundbank export glass-opal "glass-opal.wav"` | Native multi-frame mono PCM WAV for a compatible wavetable editor |
| `soundbank export glass-opal` | Browser download of that table |
| `soundbank export-all "Mariana-Wavetables.zip"` | Native ZIP with 64 tables organized by family. Choose a new filename |

The release kit also includes that ZIP. To use it in another synth, unpack it, import a WAV as a **wavetable**, choose 2,048 samples per frame where required, hold a note and sweep table position. The short WAV stores cycles at the synth's native table length. It serves a different purpose from a two-second audition at concert pitch. Actual DAW import and proprietary preset formats require host-specific verification. The supplied waveforms can be used and redistributed, including in commercial music.

## External collections and editors

| Source | What it offers |
| --- | --- |
| [Adventure Kid Waveforms](https://www.adventurekid.se/akrt/waveforms/adventure-kid-waveforms/) | Single-cycle waves and instrument-specific packs. The original single-cycle set uses 600 samples per waveform. |
| [WaveEdit community banks](https://github.com/smpldsnds/wavedit-online) | Community CC0 banks organized as 64 waveforms of 256 samples. Use the source format when importing. |
| [Surge XT](https://surge-synth-team.org/surge-xt/faq/) and [Vital](https://vital.audio/) | Desktop synthesis and wavetable editing for users who want to design in a separate instrument. |

These links open the publishers' collections. Factory content and commercial plug-in licences stay with their publishers. See the [effects guide](SOUND_DESIGN.md) for native effect hosting and the [tone guide](TONE_PROCEDURES.md) for saving and playing layered arrangements.

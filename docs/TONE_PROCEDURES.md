# Tone scores and live instruments

In Mariana's command prompt, enter the following command to play the complete 28.8-second arrangement. In the TUI press `:` first. In FLOW use the command field.

```text
tone procedure play twinkle
```

The opening melody is C C G G A A G. A felt-key lead plays all six phrases, a choir synth sustains the changing three-note harmony, and a bass plays the roots. A stereo chorus mixes two continuously modulated, interpolated delays into the score. The choir is a synthesized timbre. Use the regular player controls to pause, seek or stop.

| Command | Result |
| --- | --- |
| `tone procedure play twinkle --bpm 120 --chorus 25 --level 40` | Play a faster arrangement with a lighter chorus and a 40% generator level. |
| `tone voices` | List 26 original timbres, including felt keys, strings, mallet, reeds, two vowels and percussion. |
| `tone keys glass` | Open a playable keyboard. Hold several keys for a chord. Release them for the instrument's release envelope. Escape closes it. |
| `tone synth electric-piano C4+Eb4+G4:2 R F4 A4` | Play a minor chord, a rest and two notes. |
| `tone sfx list` | List kick, snare, hat, footstep, riser and zap. |
| `tone sfx footstep` | Play a synthesized foley cue. |
| `tone procedure list` | List factory and user scores in the active profile. |

## Save a layered arrangement

Enter each line separately in Mariana.

```text
tone procedure save evening 96 @felt-keys C5 E5 G5:2 @choir C4+E4+G4:4 @round-bass C3:4 --chorus 32
tone procedure play evening
```

The word after `save` is a unique name made of lower-case letters, digits or hyphens. The number sets the tempo in beats per minute. Each `@voice` starts a simultaneous part at beat zero. Notes within a part play in order. The default duration is one beat. A suffix such as `:0.5` or `:2` sets a step's length in beats. `+` joins notes into a chord, `R` adds a rest, and `C#4` and `Eb4` are valid altered pitches. Use up to four parts with six notes per chord, 128 steps per part and a total playing time of 90 seconds.

The native CLI, TUI and Electron backend keep saved scores in the active profile's `tone-procedures.sqlite3`. The portable console, FLOW and mobile web bundles use the current browser profile's IndexedDB. Factory arrangements come with every build and work offline. Device-to-device user score sync is pending. Duplicate names are refused, so an existing score survives a mistyped save command.

## Live keys and rendering

The thirteen live keys span C4 to C5. The lower row A, S, D, F, G, H, J and K plays the white keys, and W, E, T, Y and U play the black keys. Browser keys also support multitouch. The live keyboard uses the microphone-free Web Audio synth in the browser or Tk and PortAudio on a graphical native desktop. On native systems it opens the current playback device, falling back to the system default when the player has no active device. Device output sharing depends on OS and audio-driver support. Use `tone synth` from headless terminals. `tone keys` accepts the twenty melodic timbres. The six percussion and noise cues use the finite-score renderer.

Native and portable players synthesize the same score definitions and spectral coefficients at 32 kHz, with harmonics above the bandwidth excluded. Percussion noise has a repeatable seed within each renderer. Ordinary tones and sweeps retain their 48 kHz renderer. All samples here are generated locally. No third-party sample files, licensed preset banks or plugins are required. Additional morphing timbres are available through the [wavetable bank](WAVETABLES.md).

## Verification

The native and portable regression suites exercise the complete factory score, user scores, chord boundaries, rests, chorus stereo differences, duration, signal bounds and synthesized effects. The native mixer test presses two keys, releases them and confirms the output returns to silence. A Linux graphical check delivered a real keypress to the Tk keyboard, captured generated PCM and closed it from the parent. A complete portable-shell command run loaded the factory arrangement, applied the choir AudioWorklet to stereo PCM and restored a user arrangement after switching to another listener and back. That run used simulated browser storage and audio endpoints. Native desktop audio-device acceptance, browser listening on hardware and mobile touch acceptance are still pending.

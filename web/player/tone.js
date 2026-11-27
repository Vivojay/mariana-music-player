/* Offline, finite-length tone previews for Mariana's HTML audio transport. */
(() => {
  "use strict";
  const sampleRate = 48000;
  const waveforms = ["sine", "triangle", "square", "sawtooth"];
  const chords = new Map(Object.entries({
    major: [0, 4, 7], minor: [0, 3, 7], fifth: [0, 7], octave: [0, 12],
    sus4: [0, 5, 7], major7: [0, 4, 7, 11], minor7: [0, 3, 7, 10],
  }));
  const help = [
    "tone sine|triangle|square|sawtooth [Hz] · default 440 Hz",
    "tone harmony <Hz> <Hz> ...  or  tone harmony <root Hz> --chord major|minor|fifth|octave|sus4|major7|minor7",
    "tone sweep <start Hz> <end Hz> [--curve linear|log]",
    "--seconds 0.05..60 (default 2), --level 0..100 (default 15), --wave <waveform> for harmony or sweep",
    "Example: tone sweep 880 110 --curve log --seconds 5",
  ].join("\n");

  function number(value) {
    if (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value)) {
      throw new Error("Enter a numeric frequency, duration or level.");
    }
    return Number(value);
  }

  function parse(args) {
    const options = new Map();
    const values = [];
    for (let index = 0; index < args.length; index++) {
      const token = args[index];
      if (!token.startsWith("--")) {
        values.push(token);
        continue;
      }
      const equals = token.indexOf("=");
      const name = equals === -1 ? token : token.slice(0, equals);
      if (!["--seconds", "--duration", "--level", "--wave", "--curve", "--chord"].includes(name)) {
        throw new Error("Unknown tone option. Enter tone help for the supported commands.");
      }
      const value = equals === -1 ? args[++index] : token.slice(equals + 1);
      if (!value || value.startsWith("--")) throw new Error("Missing value for " + name);
      options.set(name === "--duration" ? "--seconds" : name, value.toLowerCase());
    }

    const mode = (values.shift() || "").toLowerCase();
    let frequencies = values.map(number);
    const seconds = number(options.get("--seconds") ?? "2");
    const level = number(options.get("--level") ?? "15");
    const curve = options.get("--curve") ?? "linear";
    const chord = options.get("--chord");
    if (chord !== undefined) {
      if (mode !== "harmony" || frequencies.length !== 1 || !chords.has(chord)) {
        throw new Error("Choose a chord name and one root frequency, e.g. tone harmony 220 --chord minor.");
      }
      frequencies = chords.get(chord).map(interval => frequencies[0] * 2 ** (interval / 12));
    }
    const wave = options.get("--wave") ?? (waveforms.includes(mode) ? mode : "sine");
    if (!waveforms.includes(wave)) throw new Error("Choose a sine, square, triangle or sawtooth wave.");
    if (waveforms.includes(mode)) {
      if (options.has("--wave") || frequencies.length > 1) throw new Error("Choose a single waveform and frequency.");
      if (!frequencies.length) frequencies = [440];
    } else if (mode === "harmony") {
      if (frequencies.length < 2 || frequencies.length > 8) throw new Error("A harmony takes 2 to 8 frequencies.");
    } else if (mode === "sweep") {
      if (frequencies.length !== 2) throw new Error("A sweep needs a start and an end frequency.");
    } else {
      throw new Error(help);
    }
    if (options.has("--curve") && (mode !== "sweep" || !["linear", "log"].includes(curve))) {
      throw new Error("--curve accepts linear or log for a sweep.");
    }
    if (!frequencies.every(hz => hz >= 1 && hz <= 20000)) throw new Error("Frequencies must be between 1 and 20000 Hz.");
    if (!(seconds >= .05 && seconds <= 60 && level >= 0 && level <= 100)) {
      throw new Error("Choose a duration of 0.05 to 60 seconds and a level of 0 to 100 percent.");
    }
    return { mode, wave, frequencies, seconds, level, curve };
  }

  function wavBuffer(frames) {
    const view = new DataView(new ArrayBuffer(44 + 2 * frames));
    function tag(offset, value) {
      for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
    }
    tag(0, "RIFF");
    view.setUint32(4, 36 + 2 * frames, true);
    tag(8, "WAVE");
    tag(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, 1, true); // mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, 2 * sampleRate, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    tag(36, "data");
    view.setUint32(40, 2 * frames, true);
    return view;
  }

  function stepCorrection(phase, step) {
    const left = Math.max(1 - phase / step, 0);
    const right = Math.max(1 - (1 - phase) / step, 0);
    return right * right - left * left;
  }

  function oscillator(wave, cycles, step) {
    const phase = cycles - Math.floor(cycles);
    if (wave === "sine") return Math.sin(2 * Math.PI * phase);
    if (wave === "triangle") return 1 - 4 * Math.abs(phase - .5);
    const edge = stepCorrection(phase, step);
    if (wave === "square") return (phase < .5 ? 1 : -1) + edge - stepCorrection((phase + .5) % 1, step);
    return 2 * phase - 1 - edge;
  }

  async function render(args) {
    const { mode, wave, frequencies, seconds, level, curve } = parse(args);
    const frames = Math.round(seconds * sampleRate);
    const view = wavBuffer(frames);
    const fade = Math.min(Math.round(.008 * sampleRate), Math.floor(frames / 2));
    const start = frequencies[0];
    const end = frequencies[1] ?? start;
    const slope = (end - start) / seconds;
    const logRate = Math.log(end / start) / seconds;
    for (let first = 0; first < frames; first += 32768) {
      if (first) await new Promise(resolve => setTimeout(resolve, 0));
      const limit = Math.min(first + 32768, frames);
      for (let frame = first; frame < limit; frame++) {
        const time = frame / sampleRate;
        let sample = 0;
        if (mode === "sweep") {
          if (curve === "log" && logRate !== 0) {
            sample = oscillator(wave, start * Math.expm1(logRate * time) / logRate,
              start * Math.exp(logRate * time) / sampleRate);
          } else {
            sample = oscillator(wave, (start + .5 * slope * time) * time, (start + slope * time) / sampleRate);
          }
        } else {
          for (const hz of frequencies) sample += oscillator(wave, hz * time, hz / sampleRate);
          sample /= frequencies.length;
        }
        const envelope = Math.min(frame / fade, (frames - 1 - frame) / fade, 1);
        view.setInt16(44 + frame * 2, Math.round(Math.max(-1, Math.min(1, sample)) * envelope * 32767 * level / 100), true);
      }
    }
    const label = frequencies.map(hz => Number(hz.toFixed(3))).join(mode === "sweep" ? " → " : " + ");
    const kind = waveforms.includes(mode) ? "tone" : mode;
    const title = wave[0].toUpperCase() + wave.slice(1) + " " + kind + " · " + label + " Hz";
    const file = new File([view.buffer], "Mariana-" + kind + "-" + wave + "-" + start + "Hz.wav", { type: "audio/wav" });
    return { file, title };
  }

  window.MarianaTone = Object.freeze({ render, help });
})();

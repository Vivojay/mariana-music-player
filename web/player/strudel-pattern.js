/* Portable oscillator subset of Strudel notation. Parse the entire source as data. */
(() => {
  'use strict';
  const rate = 22050;
  const maxBytes = 65536;
  const unsupported = 'This syntax needs the full Strudel engine. Use “Live editor” or “Open Strudel online” in Flow, or the Electron Strudel editor.';
  function parse(source) {
    if (typeof source !== 'string' || new TextEncoder().encode(source).length > maxBytes) throw Error('Pattern must be at most 64 KiB of text.');
    let rest = source.trim();
    function take(re, optional = false) {
      const match = re.exec(rest);
      if (!match) {
        if (optional) return null;
        throw Error(unsupported);
      }
      rest = rest.slice(match[0].length).trimStart();
      return match;
    }
    function literal() {
      return take(/^(?:"([^"\r\n]*)"|'([^'\r\n]*)')/).slice(1).find(x => x !== undefined);
    }
    function number() { return Number(take(/^(?:\d+(?:\.\d+)?|\.\d+)/)[0]); }
    let cps = 0.5;
    if (take(/^setcps\s*\(/, true)) {
      cps = number();
      take(/^\)\s*;?/);
      if (!(cps >= 0.05 && cps <= 8)) throw Error('Use 0.05 to 8 cycles per second for a portable preview.');
    }
    function layer() {
      take(/^note\s*\(/);
      const sequence = literal().trim().split(/\s+/);
      if (sequence.length > 64) throw Error('Use up to 64 steps per portable layer.');
      const repeats = [];
      const notes = sequence.map(token => {
        const [name, count = '1', extra] = token.split('*');
        if (!/^(?:[1-9]|1[0-6])$/.test(count) || extra !== undefined)
          throw Error('Use one to sixteen retriggers, such as c4*4.');
        repeats.push(Number(count));
        if (name === '~') return 0;
        const match = /^([a-g])([b#]?)([0-8])$/i.exec(name);
        if (!match) throw Error('Use note names with octaves such as c4, eb4 and f#3. Use ~ for a rest. Other mini-notation needs the Electron Strudel editor.');
        const pitch = {c:0, d:2, e:4, f:5, g:7, a:9, b:11}[match[1].toLowerCase()];
        const midi = (Number(match[3]) + 1) * 12 + pitch + (match[2] === '#' ? 1 : match[2] ? -1 : 0);
        return 440 * 2 ** ((midi - 69) / 12);
      });
      take(/^\)/);
      let wave = 'triangle', gain = 1, speed = 1, lowpass = 0, highpass = 0;
      while (take(/^\./, true)) {
        if (take(/^s\s*\(/, true)) {
          wave = literal();
          if (!['sine', 'triangle', 'square', 'sawtooth'].includes(wave)) throw Error('Choose sine, triangle, sawtooth or square for a portable preview.');
        } else if (take(/^gain\s*\(/, true)) {
          gain = number();
          if (!(gain >= 0 && gain <= 1)) throw Error('Use a gain between 0 and 1.');
        } else if (take(/^rev\s*\(/, true)) {
          notes.reverse(); repeats.reverse();
        } else {
          const [, modifier] = take(/^(fast|slow|lpf|hpf)\s*\(/);
          const value = number();
          if (modifier === 'fast' || modifier === 'slow') {
            if (!(value >= 0.125 && value <= 8)) throw Error('Use a speed factor between 0.125 and 8.');
            speed *= modifier === 'fast' ? value : 1 / value;
          } else {
            if (!(value >= 20 && value <= 10000)) throw Error('Choose a filter frequency from 20 to 10000 Hz.');
            if (modifier === 'lpf') lowpass = value;
            else highpass = value;
          }
        }
        take(/^\)/);
      }
      if (!(speed >= 0.125 && speed <= 8)) throw Error('Combined speed must stay between 0.125 and 8.');
      return {notes, repeats, wave, gain, speed, lowpass, highpass};
    }
    const stacked = Boolean(take(/^stack\s*\(/, true));
    const layers = [layer()];
    if (stacked) {
      while (take(/^,/, true)) {
        if (layers.length >= 4) throw Error('Use up to four layers for a portable preview.');
        layers.push(layer());
      }
      take(/^\)/);
    }
    if (rest && rest !== ';') throw Error(unsupported);
    return {cps, layers};
  }
  function sample(wave, phase) {
    switch (wave) {
      case 'sine': return Math.sin(2 * Math.PI * phase);
      case 'triangle': return 1 - 4 * Math.abs(phase - 0.5);
      case 'sawtooth': return 2 * phase - 1;
      case 'square': return phase < 0.5 ? 1 : -1;
    }
  }
  async function render(source, seconds, signal) {
    const {layers, cps} = parse(source);
    if (!Number.isInteger(seconds) || seconds < 1 || seconds > 60) throw Error('Use a duration of 1 to 60 whole seconds.');
    const frames = seconds * rate;
    const alpha = frequency => 1 - Math.exp(-2 * Math.PI * frequency / rate);
    const voices = layers.map(layer => ({...layer, lowMix:0, highMix:0,
      lowAlpha:alpha(layer.lowpass), highAlpha:alpha(layer.highpass),
      stepsPerSecond:cps * layer.notes.length * layer.speed,
    }));
    const bytes = new Uint8Array(44 + frames * 2), view = new DataView(bytes.buffer);
    const tag = (offset, value) => bytes.set(new TextEncoder().encode(value), offset);
    tag(0, 'RIFF'); view.setUint32(4, bytes.length - 8, true); tag(8, 'WAVE'); tag(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true);
    view.setUint16(34, 16, true); tag(36, 'data'); view.setUint32(40, frames * 2, true);
    for (let start = 0; start < frames; start += 16384) {
      if (signal?.aborted) throw Error('Render cancelled.');
      const end = Math.min(start + 16384, frames);
      for (let frame = start; frame < end; frame++) {
        const t = frame / rate;
        let mix = 0;
        for (const voice of voices) {
          const step = t * voice.stepsPerSecond, index = Math.floor(step), slot = index % voice.notes.length;
          const frequency = voice.notes[slot];
          let value = 0;
          if (frequency) {
            const count = voice.repeats[slot], duration = 1 / (voice.stepsPerSecond * count);
            const elapsed = (step - index) * count % 1 * duration;
            const phase = (elapsed * frequency) % 1;
            const envelope = Math.min(1, elapsed / 0.005, (duration - elapsed) / 0.012);
            value = sample(voice.wave, phase) * voice.gain * envelope;
          }
          if (voice.lowAlpha) {
            voice.lowMix += voice.lowAlpha * (value - voice.lowMix);
            value = voice.lowMix;
          }
          if (voice.highAlpha) {
            voice.highMix += voice.highAlpha * (value - voice.highMix);
            value -= voice.highMix;
          }
          mix += value;
        }
        view.setInt16(44 + frame * 2, Math.round(mix * 0.8 * 32767 / layers.length), true);
      }
      if (end < frames) await new Promise(resolve => setTimeout(resolve, 0));
    }
    return new Blob([bytes], {type:'audio/wav'});
  }
  globalThis.MarianaStrudelPattern = {maxBytes, parse, render};
})();

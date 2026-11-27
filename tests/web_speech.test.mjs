import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';

const worklet = readFileSync(new URL('../web/player/speech-worklet.js', import.meta.url), 'utf8');
const routing = readFileSync(new URL('../web/player/speech-dsp.js', import.meta.url), 'utf8');

function session() {
  let Processor;
  vm.runInNewContext(worklet, {
    AudioWorkletProcessor: class { constructor() { this.port = {}; } }, sampleRate: 48000,
    registerProcessor: (_, ctor) => { Processor = ctor; },
  });
  return new Processor();
}

test('stereo-linked sibilance reduction, vowel preservation and bounded strength', () => {
  for (const hz of [380, 7200]) for (const limit of [0, 3, 6, 9]) {
    const processor = session();
    for (let k = 0; k < 60; k++) {
      const left = Float32Array.from({ length: 128 }, (_, i) => .3 * Math.sin(2 * Math.PI * hz * (k * 128 + i) / 48000));
      const input = [left, left.map(x => x * .5)];
      const out = [new Float32Array(128), new Float32Array(128)];
      assert.equal(processor.process([input], [out], { maxReduction: [limit] }), true);
      if (k > 45) for (let i = 0; i < 128; i++) {
        const expected = hz === 380 ? 1 : 10 ** (-limit / 20);
        assert.ok(Math.abs(left[i] * expected - out[0][i]) < 0.0001);
        assert.equal(out[1][i], out[0][i] * .5);
      }
    }
  }
});

test('an unavailable module does not capture or mute the original media element', async () => {
  let captures = 0;
  const window = { AudioWorkletNode: class {}, AudioContext: class {
    constructor() { this.audioWorklet = { addModule() { throw Error('module blocked'); } }; }
    async resume() {}
    createMediaElementSource() { captures++; }
  } };
  vm.runInNewContext(routing, { window, URL, document: { currentScript: { src: 'https://localhost/speech-dsp.js' } } });
  const audio = {};
  assert.equal(await window.MarianaSpeech.setLevel(audio, 'off'), true);
  assert.equal(await window.MarianaSpeech.setLevel(audio, 'strong'), false);
  assert.equal(captures, 0);
});

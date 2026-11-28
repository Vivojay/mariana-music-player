import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import '../web/player/strudel-pattern.js';

const {parse, render} = globalThis.MarianaStrudelPattern;
const starter = readFileSync(new URL('../res/strudel/starter.js', import.meta.url), 'utf8');

test('renders a tuned note followed by a silent half-cycle', async () => {
  const wav = new DataView(await (await render('setcps(1); note("a4 ~").s("sine");', 1)).arrayBuffer());
  assert.equal(wav.byteLength, 44 + 22050 * 2);
  assert.equal(wav.getUint32(24, true), 22050);
  assert.equal(wav.getUint32(40, true), 22050 * 2);
  let crossings = 0, previous = 0;
  for (let i = 0; i < 22050; i++) {
    const value = wav.getInt16(44 + 2 * i, true);
    if (previous <= 0 && value > 0) crossings++;
    if (i >= 11025) assert.equal(value, 0);
    previous = value;
  }
  assert.equal(crossings, 220);
});

test('four oscillator choices produce distinct overtone signals and the shared starter layers parse', async () => {
  const results = await Promise.all(['sine','square','sawtooth','triangle'].map(async waveform =>
    Buffer.from(await (await render('note("c4").s("' + waveform + '")', 1)).arrayBuffer()).toString('base64')));
  assert.equal(new Set(results).size, 4);
  assert.equal(parse(starter).layers.length, 2);
  assert.equal(parse("note('d4 eb4 f#4 ~').gain(.5)").layers[0].notes.length, 4);
});

test('validates the full grammar before rendering, cancellation and size limits', async () => {
  for (const source of [starter + ' unexpected', 's("bd")', 'note("c4*65")', 'setcps(0);note("c4")',
    'note("c4").gain(2)', 'stack(note("c4"),note("c4"),note("c4"),note("c4"),note("c4"))', 'ü'.repeat(32769)]) {
    assert.throws(() => parse(source));
  }
  await assert.rejects(render(starter, 0), /duration/);
  const controller = new AbortController();
  const rendering = render(starter, 60, controller.signal);
  controller.abort();
  await assert.rejects(rendering, /cancelled/);
});


test('extended portable syntax renders note retriggers, reverse, rate changes and audible filters', async () => {
  const code = 'setcps(1); note("a4*4 ~").s("sine").rev().fast(2).slow(2)';
  const spec = parse(code).layers[0];
  assert.equal(spec.speed, 1);
  assert.deepEqual(spec.notes, [0, 440]);
  assert.deepEqual(spec.repeats, [1, 4]);
  async function pcm(extra) {
    const view = new DataView(await (await render(code + extra, 1)).arrayBuffer());
    return Array.from({length:22050}, (_, i) => view.getInt16(44 + 2*i, true));
  }
  const dry = await pcm('');
  const low = await pcm('.lpf(100)');
  const high = await pcm('.hpf(1000)');
  assert.ok(dry.slice(0,11025).every(value => value === 0));
  assert.ok(Math.abs(dry[13500]) > 0);
  assert.ok(Math.abs(dry[13781]) < 100);
  const rms = values => Math.sqrt(values.reduce((sum, value) => sum + value**2, 0)/values.length);
  assert.ok(rms(low) < rms(dry) * 0.35);
  assert.ok(rms(high) < rms(dry) * 0.55);
});

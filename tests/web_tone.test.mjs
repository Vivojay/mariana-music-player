import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const window = {};
const source = await readFile(new URL('../web/player/tone.js', import.meta.url), 'utf8');
runInNewContext(source, { window, File, setTimeout });
const { render } = window.MarianaTone;

async function samples(command) {
  const { file } = await render(command.split(' '));
  const bytes = Buffer.from(await file.arrayBuffer());
  assert.equal(bytes.toString('ascii', 0, 4), 'RIFF');
  assert.equal(bytes.readUInt32LE(24), 48000);
  assert.equal(bytes.readUInt32LE(40) + 44, bytes.length);
  return new Int16Array(bytes.buffer, bytes.byteOffset + 44, (bytes.length - 44) / 2);
}

test('four distinct bounded oscillator previews and verifiable pitch', async () => {
  const waves = new Set();
  for (const wave of ['sine', 'triangle', 'square', 'sawtooth']) {
    const pcm = await samples(wave + ' 300 --seconds .2 --level 10');
    assert.equal(pcm.length, 9600);
    assert.equal(pcm[0], 0);
    assert.equal(pcm.at(-1), 0);
    assert.ok(Math.max(...pcm) <= 3277);
    let crossings = 0;
    for (let n = 1500; n < 6300; n++) if (pcm[n] <= 0 && pcm[n + 1] > 0) crossings++;
    assert.equal(crossings, 30);
    waves.add(pcm.slice(1503, 1533).join(','));
  }
  assert.equal(waves.size, 4);
});

test('harmonies and sweeps match the documented grammar', async () => {
  const chord = await samples('harmony 210 --chord octave --seconds .1 --wave square');
  assert.deepEqual(chord, await samples('harmony 210 420 --seconds .1 --wave square'));
  const descending = await samples('sweep 800 80 --seconds 1 --curve log');
  function frequency(middle) {
    let rising = 0;
    for (let i = middle - 2400; i < middle + 2400; i++) {
      if (descending[i] <= 0 && descending[i + 1] > 0) rising++;
    }
    return rising * 10;
  }
  assert.ok(Math.abs(frequency(12000) - 450) < 11);
  assert.ok(Math.abs(frequency(36000) - 142) < 11);
  for (const args of ['square NaN', 'sweep 100', 'harmony 900 --chord xyz', 'sine 45 --seconds 1000']) {
    await assert.rejects(render(args.split(' ')));
  }
});

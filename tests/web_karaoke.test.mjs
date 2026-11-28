import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

globalThis.window = globalThis;
await import('../web/player/karaoke.js');
const api = window.MarianaKaraoke;
const fixture = name => readFileSync(new URL('../res/karaoke/' + name, import.meta.url));
const duet = () => JSON.parse(fixture('practice-duet.json'));
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

test('bundled practice duet matches its exact audio and covers the whole recording', () => {
  const score = duet(), wav = fixture('practice-duet.wav');
  assert.equal(digest(wav), score.media_sha256);
  const duration = wav.readUInt32LE(40) / wav.readUInt32LE(28);
  const v = api.validate(score);
  assert.deepEqual(v.singers, ['Alto', 'Tenor']);
  assert.equal(api.availability(v, duration), '');
  assert.equal(api.locate(score.segments, 399), 0);
  assert.equal(api.locate(score.segments, 400), 1);
  assert.equal(score.segments[api.locate(score.segments, 3400)].voices.length, 2);
  assert.equal(api.locate(score.segments, 6000), -1);
  assert.equal(api.locate(score.segments, -1), -1);
  assert.match(api.availability(v, 5.749), /duration differs/);
  assert.equal(api.availability(v, 6.25), '');
});

test('the weakest word or global score determines eligibility, including a second voice', () => {
  for (const [global, word, accepted] of [[1,.9,true], [.9,1,true], [.89999,1,false], [1,.89999,false]]) {
    const sheet = duet();
    sheet.confidence = global;
    sheet.segments[3].voices[1].words[2].confidence = word;
    const v = api.validate(sheet);
    assert.equal(api.availability(v, 6) === '', accepted);
  }
});

test('rejects incomplete, unlabelled, malformed or conflicting singer timelines', () => {
  for (const change of [
    s => s.segments.shift(), s => s.segments.pop(), s => s.segments[1].end_ms++,
    s => s.segments[1].voices[0].words[1].start_ms = 431, s => s.segments[1].voices[0].words[0].start_ms = 400.1,
    s => s.segments[1].voices[0].words[0].text = 'hidden\u202e',
    s => s.segments[3].voices[1].singer = 'Alto', s => s.segments[3].voices[1].words = [],
    s => s.confidence = '0.95', s => s.source = '', s => s.segments.forEach(seg => seg.voices = []),
  ]) { const sheet = duet(); change(sheet); assert.throws(() => api.validate(sheet)); }
});

test('large-file worker SHA-256 matches Node across padding and chunk boundaries', async () => {
  const context = vm.createContext({self:{}});
  vm.runInContext(readFileSync(new URL('../web/player/karaoke-hash.js', import.meta.url), 'utf8'), context);
  for (const length of [0,1,55,56,63,64,65,119,120,65537,1048576,1048635]) {
    const bytes = Buffer.alloc(length);
    for (let i=0; i<length; i++) bytes[i] = i % 251;
    context.file = new Blob([bytes]);
    assert.equal(await vm.runInContext('hashBlob(file)', context), digest(bytes), length.toString());
  }
});

await import('../web/player/karaoke-ttml.js');
await import('../web/player/karaoke-mix.js');

test('two independent word clocks produce conservative cross-part confidence, explicit rests and exact-time rejection', () => {
  const score = duet(), data = {total:6000,lines:[]};
  for (const segment of score.segments) for (const lane of segment.voices)
    data.lines.push(lane.words.map(w => ({...w,singer:lane.singer})));
  const compare = second => api.validate(MarianaKaraokeTTML.reconcile(data, second, score.media_sha256));
  assert.throws(() => compare(structuredClone(data)), /identical/i);
  const other = structuredClone(data); other.lines.at(-1)[0].end_ms += 100;
  assert.equal(compare(other).confidence,.9);
  assert.equal(compare(other).sheet.segments[0].voices.length,0);
  assert.equal(compare(other).sheet.segments.find(s => s.start_ms === 3400).voices.length,2);
  other.lines.at(-1)[0].end_ms++;
  assert.match(api.availability(compare(other),6), /below/);
  other.lines.at(-1)[0].singer = 'New voice';
  assert.throws(() => compare(other), /differ/);
});

test('sample-aligned vocal adjustment preserves backing and stereo channel positions', async () => {
  const buffer = (arrays) => ({
    numberOfChannels:arrays.length, sampleRate:44100, length:arrays[0].length,
    getChannelData:c => Float32Array.from(arrays[c]),
  });
  const vocal = buffer([[.2,-.15,.25,-.1], [.1,-.2,.2,-.2]]);
  const master = buffer([[.3,-.05,.35,0], [.3,0,.4,0]]);
  const pair = {master,vocal};
  MarianaKaraokeMix.checkPair(master,vocal);
  assert.throws(() => MarianaKaraokeMix.checkPair(master,buffer([[0,0,0,0]])), /match/);
  assert.throws(() => MarianaKaraokeMix.checkPair(master,buffer([[1,1]])), /duration/);
  for (const level of [0,.5,1]) {
    const result = await MarianaKaraokeMix.render(pair,level,new AbortController().signal);
    const data = new DataView(await result.arrayBuffer());
    assert.equal(data.getUint16(22,true),2); assert.equal(data.getUint32(40,true),16);
    assert(Math.abs(data.getInt16(44,true)/32767 - (.1 + .2*level)) < .0001);
    assert(Math.abs(data.getInt16(46,true)/32767 - (.2 + .1*level)) < .0001);
  }
  const controller = new AbortController(); controller.abort();
  await assert.rejects(MarianaKaraokeMix.render(pair,.25,controller.signal),/cancel/i);
});

test('native duet fixture loads identically, and unknown duration cannot enable karaoke', () => {
  const sheet = JSON.parse(readFileSync(new URL('./fixtures/karaoke-duet.json', import.meta.url)));
  const verified = api.validate(sheet);
  assert(verified.singers.length >= 2);
  assert.match(api.availability(verified,NaN), /duration/);
  assert.equal(api.availability(verified,sheet.duration_ms/1000), '');
});

await import('../web/player/karaoke-invite.js');
test('duet invite fingerprints interoperate with the Python score fixtures and carry no lyrics', () => {
  const sheet = JSON.parse(readFileSync(new URL('./fixtures/karaoke-duet.json', import.meta.url)));
  const nativeInvite = JSON.parse(readFileSync(new URL('./fixtures/karaoke-invite.json', import.meta.url)));
  const verified = api.validate(sheet), digest = createHash('sha256').update(MarianaKaraokeInvite.timing(sheet)).digest('hex');
  assert.equal(digest,'fdfe8ed549a1830a4d5fadd4e653571ab4bd32a2a3626635166009ee75e7f255');
  assert.equal(createHash('sha256').update(MarianaKaraokeInvite.timing(duet())).digest('hex'),
    'a9c644ef1656c564b086b5ca2be3d06ddbdc579a49eda8f5b4f75736dccd2e6b');
  assert.equal(MarianaKaraokeInvite.matches(MarianaKaraokeInvite.validate(nativeInvite), verified,digest),'');
  assert.throws(() => MarianaKaraokeInvite.validate({...nativeInvite,lyrics:'unrequested'}));
  assert.throws(() => MarianaKaraokeInvite.validate({...nativeInvite,start_ms:sheet.duration_ms}));
  assert.match(MarianaKaraokeInvite.matches({...nativeInvite,part:'Third'},verified,digest),/singer/);
  assert.match(MarianaKaraokeInvite.matches(nativeInvite,verified,'x'),/timing/);
  assert.match(MarianaKaraokeInvite.matches({...nativeInvite,media_sha256:'0'.repeat(64)},verified,digest),/recording/);
});

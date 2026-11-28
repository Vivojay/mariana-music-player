import assert from 'node:assert/strict';
import {File} from 'node:buffer';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';
import '../web/player/clip-media.js';
import '../web/player/clip-story.js';
import '../web/player/clip.js';

const media = globalThis.MarianaClipMedia;
const fixture = Float32Array.from({length:16000}, (_, i) => 0.75 * Math.sin(i / 17));
const audio = {numberOfChannels:2, sampleRate:8000, length:16000,
  getChannelData:i => i === 0 ? fixture : Float32Array.from(fixture, x => -x)};
const entire = media.cutBuffer(audio, 0, 2);

test('PCM selection copies exactly the two selected channels without Web Audio', async () => {
  const source = new Uint8Array(await entire.arrayBuffer());
  const start = .173, end = .986;
  const out = new Uint8Array(await (await media.render(entire, start, end, 2)).arrayBuffer());
  const view = new DataView(out.buffer), frames = Math.round(end * 8000) - Math.round(start * 8000);
  assert.equal(view.getUint32(24, true), 8000);
  assert.equal(view.getUint16(22, true), 2);
  assert.equal(view.getUint32(40, true), frames * 4);
  assert.deepEqual(out.slice(44), source.slice(44 + Math.round(start * 8000) * 4, 44 + Math.round(end * 8000) * 4));
});

test('RIFF reader honors extra padded chunks; rejects stale or empty selections', async () => {
  const base = new Uint8Array(await entire.arrayBuffer());
  const extra = Uint8Array.of(74,85,78,75, 3,0,0,0, 65,66,67,0);
  const expanded = new Blob([base.slice(0,36), extra, base.slice(36)]);
  const out = await media.cutWave(expanded, .25, 1.25);
  assert.deepEqual(new Uint8Array(await out.arrayBuffer()).slice(44), base.slice(44+2000*4,44+10000*4));
  assert.throws(() => media.range(2, 1, 2));
  assert.throws(() => media.range(0, 3, 2));
  assert.throws(() => media.range(0, 1, Infinity));
  assert.throws(() => media.seconds('1:77:01'));
  assert.equal(media.seconds('01:02:04.125'),3724.125);
  await assert.rejects(media.cutWave(entire, 0, 3), /shorter/);
  const cancel = new AbortController(); cancel.abort();
  await assert.rejects(media.render(entire, .1, .2, 2, cancel.signal), {name:'AbortError'});
});

async function shareModule(context) {
  vm.runInNewContext(await readFile(new URL('../web/player/clip-share.js', import.meta.url), 'utf8'), context);
  return context.MarianaClipShare;
}
test('system share receives the selected file; unavailable share and user cancellations preserve export', async () => {
  const file = new File([entire], 'test.wav', {type:'audio/wav'});
  let shared;
  const navigator = {canShare:({files}) => files[0] === file, share:async data => {shared=data.files[0];}};
  const app = await shareModule({navigator});
  await app.share(file);
  assert.strictEqual(file, shared);
  navigator.share = async () => { throw new DOMException('Closed','AbortError'); };
  await assert.rejects(app.share(file), {name:'AbortError'});
  navigator.canShare = () => false;
  await assert.rejects(app.share(file), /Download/);
});

test('iOS host transfer sends acknowledged, size-bounded chunks of the exact prepared file', async () => {
  const log = [];
  const bridge = {postMessage:async msg => log.push(msg)};
  const app = await shareModule({MarianaNativeShell:'ios', webkit:{messageHandlers:{marianaClip:bridge}}, navigator:{}, btoa});
  const file = new File([entire], 'Mariana.wav', {type:'audio/wav'});
  assert.equal(app.available(file), true);
  await app.share(file, 'instagram-story', 12.5, true);
  assert.equal(log[0].target, 'instagram-story'); assert.equal(log[0].portrait, true);
  assert.equal(log[0].size, file.size);
  assert.equal(log[0].mime, 'audio/wav');
  assert.equal(log.at(-1).op, 'finish');
  const chunks = log.slice(1,-1).map(msg => Buffer.from(msg.data,'base64'));
  assert(chunks.length > 1 && chunks.every(b => b.length <= 49152));
  assert.deepEqual(Buffer.concat(chunks), Buffer.from(await file.arrayBuffer()));
});

test('editor uses paused playback position, prepares the marked clip and invalidates stale media', async () => {
  const nodes = new Map(), log = [];
  const el = id => {
    if (!nodes.has(id)) nodes.set(id, {value:'', hidden:id === 'clip-panel', dataset:{},
      style:{setProperty(){}}, classList:{toggle(){}}, addEventListener(name, fn) {this['on'+name] = fn;},
      setAttribute(){}, removeAttribute(){}, focus(){}, load(){}, pause(){}, scrollIntoView(){}});
    return nodes.get(id);
  };
  const ctx = {window:{addEventListener(){}}, navigator:{}, File, URL, AbortController, setTimeout, clearTimeout,
    MarianaClipMedia:media, MarianaClipStory:{codec:() => ''}, MarianaClipShare:{
      host:() => '', available:() => true, share:async file => log.push(file)}};
  vm.runInNewContext(await readFile(new URL('../web/player/clip.js', import.meta.url),'utf8'), ctx);
  let item = {title:'Band practice.wav', id:'one'};
  let position = .3, activeBlob = Promise.resolve(entire);
  const api = ctx.MarianaClips.mount(el, () => ({item, duration:2, position}), () => activeBlob, () => {});
  api.sync();
  await api.command(['start']); position = .7; await api.command(['end']);
  await api.command([]); // Opening the editor keeps marks set through the console.
  assert.equal(el('clip-start').value,'0.3'); assert.equal(el('clip-end').value,'0.7');
  await api.command(['export']); const url = el('clip-download').href;
  assert.ok(url.startsWith('blob:')); await api.command(['share']);
  const data = new DataView(await log[0].arrayBuffer());
  assert.equal(data.getUint32(40,true), 3200*4);
  assert.match(log[0].name, /Band practice-0.3-0.7.wav/);
  assert.equal(position,.7);
  let resume;
  activeBlob = new Promise(resolve => {resume=resolve;});
  const pending = api.command(['export']);
  item = {title:'Other.wav', id:'two'}; api.sync(); resume(entire); await pending;
  assert.equal(el('clip-result').hidden,true);
  assert.equal(log.length,1);
});

test('Android channel streams payloads in order and acknowledges each chunk', async () => {
  let receive, port, posted = [];
  const context = {location:{origin:'https://app.mariana.invalid'}, window:{addEventListener:(_event, fn) => {receive=fn;}, dispatchEvent(){}},
    navigator:{}, Event, setTimeout, clearTimeout, btoa};
  const app = await shareModule(context);
  const target = [{id:'instagram',name:'Instagram',reason:''}];
  port = {postMessage:body => { const fields = JSON.parse(body);
    if (fields.op === 'targets') queueMicrotask(() => port.onmessage({data:JSON.stringify(target)}));
    else { posted.push(fields); queueMicrotask(() => port.onmessage({data:'ok'})); }
  }};
  receive({source:null, data:'MarianaClipPort', ports:[port]});
  const file = new File([entire], 'Stereo.wav', {type:'audio/wav'});
  assert.equal((await app.targets(file, 4, false))[0].id, 'instagram');
  await app.share(file, 'snapchat', 4, false);
  assert.equal(posted[0].target, 'snapchat');
  assert.equal(app.host(),'android');
  assert.equal(posted[0].op,'start'); assert.equal(posted.at(-1).op,'finish');
  assert.deepEqual(Buffer.concat(posted.slice(1,-1).map(p => Buffer.from(p.data, 'base64'))), Buffer.from(await entire.arrayBuffer()));
});

test('official timestamp link shares only the public video ID and selected second', () => {
  assert.equal(media.youtubeLink('https://music.youtube.com/watch?v=abcdefghijk&si=private-key&list=secret', 57.8),
    'https://www.youtube.com/watch?v=abcdefghijk&t=57s');
  assert.equal(media.youtubeLink('https://youtu.be/abcdefghijk?t=122',0),'https://www.youtube.com/watch?v=abcdefghijk');
  for (const url of ['https://youtube.com.evil/watch?v=abcdefghijk','https://private:pass@youtube.com/watch?v=abcdefghijk',
    'https://youtu.be/abc', 'https://media.example/private.mp3?token=secret']) assert.equal(media.youtubeLink(url,0),'');
});

test('source-video export keeps the original aspect ratio, frames and audio track', async () => {
  const frames = [], tracks = [{kind:'video',stop() {this.stopped=true;}}];
  const audioTrack = {kind:'audio',stop() {this.stopped=true;}};
  const stream = {getTracks:() => tracks, addTrack:t => tracks.push(t)};
  let seen = -1, canvas;
  class Video extends EventTarget {
    videoWidth = 1920; videoHeight = 1080; duration = 3;
    load() { if (this.src) queueMicrotask(() => this.dispatchEvent(new Event('loadeddata'))); }
    set currentTime(t) { seen = t; queueMicrotask(() => this.dispatchEvent(new Event('seeked'))); }
    get currentTime() {return seen;}
    play() { this.currentTime = 1.95; queueMicrotask(() => this.onended?.()); return Promise.resolve(); }
    pause() {} removeAttribute() {this.src='';}
  }
  class Canvas {
    getContext() {return {drawImage:(_video,x,y,w,h) => frames.push([x,y,w,h])};}
    captureStream() { return stream;}
  }
  class Recorder {
    static isTypeSupported(type) {return type === 'video/mp4';}
    constructor(stream, options) {this.mimeType=options.mimeType;}
    start() {this.state='recording';}
    stop() {this.state='inactive'; this.ondataavailable({data:new Blob([Uint8Array.of(1,2)])}); this.onstop();}
  }
  const ctx = {document:{createElement:tag => tag === 'video' ? new Video() : (canvas=new Canvas())},
    URL, Blob, DOMException, performance, setInterval, clearInterval, HTMLCanvasElement:Canvas, AudioContext:function(){},
    MediaRecorder:Recorder, MarianaClipMedia:media};
  vm.runInNewContext(await readFile(new URL('../web/player/clip-story.js', import.meta.url),'utf8'), ctx);
  const node = {connect(){},disconnect(){},stream:{getAudioTracks:() => [audioTrack]}};
  const data = await ctx.MarianaClipStory.original(new Blob(['test']), .25, 1.95, {
    createMediaElementSource:() => node,createMediaStreamDestination:() => node}, new AbortController().signal);
  assert.equal(data.type,'video/mp4'); assert.deepEqual(frames[0],[0,0,1280,720]);
  assert.equal(canvas.height,720); assert.equal(tracks.length,2); assert(tracks.every(t => t.stopped));
});

import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import '../web/player/dj-engine.js';
const {Mixer,weights,wavHeader,waveformPeaks,sampleWaveform,stereoMeter} = globalThis.MarianaDJEngine;

class Param {
  constructor(value=0) { this.value = value; }
  setTargetAtTime(value) { this.value = value; }
}
class AudioNode {
  constructor() { this.edges = new Set(); }
  connect(target) { this.edges.add(target); return target; }
  disconnect(target) { if (target) this.edges.delete(target); else this.edges.clear(); }
}
function context() {
  const ctx = {
    currentTime:0, sampleRate:48000, destination:new AudioNode(),
    createGain:() => Object.assign(new AudioNode(), {gain:new Param(1)}),
    createBiquadFilter:() => Object.assign(new AudioNode(), {gain:new Param(),frequency:new Param(),Q:new Param()}),
    createDynamicsCompressor:() => Object.assign(new AudioNode(), Object.fromEntries(['attack','release','ratio','knee','threshold'].map(p => [p,new Param()]))),
    createBufferSource:() => Object.assign(new AudioNode(),{playbackRate:new Param(1),start(when,pos){ this.position = pos; },stop(){}}),
    createScriptProcessor:() => (ctx.capture = new AudioNode()),
    decodeAudioData:async () => ({duration:30, length:30*48000, numberOfChannels:2}),
  };
  return ctx;
}
const file = async () => new File([new Uint8Array(12)],'song.wav');

test('two decks sum through independent EQ/gain, equal-power faders and a common master', () => {
  const ctx=context(), m=new Mixer(ctx);
  for (const deck of Object.values(m.decks)) {
    assert(deck.eq.low.edges.has(deck.eq.mid)); assert(deck.eq.mid.edges.has(deck.eq.high));
    assert(deck.eq.high.edges.has(deck.trim)); assert(deck.trim.edges.has(deck.fader)); assert(deck.fader.edges.has(m.bus));
  }
  assert(m.bus.edges.has(m.master)); assert(m.master.edges.has(ctx.destination));
  for (let i=0;i<=100;i++) { const [a,b] = weights(i); assert.ok(Math.abs(a*a+b*b-1)<1e-12); }
  m.crossfade(0); assert.equal(m.decks.A.fader.gain.value,1); assert.equal(m.decks.B.fader.gain.value,0);
  m.crossfade(100); assert.equal(m.decks.A.fader.gain.value,0); assert.equal(m.decks.B.fader.gain.value,1);
  assert.throws(() => m.crossfade(110));
  m.decks.A.setGain(80); m.decks.A.setEQ('mid',-8); assert.equal(m.decks.A.trim.gain.value,.8);
  assert.equal(m.decks.A.eq.mid.gain.value,-8); assert.equal(m.decks.B.eq.mid.gain.value,0);
});

test('rate changes preserve position; cues and loops follow the audio clock and reject invalid ranges', async () => {
  const ctx=context(), m=new Mixer(ctx), deck=m.decks.A;
  await deck.load(file); deck.play(); ctx.currentTime=5; deck.cue('set',3); deck.setRate(2);
  ctx.currentTime=8; assert.equal(deck.position(),11); deck.pause(); ctx.currentTime=9;
  assert.equal(deck.position(),11); deck.cue('go',3); assert.equal(deck.position(),5);
  deck.setLoop(8,12); deck.play(); assert.equal(deck.source.loopStart,8); assert.equal(deck.source.loopEnd,12);
  ctx.currentTime=12; assert.equal(deck.position(),10);
  assert.throws(() => deck.setLoop(12,8)); assert.deepEqual(deck.loop,{start:8,end:12});
  deck.seek(25); assert.equal(deck.loop,null); assert.equal(deck.position(),25);
  ctx.currentTime=14.5; deck.source.onended(); assert.equal(deck.position(),30); deck.play(); assert.equal(deck.position(),0);
  assert.throws(() => deck.cue('go',4)); assert.throws(() => deck.cue('set',1.25)); assert.throws(() => deck.seek(31));
  deck.cue('clear',3); assert.equal(deck.cues.has(3),false);
});

test('parallel scopes retain opposite-channel PCM peaks and silence outside a track', async () => {
  const left = new Float32Array(384), right = new Float32Array(384);
  left[4] = 0.5; right[16] = -0.75; left[135] = -0.25; right[263] = 1;
  const channels = [left,right];
  const peaks = await waveformPeaks({length:left.length, sampleRate:128, numberOfChannels:2, getChannelData:i => channels[i]});
  assert.deepEqual(Array.from(peaks.points), [-0.75,0.5,-0.25,0,0,1]);
  const view = sampleWaveform(peaks,-1,4,new Float32Array(10));
  assert.deepEqual(Array.from(view),[0,0,-0.75,0.5,-0.25,0,0,1,0,0]);
  const overview = sampleWaveform(peaks,0,3,new Float32Array(2));
  assert.deepEqual(Array.from(overview),[-0.75,1]);
});

test('scope generation can abandon an analysis after another recording takes its deck', async () => {
  const pcm = new Float32Array(128 * 1025);
  const peaks = await waveformPeaks({length:pcm.length, sampleRate:48000, numberOfChannels:1, getChannelData:() => pcm}, () => false);
  assert.equal(peaks,null);
});

test('stereo meter reads signed peaks independently from a parallel post-mix tap', () => {
  const node = new AudioNode(), splitter = new AudioNode();
  const amplitudes = [-0.5,0];
  const context = {
    createChannelSplitter:channels => { assert.equal(channels,2); return splitter; },
    createAnalyser:() => Object.assign(new AudioNode(),{getFloatTimeDomainData:array => array.fill(amplitudes.shift())}),
  };
  const [left,right] = stereoMeter(context,node)();
  assert(node.edges.has(splitter)); assert.equal(splitter.edges.size,2);
  assert(Math.abs(left - 20 * Math.log10(0.5)) < 1e-9);
  assert.equal(right,-60);
});

test('stale or failed loads preserve the latest playable deck and its cues', async () => {
  const ctx=context(), deck=new Mixer(ctx).decks.A; let give;
  const first=deck.load(() => new Promise(resolve => { give=resolve; }));
  await deck.load(async () => new File(['new'],'new.mp3')); give(await file()); assert.equal(await first,false);
  assert.equal(deck.title,'new.mp3'); deck.seek(3); deck.cue('set',1);
  ctx.decodeAudioData=async () => { throw Error(); };
  await assert.rejects(deck.load(file),/decode/); assert.equal(deck.cues.get(1),3);
  assert.equal(deck.title,'new.mp3'); assert.equal(deck.position(),3);
});

test('master recording captures bounded interleaved stereo PCM from the post-fader bus and retains speaker output', async () => {
  const ctx=context(), m=new Mixer(ctx);
  let resolve; const finished = new Promise(done => {resolve=done;});
  await m.record((file,seconds,reason)=>resolve({file,seconds,reason}),44+3*4);
  assert(m.master.edges.has(ctx.capture)); assert(m.master.edges.has(ctx.destination));
  const channels = [Float32Array.from([-1,.5,2,0]),Float32Array.from([1,-.5,-2,0])];
  ctx.capture.onaudioprocess({inputBuffer:{getChannelData:i=>channels[i]}});
  const {file:wave,seconds,reason} = await finished;
  assert.match(reason,/limit/); assert.equal(seconds,3/48000); assert.equal(wave.type,'audio/wav');
  assert(m.master.edges.has(ctx.destination)); assert(!m.master.edges.has(ctx.capture));
  const bytes = new DataView(await wave.arrayBuffer()); assert.equal(wave.size,56); assert.equal(bytes.getUint32(40,true),12);
  assert.equal(bytes.getUint16(22,true),2); assert.equal(bytes.getUint32(24,true),48000);
  assert.deepEqual(Array.from({length:6},(_,i)=>bytes.getInt16(44+i*2,true)),[-32768,32767,16384,-16384,32767,-32768]);
  assert.equal(m.recording,null);
});

test('audio-thread recorder flushes partial blocks, captures silence, and pads mono to stereo', async () => {
  let Type; const messages=[];
  vm.runInNewContext(await readFile(new URL('../web/player/dj-recorder.js',import.meta.url),'utf8'),{
    AudioWorkletProcessor:class { constructor() { this.port={postMessage:x=>messages.push(x)}; } },
    registerProcessor:(name,cls)=>{ assert.equal(name,'mariana-mix-recorder'); Type=cls; }
  });
  const p=new Type(), output=[[new Float32Array(128)]];
  for (let i=0;i<33;i++) p.process(i===0 ? [[]] : [[new Float32Array(128).fill(.25)]],output);
  p.port.onmessage({data:'stop'}); assert.equal(messages.at(-1),'stopped');
  assert.equal(messages[0].byteLength,4096*4); assert.equal(messages[1].byteLength,128*4);
  const v = new DataView(messages[0]); assert.equal(v.getInt16(0,true),0); assert.equal(v.getInt16(128*4,true),8192); assert.equal(v.getInt16(128*4+2,true),8192);
  assert.equal(p.process([],[]),false); assert.equal(new DataView(wavHeader(512,44100)).getUint32(28,true),176400);
});

test('private cue bypasses the crossfader and never joins the master recording branch', () => {
  const ctx=context(), m=new Mixer(ctx), headphones=ctx.createGain();
  m.crossfade(0);
  m.monitor('B',true,headphones);
  assert(m.decks.B.trim.edges.has(headphones)); assert(m.decks.B.trim.edges.has(m.decks.B.fader));
  assert.equal(m.decks.B.fader.gain.value,0);
  assert(!headphones.edges.has(m.master)); assert(!headphones.edges.has(m.bus));
  m.monitor('B',false); assert(!m.decks.B.trim.edges.has(headphones)); assert(m.decks.B.trim.edges.has(m.decks.B.fader));
});

test('stopping during worklet installation flushes the already-requested recording once', async () => {
  const ctx = context(), m = new Mixer(ctx);
  let install, completed=0, node;
  ctx.audioWorklet = {addModule:()=>new Promise(done=>{install=done;})};
  const old = globalThis.AudioWorkletNode;
  globalThis.AudioWorkletNode = class extends AudioNode {
    constructor() {
      super(); node=this;
      this.port = {close(){},postMessage:msg => { if (msg==='stop') queueMicrotask(()=>this.port.onmessage({data:'stopped'})); }};
    }
  };
  try {
    const ready=m.record((file,seconds)=>{completed++; assert.equal(file,null); assert.equal(seconds,0);});
    m.stopRecording(); await assert.rejects(m.record(()=>{}), /already/);
    install(); await ready; await Promise.resolve();
    assert.equal(completed,1); assert.equal(m.recording,null); assert(!m.master.edges.has(node)); assert(m.master.edges.has(ctx.destination));
  } finally { globalThis.AudioWorkletNode=old; }
});

test('direct-to-disk recording finalizes one valid WAV after ordered writes and aborts a failed destination', async () => {
  const {DiskCapture} = globalThis.MarianaDJEngine;
  for (const fail of [false,true]) {
    const ctx = context(), mixer = new Mixer(ctx);
    const chunks = [], ops = [];
    const output = {
      async write(data) {
        if (fail && chunks.length) throw Error('Drive full');
        ops.push('write'); chunks.push(data);
      },
      async seek(pos) { assert.equal(pos,0); ops.push('seek'); },
      async close() { ops.push('close'); },
      async abort() { ops.push('abort'); },
    };
    const handle = {createWritable:async()=>output,getFile:async()=>new File([chunks.at(-1),...chunks.slice(1,-1)],'live.wav',{type:'audio/wav'})};
    const disk = await DiskCapture.open(handle,ctx.sampleRate);
    let finish; const done = new Promise(resolve=>{finish=resolve;});
    await mixer.record((file,seconds,reason)=>finish({file,seconds,reason}),1024,disk);
    for (const amp of [.1,.3]) {
      const arr = Float32Array.of(amp,amp);
      ctx.capture.onaudioprocess({inputBuffer:{getChannelData:()=>arr}});
    }
    assert.equal(mixer.recording.chunks.length,0);
    mixer.stopRecording(); const {file,seconds,reason} = await done;
    if (fail) { assert.equal(file,null); assert.match(reason,/Drive full/); assert(ops.includes('abort')); assert(!ops.includes('close')); }
    else {
      assert.deepEqual(ops,['write','write','write','seek','write','close']);
      assert.equal(seconds,4/ctx.sampleRate); assert.equal(file.name,'live.wav'); assert.equal(file.size,60);
      assert.equal(new DataView(await file.arrayBuffer()).getUint32(40,true),16);
    }
  }
});

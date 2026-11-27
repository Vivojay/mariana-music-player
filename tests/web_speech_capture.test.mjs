import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const script = readFileSync(new URL('../web/player/speech-capture.js',import.meta.url),'utf8');
function setup({recognition = true, configure = () => {}} = {}) {
  const nodes = {}, files = [], tracks = [], timers = new Map();
  const el = id => nodes[id] ||= {value:'', textContent:'', focus(){}, removeAttribute(){}};
  el('mic-format').value = 'audio';
  let clock = 0, micRequests = 0, engine;
  const stream = {getTracks:() => tracks};
  class Recorder {
    static isTypeSupported = type => type.startsWith('audio/webm');
    mimeType = 'audio/webm;codecs=opus';
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      queueMicrotask(() => {
        this.ondataavailable({data:new Blob(['encoded-test-samples'])});
        this.onstop();
      });
    }
  }
  class Speech {
    constructor() { engine = this; }
    start() {}
    stop() { queueMicrotask(() => this.onend()); }
  }
  const env = {Blob,File, URL, MediaRecorder:Recorder, SpeechRecognition:recognition ? Speech : undefined,
    performance:{now:() => clock}, addEventListener(){},
    navigator:{language:'en-GB',mediaDevices:{getUserMedia:async () => {
      micRequests++;
      tracks.push({stopped:false,stop(){this.stopped = true;},addEventListener(){}});
      return stream;
    }}},
    MarianaClipShare:{available:() => true, share:async file => files.push(file)},
    clearTimeout:id => timers.delete(id),setTimeout:cb => {timers.set(1,cb);return 1;}};
  configure(env);
  runInNewContext(script,env);
  const studio = env.MarianaMic.mount(el,env);
  return {studio,env,el,files,tracks,started:() => micRequests, engine:() => engine, clock:time => {clock=time;}};
}

test('requires explicit permission for recognition, records by itself when captions unavailable',async () => {
  const {studio,el,started,engine,tracks,files} = setup({recognition:false});
  assert.equal(started(),0);
  assert.equal(el('mic-start').disabled,true);
  assert.match(await studio.command(['start']),/enable the checkbox/);
  assert.equal(started(),0);
  await studio.command(['record']);
  assert.equal(started(),1);
  assert.equal(engine(),undefined);
  await studio.command(['stop']);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(tracks.every(track=>track.stopped),true);
  await studio.command(['share','audio']);
  assert.equal(files[0].type,'audio/webm');
  assert.match(files[0].name,/\.webm$/);
  assert.equal(await files[0].text(),'encoded-test-samples');
  assert.match(await studio.command(['export','vtt']),/No completed/);
});

test('captures interim and final words once, labels cues and shares UTF-8 WebVTT',async () => {
  const {studio,el,started,engine,files,clock} = setup();
  assert.match(await studio.command(['start']),/enable the checkbox/);
  assert.equal(started(),0);
  el('mic-consent').checked = true;
  await studio.command(['start']);
  assert.equal(el('mic-consent').checked,false);
  await studio.command(['speaker','Jay','&','A']);
  clock(100);
  const speech = engine();
  speech.onspeechstart();
  const result = {isFinal:false,0:{transcript:'Hello there'}};
  speech.onresult({results:[result],resultIndex:0});
  assert.equal(el('mic-partial').textContent,'Hello there');
  clock(2300);
  result.isFinal = true;
  speech.onresult({results:[result],resultIndex:0});
  speech.onresult({results:[result],resultIndex:0});
  await studio.command(['stop']);
  await new Promise(resolve=>setImmediate(resolve));
  await studio.command(['share','vtt']);
  assert.equal(await files[0].text(),'WEBVTT\n\n00:00:00.100 --> 00:00:02.300\n<v Jay &amp; A>Hello there</v>\n');
  await studio.command(['share','txt']);
  assert.equal(await files[1].text(),'Jay & A: Hello there\n');
  assert.equal(files[1].type,'text/plain');
  assert.equal(await studio.command(['text']),'Jay & A: Hello there');
});

test('releases delayed permission result after cancel and reports denial',async () => {
  const {studio,env,el} = setup();
  let accept, closed = false;
  env.navigator.mediaDevices.getUserMedia = () => new Promise(resolve=>{accept=resolve;});
  const request = studio.command(['record']);
  await studio.command(['stop']);
  accept({getTracks:() => [{stop(){closed=true;}}]});
  assert.match(await request,/cancelled/);
  assert.equal(closed,true);
  env.navigator.mediaDevices.getUserMedia = async () => {throw Error('denied');};
  assert.match(await studio.command(['record']),/denied/);
  assert.equal(el('mic-stop').disabled,true);
});

function jamFixture({audio = true, surface = 'browser', denyMic = false} = {}) {
  const track = kind => ({kind,stopped:false,enabled:true, listeners:{},
    stop(){this.stopped = true;}, addEventListener(event,fn){this.listeners[event] = fn;},
    getSettings:() => ({displaySurface:surface}), end(){this.listeners.ended();}});
  const stream = (tracks, amplitude=0) => ({amplitude,getTracks:() => tracks,
    getVideoTracks:() => tracks.filter(t=>t.kind === 'video'), getAudioTracks:() => tracks.filter(t=>t.kind === 'audio')});
  const video = track('video'), sharedAudio = track('audio'), mic = track('audio');
  const shared = stream(audio ? [video,sharedAudio] : [video], .8), local = stream([mic], .2);
  const mixed = stream([track('audio')]);
  const nodes = [], used = {display:0, mic:0, closed:0, encoded:null};
  function node(role, source=null) {
    const obj = {role,source,to:[],connect(target){this.to.push(target);},disconnect(){this.disconnected=true;}};
    nodes.push(obj);
    return obj;
  }
  function configure(env) {
    const Recorder = env.MediaRecorder;
    env.MediaRecorder = class extends Recorder {constructor(input){super();used.encoded=input;}};
    env.AudioContext = class {
      destination = node('monitor');
      createMediaStreamDestination(){return Object.assign(node('bus'),{stream:mixed});}
      createGain(){return Object.assign(node('gain'),{gain:{value:1}});}
      createMediaStreamSource(source){return node('source',source);}
      async close(){used.closed++;}
      async resume(){}
    };
    env.navigator.mediaDevices.getDisplayMedia = async () => {used.display++;return shared;};
    env.navigator.mediaDevices.getUserMedia = async () => {
      used.mic++;
      if (denyMic) throw Error('permission denied');
      return local;
    };
  }
  return {...setup({configure}),used,nodes,video,sharedAudio,mic,mixed};
}

test('authorized tab+mic jam mixes only audio, has no monitor and releases both inputs when sharing ends',async () => {
  const {el,studio,used,nodes,video,sharedAudio,mic,mixed,files} = jamFixture();
  assert.match(await studio.command(['jam']),/Confirm participant permission/);
  assert.equal(used.display,0);
  el('mic-participants').checked=true;
  assert.match(await studio.command(['jam']),/stereo mix/);
  assert.equal(el('mic-participants').checked,false);
  assert.equal(video.enabled,false);
  assert.equal(used.encoded,mixed);
  assert.equal(used.encoded.getVideoTracks().length,0);
  const bus = nodes.find(n=>n.role==='bus'), sources = nodes.filter(n=>n.role==='source');
  assert.equal(sources.length,2);
  let sample=0;
  for (const source of sources) {
    const [gain] = source.to;
    assert.equal(gain.role,'gain');
    assert.deepEqual(gain.to,[bus]);
    sample += gain.gain.value * source.source.amplitude;
  }
  assert.equal(sample,.5);
  assert.ok(nodes.every(n=>!n.to.some(target=>target.role==='monitor')));
  video.end();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(used.closed,1);
  assert.ok([video,sharedAudio,mic,...mixed.getTracks()].every(t=>t.stopped));
  await studio.command(['share','audio']);
  assert.match(files[0].name,/^Mariana-jam-/);
});

test('wrong surface, missing tab audio or denied second input cleans up the share and produces no file',async () => {
  for (const [options, reason] of [[{surface:'monitor'},/Select a browser tab/],
    [{audio:false},/supplied no audio/],[{denyMic:true},/permission denied/]]) {
    const {studio,el,used,video} = jamFixture(options);
    el('mic-participants').checked=true;
    assert.match(await studio.command(['jam']),reason);
    assert.equal(used.mic,options.denyMic ? 1 : 0);
    assert.equal(used.closed,1);
    assert.equal(video.stopped,true);
    assert.equal(used.encoded,null);
    assert.match(await studio.command(['share','audio']),/No completed/);
  }
});

test('cancelling while microphone permission is pending releases tab immediately and discards a late grant',async () => {
  const {studio,env,el,used,video} = jamFixture();
  let resolveMic, stopped=false;
  env.navigator.mediaDevices.getUserMedia=() => new Promise(resolve=>{resolveMic=resolve;});
  el('mic-participants').checked=true;
  const pending=studio.command(['jam']);
  await new Promise(resolve=>setImmediate(resolve));
  await studio.command(['stop']);
  assert.ok(video.stopped);
  resolveMic({getTracks:() => [{stop(){stopped=true;}}]});
  assert.match(await pending,/cancelled/);
  assert.ok(stopped);
  assert.equal(used.encoded,null);
  assert.equal(used.closed,1);
});

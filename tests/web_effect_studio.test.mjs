import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const src = name => readFileSync(new URL('../web/player/'+name, import.meta.url),'utf8');
function render(config, data, blockSize = 128) {
  let Processor;
  vm.runInNewContext(src('effect-worklet.js'),{AudioWorkletProcessor:class {constructor(){this.port={};}},
    registerProcessor:(_,p)=>{Processor=p;},sampleRate:48000});
  const p=new Processor();p.port.onmessage({data:config});
  const result=new Float32Array(data.length);
  for(let i=0;i<data.length;i+=blockSize) {
    const block=data.subarray(i,i+blockSize), out=[new Float32Array(block.length),new Float32Array(block.length)];
    p.process([[block,block]],[out]);result.set(out[0],i);
  }
  return {result,p};
}
const tone = hz => Float32Array.from({length:48000},(_,i)=>.25*Math.sin(i*2*Math.PI*hz/48000));

test('real worklet impulse taps, tape stop and bounded stereo output',()=>{
  const signal=new Float32Array(40000);signal[0]=1;
  const {result}=render({delay:100},signal);
  assert.equal(result[0],1);assert.equal(result[10800],.5);
  assert.ok(Math.abs(result[21600]-.28)<.0001);
  assert.equal(render({tapestop:25},tone(221)).result.at(-1),0);
  const vocoder=render({vocoder:95},tone(221)).result;
  assert.ok(vocoder.every(Number.isFinite) && vocoder.some(x=>Math.abs(x)>.03));
});
test('bitcrush holds quantized samples across worklet block boundaries',()=>{
  const data=tone(331).subarray(0,200);
  const {result}=render({bitcrush:100},data,17);
  assert.deepEqual(result,render({bitcrush:100},data).result);
  assert.ok(result.every(x=>x*8===Math.floor(x*8)));
  assert.ok(result.subarray(16,32).every(x=>x===result[16]));
});
test('voice pitch correction and octave shift affect audio',()=>{
  const {result}=render({pitch:12},tone(220));
  let crossings=0;
  for(let i=24000;i<48000;i++) if(result[i-1]<0 && result[i]>=0) crossings++;
  assert.ok(Math.abs(crossings*2-440)<8);
  const {p}=render({tune:100},tone(451));
  assert.ok(Math.abs(p.correction-12*Math.log2(440/451))<.045);
});
test('rack commands reach local player, restore a profile-scoped save and report unavailable mic',async()=>{
  let calls=[],stored={};
  const window={addEventListener(){},MarianaSpeech:{async setRack(audio,config){calls.push(config);return true;}},
    MarianaProfiles:{key:s=>'named:'+s}};
  vm.runInNewContext(src('effect-studio.js'),{window,URL,navigator:{},document:{currentScript:{src:'https://localhost/effect-studio.js'}},
    localStorage:{getItem:k=>stored[k],setItem:(k,v)=>stored[k]=v}});
  const studio=window.MarianaEffects.mount(()=>null,{addEventListener(){}},()=>null);
  await studio.command(['preset','choir']);await studio.command(['save','room1']);
  await studio.command(['off']);await studio.command(['load','room1']);
  assert.equal(calls.at(-1).chorus,62);
  assert.ok(Object.hasOwn(stored,'named:mariana.fx.room1'));
  await assert.rejects(studio.command(['set','room','NaN']));
  await assert.rejects(studio.command(['mic','on']),/localhost or HTTPS/);
});

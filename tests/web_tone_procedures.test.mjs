import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {File} from 'node:buffer';

const source=new URL('../web/player/tone-procedures.js',import.meta.url);
const bank=JSON.parse(readFileSync(new URL('../mariana/tone_bank.json',import.meta.url)));
const ctx=vm.createContext({MarianaToneBank:bank,File,setTimeout,performance});
vm.runInContext(readFileSync(source,'utf8'),ctx);
const {plan,render}=ctx.MarianaToneProcedures;
const command=line=>plan(line.split(' '));
async function pcm(p) {
  const {file}=await render(p);const buffer=await file.arrayBuffer();const info=new DataView(buffer);
  assert.equal(info.getUint16(22,true),2); assert.equal(info.getUint32(24,true),32000);
  assert.equal(info.getUint32(40,true),p.frames*4);
  return new Int16Array(buffer,44);
}
test('full Twinkle melody, triads, bass and stereo chorus render for the audio transport',async()=>{
  const p=await command('procedure play twinkle');assert.equal(p.frames,921600); assert.equal(p.parts.length,3);
  assert.equal(p.parts[0].notes.length,42);assert.equal(p.parts[1].notes[0].pitches.length,3);
  const wet=await pcm(p);
  assert(wet.some((v,i)=>i%2===0 && Math.abs(wet[i+1]-v)>100));
  const off=await command('procedure play twinkle --bpm 200 --chorus 0');
  const dry=await pcm(off);
  assert.equal(off.frames,p.frames/2);
  assert(dry.every((v,i)=>i%2===1 || v===dry[i+1]));
});
test('custom polyphony, rests and storage round trip',async()=>{
  const scores=new Map();
  const store=async(op,key,value)=>{
    if(op==='list') return [...scores.keys()];
    if(op==='get') return scores.get(key);
    if(scores.has(key)) throw Error('already exists');
    scores.set(key,structuredClone(value));
  };
  const args='procedure save my-theme 90 @glass C4+E4+G4:2 R @reed A3:3 --chorus 25'.split(' ');
  assert.match(await plan(args,store),/Saved my-theme/);
  assert.match(await plan(['procedure','list'],store),/my-theme/);
  const p=await plan(['procedure','play','my-theme'],store);
  assert.equal(p.frames,64000);assert.equal(p.chorus,25);assert.equal(p.parts[0].notes[1].pitches.length,0);
  await assert.rejects(plan(args,store),/already exists/);
  await assert.rejects(command('procedure save twinkle 100 C4'));
  await assert.rejects(command('synth glass C4:901'));
  await assert.rejects(command('procedure play twinkle --bpm 30'));
});
test('synth, foley and cancellation',async()=>{
  assert.match(await command('voices'),/felt-keys/);
  assert.match(await command('sfx list'),/footstep/);
  for(const line of ['sfx footstep','sfx riser','synth flute C5+G5:2']) {
    const samples=await pcm(await command(line)); assert(samples.some(v=>Math.abs(v)>100));
  }
  const p=await command('procedure play twinkle');
  await assert.rejects(render(p,()=>false),/newer selection/);
});

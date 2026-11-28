import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import '../web/player/command-match.js';
const {parse,scan,suggest}=globalThis.MarianaCommandMatch;
const data=['core','studio'].flatMap(part=>JSON.parse(readFileSync(new URL('../mariana/command_grammar_'+part+'.json',import.meta.url))).commands)
  .filter(row=>['portable','both'].includes(row.surface));
const choices=(line,cursor=line.length,opts={})=>suggest(line,cursor,data,opts);
const labels=(line)=>choices(line).map(row=>row.label);
test('portable grammar reaches nested routes, aliases, flags and values',()=>{
 assert.deepEqual(labels('dj cue A '),['clear','go','set']); assert.deepEqual(labels('dj cue B go '),['1','2','3','4','5','6','7','8']);
 assert(labels('lv sea').includes('search')); assert(labels('lv search Virginia Woolf --l').includes('--limit'));
 assert.deepEqual(labels('clip export --format '),['story','video','wav']);
 assert(labels('tone harmony 440 660 --c').includes('--chord'));
 assert.deepEqual(labels('tone sweep 220 880 --curve=l'),['linear','log']);
 assert(!labels('dj ').includes('mixxx')); assert(!labels('jam ').includes('token'));
});
test('submit-time corrections target only the first unknown grammar token; free data is untouched',()=>{
 const correct=text=>choices(text,text.length,{correctionsOnly:true});
 const text='dj cuw A set 2', [pick]=correct(text);
 assert.equal(pick.value,'cue'); assert.equal(text.slice(pick.start,pick.end),'cuw'); assert(pick.correction);
 assert.equal(correct('tone sine 440 --secnods 2')[0].value,'--seconds');
 assert.equal(correct('tone sweep 220 880 --curve=lg')[0].value,'log');
 for(const free of ['sources Plaay','jam create DeeJayy','jam join !room:example.org','librivox search "The Wvae"','dj eq A low -5','add https://example.org/plaay','tone sine 440 --seconds=.5'])
   assert.deepEqual(correct(free),[],free);
});
test('caret edits preserve arguments after the cursor, Unicode, quotes and paths',()=>{
 const text='DJ cuu A set 2', [pick]=choices(text,5);
 assert.equal(text.slice(0,pick.start)+pick.value+text.slice(pick.end),'DJ cue A set 2');
 const dynamic=(words,prefix)=>{assert.deepEqual(words,['karaoke','part']);assert.equal(prefix,'Al');return [{value:'Alto II',description:'Vocal part'}];};
 const line='karaoke part "Al'; const part=choices(line,line.length,{dynamic}).find(p=>p.label==='Alto II');
 assert.equal(part.value,'"Alto II"'); assert.deepEqual(parse(line.slice(0,part.start)+part.value),['karaoke','part','Alto II']);
 assert.deepEqual(parse("speech speaker O'Connor"),['speech','speaker',"O'Connor"]);
 assert.deepEqual(parse('DJ CUE a SET 2',data),['dj','cue','A','set','2']);
 assert.deepEqual(parse('sources "The 🌙"'),['sources','The 🌙']);
 assert.throws(()=>parse('speech speaker "A'),/Close the quoted/);
 assert.deepEqual(parse(String.raw`add C:\music\track`),['add',String.raw`C:\music\track`]);
 assert.equal(scan('x 🌙y')[1].end,5);
});
test('confirmation flags and confirmation values require a genuine typed prefix and never appear in fuzzy review',()=>{
 const g=[{path:'erase',flags:['--force','--format']},{path:'erase <confirmation>',values:{confirmation:['yes']}}];
 const values=(s,opts)=>suggest(s,s.length,g,opts).map(p=>p.label);
 assert(!values('erase ').includes('yes'));assert(!values('erase --').includes('--force'));assert(values('erase --fo').includes('--force'));
 assert(!values('erase --froce',{correctionsOnly:true}).includes('--force'));
 assert(!values('erase yse',{correctionsOnly:true}).includes('yes'));
 assert(values('erase ye').includes('yes'));
});

test('the portable grammar and the real dispatcher have the same command and alias roots',()=>{
 const roots=new Set(data.flatMap(row=>[row.path,...row.aliases || []]).map(path=>path.split(' ')[0]));
 const src=readFileSync(new URL('../web/player/player.js',import.meta.url),'utf8');
 const dispatcher=src.slice(src.indexOf('async function command(text)'),src.indexOf('const commandInput'));
 const actual=new Set(Array.from(dispatcher.matchAll(/case '([^']+)':/g),m=>m[1]));
 assert.deepEqual([...roots].sort(),[...actual].sort());
});

test('every portable route and alias is reachable, and no exact spelling triggers a correction',()=>{
 for (const row of data) for (const spelling of [row.path,...row.aliases || []]) {
   const parts=spelling.split(/\s+/);
   const example=parts.map(word=>word.startsWith('<') ? String(row.values?.[word.slice(1,-1)]?.[0] ?? 'Sample') : word);
   const line=example.join(' ');
   assert.deepEqual(choices(line,line.length,{correctionsOnly:true}),[],line);
   const last=parts.at(-1);
   if (last.startsWith('<') && !row.values?.[last.slice(1,-1)]?.length) continue;
   const matches=choices(line);
   assert(matches.some(p=>(line.slice(0,p.start)+p.value+line.slice(p.end)).toLowerCase()===line.toLowerCase()),line);
 }
});
test('quoted paths, Windows drives and natural apostrophes survive command execution parsing',()=>{
 for(const [line,args] of [
   [String.raw`speech speaker "D:\Vivo Jay\music"`,['speech','speaker',String.raw`D:\Vivo Jay\music`]],
   [String.raw`add \\nas\share\song.wav`,['add',String.raw`\\nas\share\song.wav`]],
   [String.raw`add "\\nas\share name\song.wav"`,['add',String.raw`\\nas\share name\song.wav`]],
   ['add "D:\\Music Files\\"',['add','D:\\Music Files\\']],
   ["sources artist's track",['sources',"artist's",'track']],
   [`sources "artist's track"`,['sources',"artist's track"]],
   [String.raw`sources "a \"quoted\" artist"`,['sources','a "quoted" artist']],
 ]) assert.deepEqual(parse(line,data),args);
});

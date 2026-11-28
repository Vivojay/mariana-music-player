import assert from 'node:assert/strict';
import test from 'node:test';
import '../web/player/completion-values.js';

const {suggest} = globalThis.MarianaPortableValues;
test('queue completion searches local labels, inserts one-based indices and excludes control text', () => {
  const queue=[{title:'Morning set'},{title:'Evening study'}];
  assert.deepEqual(suggest(['play'],'eve',{queue}), [{value:'2',description:'Evening study'}]);
  assert.deepEqual(suggest(['jam','suggest','!jam:example.org'],'eve',{queue}),
    [{value:'Evening study',description:'Player track'}]);
  assert.deepEqual(suggest(['theme'],'dr',{themes:{dracula:{name:'Dracula'},'dr\nX':{name:'untrusted'}}}),
    [{value:'dracula',description:'Dracula'}]);
  assert.deepEqual(suggest(['add'],'https://', {queue}),[]);
});

test('reads the already-mounted options without initiating requests or inspecting account sessions', () => {
  const elements={
    'karaoke-part':{options:[{value:'all',textContent:'All singers'},{value:'0',textContent:'Alto voice'}]},
    'karaoke-controls':{hidden:false}, 'account-provider':{options:[{value:'lastfm',textContent:'Last.fm'}]},
    'jam-room':{value:'!room:example.org'}
  };
  const ctx={el:id=>elements[id]};
  assert.equal(suggest(['karaoke','part'],'alt',ctx)[0].value,'Alto voice');
  elements['karaoke-controls'].hidden=true;
  assert.deepEqual(suggest(['karaoke','part'],'alt',ctx),[]);
  assert.equal(suggest(['accounts','open'],'last',ctx)[0].value,'lastfm');
  assert.deepEqual(suggest(['accounts','link','lastfm'],'',ctx),[]);
  assert.equal(suggest(['jam','members'],'!',ctx)[0].value,'!room:example.org');
  assert.deepEqual(suggest(['jam','login'],'',ctx),[]);
});

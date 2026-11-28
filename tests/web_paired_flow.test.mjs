import assert from 'node:assert/strict';
import test from 'node:test';
import '../web/player/companion-flow.js';
const {positionAt} = globalThis.MarianaPairedFlow;

test('interpolates playing clocks and stops extrapolating after missed updates', () => {
  const playing = {state:'playing',position_seconds:25,duration_seconds:40,playback_rate:1.5};
  assert.equal(positionAt(playing,.5),25.75);
  assert.equal(positionAt(playing,300),27.025);
  assert.equal(positionAt({...playing,state:'paused'},.5),25);
  assert.equal(positionAt({...playing,state:'seeking'},.5),25);
  assert.equal(positionAt({...playing,duration_seconds:25.3},.5),25.3);
  assert.equal(positionAt({...playing,region:{active:true,end_seconds:25.4}},.5),25.4);
});

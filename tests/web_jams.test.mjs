import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const script = readFileSync(new URL('../web/player/jams.js', import.meta.url), 'utf8');
function setup(origin = 'http://127.0.0.1:8767') {
  const calls = [], applied = [], fields = new Map();
  function field(id) {
    if (!fields.has(id)) fields.set(id, {
      value:'', hidden:false, textContent:'', querySelectorAll:() => [],
      addEventListener(type, handler) { this[type] = handler; },
    });
    return fields.get(id);
  }
  const win = {MarianaJamTransport:{
    state:() => ({title:'Glass House', paused:true, seconds:12.5}),
    apply:async cue => { applied.push(cue); },
  }};
  const cue = {title:'Glass House', action:'pause', seconds:12.5};
  async function fetch(path, options) {
    const args = JSON.parse(options.body);
    calls.push(args);
    assert.equal(path, '/api/jam');
    assert.equal(options.method, 'POST');
    assert.equal(options.headers['X-Mariana-Jam'], '1');
    assert.equal(options.credentials, 'same-origin');
    const result = args[0] === 'create' ? {message:'Created', room_id:'!practice:example'}
      : args[0] === 'current' || args[0] === 'sync' ? {message:'Host cue', cue}
      : {message:'Done'};
    return {ok:true, headers:{get:()=>'application/json'}, json:async()=>result};
  }
  vm.runInNewContext(script, {window:win, document:{getElementById:field}, location:new URL(origin), fetch});
  const click = action => field('jam-actions').click({target:{closest:()=>({dataset:{jam:action}})}});
  return {click, field, command:win.MarianaJams.command, applied, calls, cue};
}

test('Flow and Console share room ID, commands and an explicit playhead transport', async () => {
  const app = setup();
  app.field('jam-name').value = 'Evening rehearsal';
  await app.click('create');
  assert.equal(app.field('jam-room').value, '!practice:example');
  app.field('jam-user').value = '@bob:example';
  await app.click('invite');
  app.field('jam-track').value = 'Glass House';
  await app.click('suggest');
  await app.click('send');
  await app.click('current');
  assert.equal(app.applied.length, 0);
  assert.equal(await app.command(['apply', '!practice:example']), 'Applied Host cue');
  await app.click('sync');
  assert.equal(app.applied.length, 2);
  assert.equal(app.applied[0], app.cue);
  assert.deepEqual(app.calls, [
    ['create', 'Evening rehearsal'], ['invite', '!practice:example', '@bob:example'],
    ['suggest', '!practice:example', 'Glass House'], ['cue', '!practice:example', 'pause', '12.5', 'Glass House'],
    ['current', '!practice:example'], ['current', '!practice:example'], ['sync', '!practice:example'],
  ]);
});

test('static player advertises local requirements and starts no account activity', async () => {
  const app = setup('https://player.example');
  assert.equal(app.field('jam-actions').hidden, true);
  await assert.rejects(() => app.command(['login', 'https://homeserver.example']), /local Mariana web launcher/);
  assert.match(await app.command(['help']), /jam join ROOM/);
  assert.equal(app.calls.length, 0);
});

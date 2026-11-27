import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../web/player/listener-profiles.js', import.meta.url), 'utf8');
function storage() {
  const rows = new Map();
  return {get length() { return rows.size; }, key: i => [...rows.keys()][i],
    getItem: k => rows.get(k) ?? null, setItem: (k,v) => rows.set(k, v)};
}
function load(localStorage, sessionStorage) {
  const window = {};
  let reloads = 0;
  vm.runInNewContext(source, {window, localStorage, sessionStorage,
    location:{reload:()=>reloads++}, document:{getElementById:()=>null}});
  return {api:window.MarianaProfiles, reloads:()=>reloads};
}
test('legacy data remains in Default and an explicit switch isolates the next document', () => {
  const local = storage(), tab = storage(), another = storage();
  const first = load(local, tab);
  local.setItem(first.api.key('queue'), 'original');
  first.api.run(['create','Studio','A']);
  assert.throws(()=>first.api.run(['create','studio','a']), /already/);
  assert.throws(()=>first.api.run(['use','Missing']), /first/);
  first.api.run(['use','Studio','A']);
  assert.equal(first.reloads(),1);
  assert.equal(first.api.key('queue'),'queue');
  const second = load(local,tab);
  assert.match(second.api.run(['current']),/Studio A/);
  assert.equal(local.getItem(second.api.key('queue')),null);
  local.setItem(second.api.key('queue'),'studio');
  assert.notEqual(second.api.key('mariana-web-audio'), 'mariana-web-audio');
  assert.equal(load(local,another).api.current,'default');
  second.api.run(['use','Default']);
  assert.equal(local.getItem(load(local,tab).api.key('queue')),'original');
});

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';

const source = fs.readFileSync(new URL('../web/player/voice.js', import.meta.url), 'utf8');
function studio(provider = '', mobile = false) {
  const fields = new Map();
  function field(id) {
    if (!fields.has(id)) fields.set(id, {
      value: '', hidden: false, setAttribute(k,v) { this[k]=v; }, removeAttribute(k) { delete this[k]; },
      appendChild(el) { this.firstElementChild = el; }, replaceChildren() { this.firstElementChild = null; },
      focus() {}, select() {},
    });
    return fields.get(id);
  }
  const win = {MarianaNativeShell: mobile, MarianaMeetingOrigin: provider};
  vm.runInNewContext(source, {window: win, crypto: webcrypto, URL, location: new URL('http://127.0.0.1:8767'),
    document: {getElementById: field, createElement: () => ({setAttribute(k,v){ this[k]=v; }})}});
  return {field, join: () => field('voice-form').onsubmit({preventDefault(){}})};
}
test('public calls stay external, with a fresh invite for each meeting', () => {
  const {field, join} = studio();
  assert.equal(field('voice-join').hidden,true);
  field('voice-new').onclick();
  const first = field('voice-external').href;
  assert.match(first,/^https:\/\/meet\.jit\.si\/Mariana-[a-f0-9]{32}$/);
  field('voice-new').onclick();
  assert.notEqual(first,field('voice-external').href);
  join();
  assert.equal(field('voice-frame').firstElementChild, undefined);
  for (const link of ['https://meet.jit.si.example.com/abc','https://name@meet.jit.si/abc','https://meet.jit.si/abc?x=1']) {
    field('voice-link').value = link; field('voice-link').oninput();
    assert.equal(field('voice-external').href, undefined);
  }
});
test('configured external host is contacted only after Join and removed on Leave', () => {
  const {field, join} = studio('https://meet.example.org');
  field('voice-new').onclick();
  assert.equal(field('voice-frame').firstElementChild, undefined);
  join();
  assert.match(field('voice-frame').firstElementChild.src,/^https:\/\/meet\.example\.org\/Mariana-/);
  assert.equal(field('voice-leave').hidden, false);
  field('voice-leave').onclick();
  assert.equal(field('voice-frame').firstElementChild, null);
  assert.equal(field('voice-join').disabled, false);
  const {field: phone, join: phoneJoin} = studio('https://meet.example.org', true);
  phone('voice-new').onclick(); phoneJoin();
  assert.equal(phone('voice-frame').firstElementChild, undefined);
});

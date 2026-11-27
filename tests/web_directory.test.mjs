import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const data = JSON.parse(readFileSync(new URL('../desktop/culture_sources.json', import.meta.url)));
const script = readFileSync(new URL('../web/player/directory.js', import.meta.url), 'utf8');

class Element {
  children = [];
  listeners = {};
  value = '';
  append(...children) { this.children.push(...children); }
  add(item) { this.append(item); }
  replaceChildren() { this.children = []; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  setAttribute(key, value) { this[key] = value; }
}

function app(hostname = 'player.example') {
  const window = {MARIANA_SOURCES:data};
  const ids = new Map();
  const document = {
    createElement: () => new Element(),
    getElementById(id) { if (!ids.has(id)) ids.set(id, new Element()); return ids.get(id); },
  };
  vm.runInNewContext(script, {window, document, Option:class {}, location:{hostname, protocol:'https:'}});
  return {api:window.MarianaDirectory, get:id => ids.get('directory-' + id)};
}

test('all sources are available offline, with pagination and category filtering', () => {
  const {api, get} = app();
  assert.equal(get('results').children.length, 6);
  get('more').listeners.click();
  assert.equal(get('results').children.length, 12);
  const output = api.consoleSearch('');
  assert.equal(output.split('\n').length, 78);
  assert.equal(new Set(data.map(row => row.url)).size, 78);
  get('group').value = 'festival-links';
  get('group').listeners.change();
  assert.match(get('count').textContent, /6 of 18/);
  assert.match(api.consoleSearch('angouleme'), /Angoulême/);
  assert.match(api.consoleSearch('PAN!C ROOM'), /youtube.com\/channel\/UCANlvQuGwrusnPsc3SlTsmw/);
  assert.equal(api.consoleSearch('unfindable-source'), 'No sources matched.');
  assert.equal(get('results').children.length, 0);
});

test('official links open separately on the web and use explicit native navigation in the phone shell', () => {
  for (const [hostname, target] of [['player.example','_blank'],['app.mariana.invalid','_self']]) {
    const {api,get} = app(hostname);
    api.consoleSearch('Sigil Radio');
    const link = get('results').children[0].children[0];
    assert.equal(link.href,'https://sigilradio.live/');
    assert.equal(link.target,target);
    assert.equal(link.rel,'noopener noreferrer');
  }
});

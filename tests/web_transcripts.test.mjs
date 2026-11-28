import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const code = readFileSync(new URL('../web/player/transcripts.js', import.meta.url), 'utf8');
class Element {
  constructor() { this.children = []; this.value = ''; this.textContent = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this[key] = value; }
  removeAttribute(key) { delete this[key]; }
}
function app(fetch) {
  const window = {};
  const document = {createElement:() => new Element(), createTextNode:text => ({textContent:text})};
  vm.runInNewContext(code, {window, document, fetch, URL, TextDecoder, AbortController, TypeError, setTimeout, clearTimeout,
    Option:class { constructor(label, value) { this.label = label; this.value = value; } }});
  return window.MarianaTranscripts;
}
const json = value => JSON.parse(JSON.stringify(value));
const variant = {url:'https://publisher.example/ep.vtt', type:'text/vtt', language:'en'};

test('feed namespace and relative assets are scoped and HTTP only', () => {
  const child = (attrs, ns = 'https://podcastindex.org/namespace/1.0') =>
    ({localName:'transcript', namespaceURI:ns, getAttribute:key => attrs[key]});
  const items = {children:[child({...variant, url:'./ep.vtt'}), child({...variant, url:'file:///etc/passwd'}),
    child(variant, 'https://unrelated.example'), child(variant), child({...variant, type:'text/html', url:'./read'})]};
  const found = json(app().fromEpisode(items, 'https://publisher.example/feed'));
  assert.deepEqual(found, [variant, {...variant, type:'text/html', url:'https://publisher.example/read'}]);
});

test('timed formats, invalid timestamps and readable plain text', () => {
  const {parse} = app();
  assert.deepEqual(json(parse('WEBVTT\r\n\r\nNOTE testing\r\nignore\r\n\r\nid\r\n00:03.100 --> 00:05.000 align:start\r\n<b>Hello</b> &amp; welcome', 'text/vtt')),
    [{text:'Hello & welcome', start:3.1}]);
  assert.deepEqual(json(parse('1\n00:01:45,920 --> 00:01:48,000\nHello\nagain', 'application/x-subrip')),
    [{text:'Hello again', start:105.92}]);
  assert.deepEqual(json(parse('{"segments":[{"startTime":2,"endTime":3,"speaker":"Dan","body":"hi"},{"body":"bad"}]}', 'application/json')),
    [{text:'Dan: hi', start:2}]);
  assert.deepEqual(json(parse('one\n\ntwo', 'text/plain')), [{text:'one', start:null}, {text:'two', start:null}]);
  assert.throws(() => parse('00:60.000 --> 00:01.000\nhuh', 'text/vtt'), /no readable/);
  assert.throws(() => parse('<script>abc</script>', 'text/html'), /publisher website/);
});

test('reader enforces a streamed byte limit without trusting Content-Length', async () => {
  const payload = new ReadableStream({start(c) { c.enqueue(new Uint8Array(2 * 1024 * 1024)); c.enqueue(new Uint8Array(1)); c.close(); }});
  const a = app(async () => new Response(payload));
  await assert.rejects(a.fetchText(variant.url), /2 MiB/);
});

test('local draft import preserves speakers and safely binds seeking to the active file', async () => {
  const nodes = {}, el = id => nodes[id] ??= new Element();
  let current = {id: 'local-1'}, seeked;
  const bind = app().mount(el, value => { seeked = value; }, () => current);
  const owner = current;
  bind(current);
  assert.equal(el('episode-transcript').hidden, false);
  assert.equal(el('transcript-online').hidden, true);
  const draft = {schema: 'mariana.transcript-draft.v1', segments: [
    {startTime:1.25, endTime:2.5, body:'नमस्ते', speaker:'Speaker 2', language:'hi'},
  ]};
  el('transcript-file').files = [{name:'draft.json', size:12, text: async () => JSON.stringify(draft)}];
  await el('transcript-file').onchange();
  const [jump, text] = el('transcript-cues').children[0].children;
  assert.equal(text.textContent, '[hi] Speaker 2: नमस्ते');
  assert.match(el('transcript-status').textContent, /Imported captions/);
  jump.onclick(); assert.equal(seeked, 1.25);
  current = {id: 'local-2'}; bind(current); seeked = null;
  jump.onclick(); assert.equal(seeked, null);
  assert.equal(el('transcript-cues').children.length, 0);
  current = owner; bind(owner);
  assert.equal(el('transcript-cues').children.length, 1);
  assert.deepEqual(json(app().parse('WEBVTT\n\n00:00:01.250 --> 00:00:02.000\n<v Speaker 2>Hi</v>', 'text/vtt')),
    [{text:'Speaker 2: Hi', start:1.25}]);
});

test('load is explicit, stale downloads cannot update the current episode, and literal search and seek are bound', async () => {
  const nodes = {};
  const el = id => nodes[id] ??= new Element();
  const vtt = 'WEBVTT\n\n00:01.250 --> 00:03.000\nhello [.*] <img src=x>\n\n00:04.000 --> 00:05.000\nbye';
  let resolve, calls = 0, current, position;
  const transcript = app(() => { calls++; return new Promise(r => { resolve = r; }); });
  const bind = transcript.mount(el, value => { position = value; }, () => current);
  current = {transcripts:[variant]}; bind(current);
  assert.equal(calls, 0);
  const pending = el('transcript-load').onclick();
  current = null; bind(null);
  resolve(new Response(vtt)); await pending;
  assert.equal(el('episode-transcript').hidden, true);
  assert.equal(el('transcript-cues').children.length, 0);
  current = {transcripts:[variant]}; bind(current);
  const read = el('transcript-load').onclick(); resolve(new Response(vtt)); await read;
  el('transcript-query').value = '[.*]'; el('transcript-query').oninput();
  assert.equal(el('transcript-cues').children.length, 1);
  const [button, text] = el('transcript-cues').children[0].children;
  assert.match(text.textContent, /<img src=x>/);
  button.onclick(); assert.equal(position, 1.25);
  position = null; current = {}; button.onclick(); assert.equal(position, null);
});

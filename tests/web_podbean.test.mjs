import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const script = readFileSync(new URL('../web/player/catalog.js', import.meta.url), 'utf8');
const feed = 'https://feed.podbean.com/night/feed.xml';

function catalog() {
  const ids = new Map();
  const element = () => ({
    children:[], append(...rows) { this.children.push(...rows); },
    replaceChildren(...rows) { this.children = rows; }, addEventListener() {},
  });
  const document = {createElement:element, getElementById(id) {
    if (!ids.has(id)) ids.set(id, element());
    return ids.get(id);
  }};
  const state = new Map(), requests = [], queue = [];
  const context = {window:{MarianaTranscripts:{fromEpisode:() => []}}, document,
    URL, URLSearchParams, AbortController, TextDecoder, setTimeout, clearTimeout, current:null,
    queue, append:async items => {
      const fresh = items.filter(item => !queue.some(row => row.url === item.url));
      queue.push(...fresh);
      return fresh.length;
    },
    select:async (row, start) => { assert.equal(start, true); context.current = row; },
    play:async () => { assert.ok(context.current); }, button:element,
    localStorage:{getItem:key => state.get(key), setItem:(key, val) => state.set(key, val)},
    fetch:async (url, options) => {
      requests.push(String(url));
      assert.equal(options.credentials, 'omit');
      if (String(url).startsWith('https://itunes.apple.com/search?')) {
        return Response.json({results:[{feedUrl:feed, collectionName:'Night'},
          {feedUrl:feed, collectionName:'Duplicate'}, {feedUrl:'https://other.example/rss', collectionName:'Other'}]});
      }
      if (String(url).includes('/api/feed/audiobooks/')) return Response.json({books:[{
        id:'42', title:'My book', url_rss:'https://librivox.org/rss/42',
        authors:[{first_name:'Ada', last_name:'Reader'}], language:'English', totaltime:'01:20:00'}]});
      if (String(url) !== feed && String(url) !== 'https://librivox.org/rss/42') return new Response('', {status:404});
      return new Response('fixture feed');
    },
    DOMParser:class {
      parseFromString(text) {
        assert.equal(text, 'fixture feed');
        const rows = Array.from({length:12}, (_, i) => ({
          querySelector:() => ({textContent:'Episode ' + (i + 1)}),
          querySelectorAll:() => [{getAttribute:key => ({url:'https://audio.example/' + (i + 1) + '.mp3', type:'audio/mpeg'})[key]}],
        }));
        return {querySelector:key => key === 'parsererror' ? null : {textContent:'Night'},
          querySelectorAll:() => rows};
      }
    },
  };
  vm.runInNewContext(script, context);
  return {run:(...args) => context.window.MarianaPodbean.command(args), context, queue, requests, state};
}

test('Podbean public search, stable episode numbers, queue, playback and shelf', async () => {
  const {run, context, queue, requests, state} = catalog();
  assert.equal(await run('search','late','night'), 'night · Night');
  assert.match(requests[0], /term=late\+night/);
  const completionRows = context.window.MarianaPodbean.completionRows;
  assert.equal(completionRows('open')[0].value, 'night');
  assert.equal(requests.length, 1);
  assert.match(await run('open','https://night.podbean.com'), /page 1\/2/);
  assert.equal(requests[1], feed);
  assert.equal(completionRows('queue')[11].description, 'Episode 12');
  assert.equal(completionRows('episodes')[1].value, '2');
  assert.equal(requests.length, 2);
  assert.match(await run('episodes','2'), /11\. Episode 11\n12\. Episode 12/);
  assert.equal(queue.length, 0);
  assert.match(await run('follow'), /Following night/);
  assert.equal(await run('list'), 'night · Night');
  assert.equal(JSON.parse(state.get('mariana.public-feeds.v1'))[0].feed, feed);
  await run('queue','12'); await run('play','12');
  assert.equal(queue.length, 1);
  assert.equal(context.current.url, 'https://audio.example/12.mp3');
  assert.equal(context.current.spoken, true);
  await assert.rejects(() => run('queue','13'), /between/);
  await run('unfollow','night');
  assert.match(await run('list'), /No followed/);
});

test('reader never submits a private token and cannot play stale numbers after a failed open', async () => {
  const {run, requests} = catalog();
  await run('open','night');
  await assert.rejects(() => run('open',feed + '?token=private'), /public feed/);
  assert.equal(requests.length, 1);
  assert.match(await run('open','missing'), /HTTP 404/);
  assert.match(await run('play','1'), /first/);
});


test('LibriVox find by author, resolve an explicit ID and play a chapter in the normal queue', async () => {
  const {context, requests, queue} = catalog();
  const run = (...args) => context.window.MarianaLibrivox.command(args);
  assert.match(await run('author','Reader','--limit','5','--offset','4'), /1. My book · Ada Reader · id:42/);
  assert.equal(context.window.MarianaLibrivox.completionRows()[0].description, 'My book');
  assert.equal(context.window.MarianaLibrivox.completionRows()[1].value, 'id:42');
  assert.equal(requests.length, 1);
  const query = new URL(requests[0]).searchParams;
  assert.equal(query.get('author'), 'Reader');
  assert.equal(query.get('offset'), '4');
  assert.equal(query.get('limit'), '5');
  assert.match(await run('chapters','1','2'), /11. Episode 11/);
  assert.match(await run('play','id:42','11'), /Selected · Episode 11/);
  assert.equal(queue.length, 12);
  assert.equal(context.current.url, 'https://audio.example/11.mp3');
  assert.match(await run('queue','1','all'), /Added 0 chapter/);
  assert.equal(await run('rss','id:42'), 'https://librivox.org/rss/42');
  assert.equal(requests.length, 2);
  const empty = catalog();
  assert.match(await empty.context.window.MarianaLibrivox.command(['show','id:42']), /English · 01:20:00/);
  assert.match(empty.requests[0], /id=42/);
});

import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const read = name => readFileSync(new URL('../' + name, import.meta.url),'utf8');

test('Android packages every first-party script and stylesheet loaded by its player', () => {
  const assets = read('mobile/android/app/src/main/java/org/marianaplayer/app/MainActivity.java');
  for (const match of read('web/player/index.html').matchAll(/(?:src|href)="([^"#:/]+\.(?:js|css))"/g))
    assert.ok(assets.includes('ASSETS.put("' + match[1] + '"'),match[1]);
});

test('PWA navigations resolve the player and each link composer independently', async () => {
  const scope = 'https://music.example/app/', listeners = {};
  const self = {registration:{scope}, addEventListener:(name, fn) => {listeners[name] = fn;}};
  const caches = {open:async () => ({match:async path => path})};
  runInNewContext(read('web/player/sw.js'),{self,caches,URL});
  for (const [page, expected] of [['?code=test&state=nonce','./index.html'],['index.html','./index.html'],
    ['share-link.html','./share-link.html'],['snap-share.html','./snap-share.html'],['unrelated.html',undefined]]) {
    let response;
    listeners.fetch({request:{url:scope+page,method:'GET',mode:'navigate'},respondWith:value=>{response=value;}});
    assert.equal(await response,expected);
  }
});

test('phone link share hands only the canonical public URL to the native sheet', async () => {
  const sent = [], win = {MarianaNativeShell:'ios', URL,
    webkit:{messageHandlers:{marianaClip:{postMessage:async fields => sent.push(JSON.parse(JSON.stringify(fields)))}}}};
  runInNewContext(read('web/player/public-share.js'),win);
  runInNewContext(read('web/player/clip-share.js'),win);
  await win.MarianaClipShare.shareLink('https://music.youtube.com/watch?v=abcdefghijk&t=25s&list=PRIVATE');
  assert.deepEqual(sent,[{op:'link',url:'https://www.youtube.com/watch?v=abcdefghijk&t=25s'}]);
  await assert.rejects(() => win.MarianaClipShare.shareLink('https://user:secret@library.example/track?token=private'));
  assert.equal(sent.length,1);
});

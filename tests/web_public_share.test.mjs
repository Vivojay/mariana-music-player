import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const root = new URL('../web/player/', import.meta.url);
const env = vm.createContext({ URL });
vm.runInContext(fs.readFileSync(new URL('public-share.js', root), 'utf8'), env);
const link = env.MarianaPublicLink;
test('music links retain the recording and useful time or track fields only', () => {
  assert.equal(link('https://youtu.be/abc_DEF-123?t=59&list=private'), 'https://www.youtube.com/watch?v=abc_DEF-123&t=59s');
  assert.equal(link('https://music.apple.com/in/album/duet/123?i=344&ct=private'), 'https://music.apple.com/in/album/duet/123?i=344');
  assert.equal(link('https://artist.bandcamp.com/track/song?from=tracking'), 'https://artist.bandcamp.com/track/song');
  assert.equal(link('https://soundcloud.com/artist/test?secret_token=abc'), 'https://soundcloud.com/artist/test');
  assert.equal(link('https://tidal.com/browse/track/123#token=x'), 'https://tidal.com/browse/track/123');
});
test('local, credential-bearing and arbitrary URLs cannot become social attachments', () => {
  for (const value of ['file:///C:/track.mp3','https://127.0.0.1/private','https://evil.tld/track/123',
    'https://www.youtube.com.evil.tld/watch?v=abc_DEF-123','https://secret@tidal.com/track/1',
    'https://tidal.com:444/track/1','https://a.bandcamp.com/private/file','https://soundcloud.com/artist/track/s-secret',
    'https://youtube.com/watch?v=1','javascript:alert(1)']) assert.equal(link(value), null, value);
});
test('the Snapchat SDK is user-activated and isolated from the player origin', () => {
  const app = fs.readFileSync(new URL('index.html',root),'utf8');
  const parent = fs.readFileSync(new URL('share-link.html',root),'utf8');
  const loader = fs.readFileSync(new URL('public-share.js',root),'utf8');
  const frame = fs.readFileSync(new URL('snap-share.html',root),'utf8');
  assert.doesNotMatch(app + parent + loader, /sdk\.snapkit\.com/);
  assert.doesNotMatch(loader, /allow-same-origin/);
  assert.match(frame, /self\.origin !== 'null'/);
  assert.match(frame, /https:\/\/sdk\.snapkit\.com\/js\/v1\/create\.js/);
});

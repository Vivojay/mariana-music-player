const prefix = 'mariana-player:' + self.registration.scope + ':';
const cacheName = prefix + '__REVISION__';
const shell = ['./','./index.html','./workspace.js','./workspace.css','./platform.js','./meeting-config.js','./command-grammar.js','./command-input.js','./command-match.js','./command-input.css','./completion-values.js','./voice.js','./share-link.html','./snap-share.html','./public-share.js','./player.css','./clip.css','./dj.css','./dj.js','./dj-engine.js','./dj-recorder.js','./clip-media.js','./clip-story.js','./clip-share.js','./clip.js','./player.js','./directory.json','./directory-data.js','./companion.js','./directory.js','./account-config.js','./jams.js','./listener-profiles.js','./accounts.js','./accounts.css','./catalog.js','./wall.js','./strudel-pattern.js','./strudel.js','./soundbank-data.js','./soundbank.js','./tone-bank.js','./tone-procedures.js','./tone-keys.css','./tone.js','./speech-dsp.js','./speech-capture.js','./effect-studio.js','./effect-worklet.js','./speech-worklet.js','./transcripts.js','./karaoke.js','./karaoke.css','./karaoke-hash.js','./karaoke-ttml.js','./karaoke-mix.js','./karaoke-invite.js','./practice-duet.js','./themes.js','./manifest.webmanifest','./icon-192.png','./icon-512.png'/*__STRUDEL_ASSETS__*/];
shell.push('./video-presets.js', './video-filters.js', './video-filters.css');
self.addEventListener('install', event => event.waitUntil(caches.open(cacheName).then(cache => cache.addAll(shell)).then(() => self.skipWaiting())));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith(prefix) && key !== cacheName).map(key => caches.delete(key)))).then(() => self.clients.claim())));
const documents = new Map(['./', './index.html', './share-link.html', './snap-share.html', './strudel-runtime/index.html']
  .map(path => [new URL(path, self.registration.scope).pathname, path === './' ? './index.html' : path]));
const local = new Set(shell.map(path => new URL(path, self.registration.scope).href));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  if (event.request.mode === 'navigate' && event.request.url.startsWith(self.registration.scope)) {
    // The OAuth return and the player share the root. Each composer has its own document.
    const file = documents.get(new URL(event.request.url).pathname);
    if (file) event.respondWith(caches.open(cacheName).then(async cache => (await cache.match(file)) || fetch(event.request)));
    return;
  }
  if (local.has(event.request.url)) event.respondWith(caches.open(cacheName).then(cache => cache.match(event.request).then(hit => hit || fetch(event.request))));
});

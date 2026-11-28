'use strict';
const el = id => document.getElementById(id);
const dryAudio = el('audio');
const localAudio = new Audio();
const localPicture = el('local-picture');
localAudio.preload = 'metadata';
localAudio.addEventListener('mariana-speech-bypass', () => {
  if (audio === localAudio) el('voice-note').textContent = 'Voice processing stopped. Playing the original audio.';
});
let audio = dryAudio;
let toneRequest = 0;
function mediaEvent(event, handler) {
  for (const player of [dryAudio, localAudio, localPicture].filter(Boolean)) player.addEventListener(event, () => {
    if (player === audio) handler();
  });
}
async function voiceMode() {
  const item = current;
  if (!item || item.url || audio !== localAudio || !window.MarianaSpeech) return;
  const mode = item.voiceMode || 'off';
  const applied = await window.MarianaSpeech.setLevel(localAudio, mode);
  if (current === item && (item.voiceMode || 'off') === mode)
    el('voice-note').textContent = applied ? 'Softening applies to this local file.' : 'This browser plays this file without voice processing.';
}
const prefsKey = window.MarianaProfiles?.key('mariana.web-player.1') ?? 'mariana.web-player.1';
let saved = {};
try { saved = JSON.parse(localStorage.getItem(prefsKey) || '{}') || {}; } catch {}
const picture = localPicture && window.MarianaVideo?.mount(el, saved.pictureFilter, effect => {
  saved.pictureFilter = effect;
  persist();
});
const queue = Array.isArray(saved.queue) ? saved.queue : [];
const library = window.MarianaWorkspace.makeLibrary(saved, queue);
let current = null;
const effectStudio = window.MarianaEffects.mount(el, localAudio, () => current);
const micStudio = globalThis.MarianaMic?.mount(el);
const showTranscript = window.MarianaTranscripts.mount(el, seek, () => current);
let objectURL = '';
let generation = 0;
let sleepTimer;
let statusTimer;
let lastSavedSecond = -1;
let feedBusy = false;
const memoryFiles = new Map();
const karaoke = window.MarianaKaraoke.mount({
  el, active:() => current, media:() => audio, seek, store:storedFile,
  getFile:item => memoryFiles.get(item.id) || storedFile('get', item.id),
  async replaceMix(item, blob) {
    if (current !== item || audio !== localAudio || !blob) throw Error('The selected local recording changed.');
    const position = audio.currentTime || 0, playing = !audio.paused, rate = audio.playbackRate;
    const previous = objectURL;
    objectURL = URL.createObjectURL(blob); audio.pause();
    item.pos = position; audio.src = objectURL; audio.playbackRate = rate;
    if (previous) URL.revokeObjectURL(previous);
    if (playing) await play();
  },
  async playDemo(key, file) {
    const before = generation;
    const stored = await storedFile('put', key, file);
    if (before !== generation) throw Error('A newer selection took precedence.');
    if (!stored) memoryFiles.set(key, file);
    let sample = queue.find(item => item.id === key);
    if (!sample) {
      sample = {id:key, title:'Practice duet', by:'Mariana · Alto and Tenor', marks:[], pos:0};
      queue.push(sample);
    }
    sample.pos = 0;
    if (sample === current && Number.isFinite(audio.duration)) seek(0);
    await select(sample, true);
  },
});
function status(message) {
  const feedback = el('status');
  feedback.textContent = message;
  clearTimeout(statusTimer);
  if (message) statusTimer = setTimeout(() => { feedback.textContent = ''; }, 9000);
}
function persist() {
  saved.queue = queue.filter(item => !item.tabOnly);
  saved.library = library.rows.filter(item => !item.tabOnly);
  try { localStorage.setItem(prefsKey, JSON.stringify(saved)); }
  catch { status('Browser storage is unavailable. This session will still play.'); }
}
function time(seconds) {
  if (!Number.isFinite(seconds)) return '—';
  const s = Math.max(0, Math.floor(seconds));
  return s >= 3600 ? [Math.floor(s / 3600), String(Math.floor(s / 60) % 60).padStart(2, '0'), String(s % 60).padStart(2, '0')].join(':') :
    Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}
function id() { return globalThis.crypto?.randomUUID?.() || (Date.now().toString(36) + Math.random().toString(36).slice(2)); }
const fileDB = new Promise(resolve => {
  try {
    const request = indexedDB.open(window.MarianaProfiles?.key('mariana-web-audio') ?? 'mariana-web-audio', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('files');
    request.onsuccess = () => resolve(request.result);
    request.onerror = request.onblocked = () => resolve(null);
  } catch { resolve(null); }
});
async function storedFile(action, key, value) {
  const db = await fileDB;
  if (!db) return null;
  return new Promise(resolve => {
    const tx = db.transaction('files', action === 'get' ? 'readonly' : 'readwrite');
    const store = tx.objectStore('files');
    const op = action === 'put' ? store.put(value, key) : store[action](key);
    tx.oncomplete = () => resolve(action === 'get' ? op.result : true);
    tx.onerror = tx.onabort = () => resolve(null);
  });
}
function button(label, handler, name) {
  const b = document.createElement('button');
  b.type = 'button'; b.textContent = label; b.addEventListener('click', handler);
  if (name) b.setAttribute('aria-label', name);
  return b;
}
const workspace = window.MarianaWorkspace.mount({
  list: library.view,
  play: item => useLibraryItem(item, true),
  queue: item => useLibraryItem(item, false),
  remove: forgetLibraryItem,
});
el('native-navigation').onclick = () => {
  workspace.open('settings');
  el('native-link-title').parentElement.open = true;
};
function drawQueue() {
  el('queue').replaceChildren();
  el('empty').hidden = queue.length > 0;
  el('dock-title').textContent = current?.title || 'Nothing playing';
  for (const [i, item] of queue.entries()) {
    const li = document.createElement('li');
    const pick = button((i + 1) + '. ' + item.title, () => select(item, true));
    pick.className = 'item'; pick.title = item.title; pick.setAttribute('aria-current', String(current === item));
    li.append(pick, button('Remove', () => remove(item), 'Remove ' + item.title)); el('queue').append(li);
  }
}
function drawMarks() {
  el('marks').replaceChildren();
  for (const pos of current?.marks || []) {
    const li = document.createElement('li');
    li.append(button('Go to ' + time(pos), () => seek(pos)), button('Remove', () => {
      current.marks = current.marks.filter(x => x !== pos); persist(); drawMarks();
    }, 'Remove bookmark at ' + time(pos)));
    el('marks').append(li);
  }
}
const clipStudio = globalThis.MarianaClips.mount(el, () => ({item:current, duration:audio.readyState >= 1 ? audio.duration : NaN, position:audio.currentTime}),
  item => memoryFiles.get(item.id) || storedFile('get', item.id), () => { audio.pause(); djStudio?.pause(); strudelStudio?.stopPreview(); });
const djStudio = globalThis.MarianaDJ?.mount(el, () => {
  const item = current;
  if (!item || item.url) throw Error('Select a local file or generated tone in the queue first.');
  return memoryFiles.get(item.id) || storedFile('get', item.id);
}, () => { audio.pause(); clipStudio.stopPreview(); strudelStudio?.stopPreview(); }, {
  listLocal: () => library.rows.slice(),
  getLocal: key => memoryFiles.get(key) || storedFile('get', key),
});
const strudelStudio = globalThis.MarianaStrudel.mount(el, async file => {
  const key = id();
  const stored = await storedFile('put', key, file);
  if (!stored) memoryFiles.set(key, file);
  await append([{id:key,title:file.name,by:'Strudel pattern'}]);
  return stored ? 'Pattern added to the queue.' : 'Pattern added for this session. Device storage is unavailable.';
}, () => { audio.pause(); clipStudio.stopPreview(); djStudio?.pause(); });
function updateTime() {
  clipStudio.sync();
  const d = audio.duration;
  el('elapsed').textContent = time(audio.currentTime); el('duration').textContent = time(d);
  el('seek').disabled = !Number.isFinite(d) || d <= 0;
  el('seek').value = d > 0 ? 100 * audio.currentTime / d : 0;
  karaoke.tick();
}
function seek(value) {
  if (!Number.isFinite(audio.duration)) return status('Seeking requires a finite recording.');
  audio.currentTime = Math.min(audio.duration, Math.max(0, value)); updateTime();
}
async function play() {
  if (!current) { if (queue.length) return select(queue[0], true); return status('Add an audio file or URL first.'); }
  if (!audio.getAttribute('src')) return select(current, true);
  try { const started = audio.play(); void voiceMode().catch(() => status('Voice processing unavailable in this browser.')); await started; } catch (err) { if (err.name !== 'AbortError') status('Playback could not start. Check the file, codec or URL, then press Play.'); }
}
function rememberPosition() {
  if (current && audio.readyState >= 1) { current.pos = audio.ended ? 0 : audio.currentTime; persist(); }
}
async function select(item, autoplay, pictureMode='auto') {
  const seq = ++generation; rememberPosition(); current = null; audio.pause();
  audio.removeAttribute('src'); audio.load();
  if (objectURL) URL.revokeObjectURL(objectURL);
  objectURL = ''; lastSavedSecond = -1; current = item; showTranscript(item);
  audio = item && !item.url ? localAudio : dryAudio;
  picture?.show(false);
  void karaoke.change(item);
  el('voice').disabled = !item || Boolean(item.url);
  el('voice').value = item?.voiceMode || 'off';
  el('voice-note').textContent = item?.url ? 'Online streams use the original audio.' : 'Available for local files.';
  saved.selected = item?.id || ''; persist();
  el('title').textContent = item?.title || 'Choose something to play'; el('kind').textContent = item?.by || 'Music, podcasts & audiobooks';
  el('play').disabled = !item; el('play').textContent = 'Play'; updateTime(); drawQueue(); drawMarks();
  if ('mediaSession' in navigator && typeof MediaMetadata !== 'undefined') navigator.mediaSession.metadata = item ? new MediaMetadata({title:item.title, artist:item.by}) : null;
  if (!item) return;
  let src = item.url;
  if (src) {
    try { src = checkURL(src); }
    catch { return status('This saved media URL is invalid. Remove it and add it again.'); }
  }
  if (!src) {
    const file = memoryFiles.get(item.id) || await storedFile('get', item.id);
    if (seq !== generation) return;
    if (!file) return status('The saved file is unavailable. Remove it and add it again.');
    if (item.video === undefined && window.MarianaVideo?.isVideo(file)) {
      item.video = true; item.by = 'Local video'; el('kind').textContent = item.by; persist();
    }
    objectURL = URL.createObjectURL(file); src = objectURL;
  }
  if ((item.video || pictureMode === 'video') && localPicture && picture) {
    audio = localPicture;
    picture.show(pictureMode !== 'audio');
    el('voice').disabled = true;
    el('voice-note').textContent = 'The picture player uses the original audio track.';
  }
  audio.src = src; audio.playbackRate = Number(el('rate').value);
  if (autoplay) await play();
}
function move(step) {
  const index = current ? queue.indexOf(current) + step : 0;
  if (index >= 0 && index < queue.length) return select(queue[index], true);
  status(step > 0 ? 'End of queue.' : 'Start of queue.');
}
async function remove(item) {
  const i = queue.indexOf(item);
  if (i < 0) return;
  const playing = !audio.paused; queue.splice(i, 1);
  if (current === item) await select(queue[i] || queue[i - 1] || null, playing);
  if (!library.rows.some(row => row.id === item.id)) {
    memoryFiles.delete(item.id);
    if (!item.url) await storedFile('delete', item.id);
    await karaoke.forget(item.id);
  }
  persist(); drawQueue();
}
mediaEvent('loadedmetadata', () => {
  if (audio === localPicture && audio.videoWidth === 0) {
    picture?.show(false);
    status('This file has an audio track only.');
  }
  if (current?.pos > 0 && Number.isFinite(audio.duration)) seek(Math.min(current.pos, Math.max(0, audio.duration - 0.15)));
  updateTime();
});
mediaEvent('timeupdate', () => {
  updateTime(); const second = Math.floor(audio.currentTime / 5);
  if (!audio.paused && second !== lastSavedSecond) { lastSavedSecond = second; rememberPosition(); }
});
mediaEvent('play', () => { djStudio?.pause(); clipStudio.stopPreview(); strudelStudio.stopPreview(); el('play').textContent = 'Pause'; if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'playing'; });
mediaEvent('pause', () => { el('play').textContent = 'Play'; if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'paused'; rememberPosition(); });
mediaEvent('ended', () => { rememberPosition(); move(1); });
mediaEvent('error', () => {
  if (!audio.getAttribute('src')) return;
  if (audio === localPicture) {
    const message = current?.url
      ? 'The browser could not read this video URL or decode its format.'
      : 'The browser could not decode this local video. An MP4 with H.264 video or WebM with VP9 video may play on this device.';
    status(message);
    el('local-picture-notice').textContent = message;
  } else status('This source could not be played. Check the media URL and browser codec support.');
});
window.addEventListener('pagehide', rememberPosition);
function checkURL(value) {
  const u = new URL(value);
  if (!['https:','http:'].includes(u.protocol) || u.username || u.password) throw Error('Use an HTTP(S) media URL without embedded credentials.');
  return u.href;
}
async function append(items) {
  const urls = new Set(queue.map(x => x.url).filter(Boolean)); let count = 0;
  for (const item of items) {
    if (item.url && urls.has(item.url)) {
      // A previously queued direct link can gain transcript metadata from its feed.
      const existing = queue.find(row => row.url === item.url);
      if (existing && item.transcripts?.length && JSON.stringify(item.transcripts) !== JSON.stringify(existing.transcripts)) {
        existing.transcripts = item.transcripts;
        if (existing === current) showTranscript(existing);
      }
      continue;
    }
    if (item.url) urls.add(item.url);
    queue.push({...item, id:item.id || id(), marks:[], pos:0}); count++;
  }
  persist(); drawQueue(); if (!current && queue.length) await select(queue[0], false);
  return count;
}
function linkTitle(url) { const u = new URL(url); try { return decodeURIComponent(u.pathname.split('/').pop()) || u.hostname; } catch { return u.hostname; } }
async function addLink(url, feed) {
  url = checkURL(url);
  if (!feed) {
    const title = linkTitle(url), video = window.MarianaVideo?.isVideo({name:title});
    const count = await append([{url, title, by:new URL(url).hostname, video}]);
    return count ? 'Added to queue.' : 'Already in queue.';
  }
  if (feedBusy) return 'A feed is already loading.';
  feedBusy = true;
  const abort = new AbortController(), timer = setTimeout(() => abort.abort(), 15000);
  try {
    const r = await fetch(url, {signal:abort.signal, credentials:'omit', referrerPolicy:'no-referrer'});
    if (!r.ok) throw Error('Feed returned HTTP ' + r.status);
    const doc = new DOMParser().parseFromString(await r.text(), 'application/xml');
    if (doc.querySelector('parsererror')) throw Error('This URL did not return a valid feed.');
    const by = doc.querySelector('channel > title, feed > title')?.textContent || new URL(url).hostname;
    const items = [];
    for (const node of doc.querySelectorAll('item, entry')) {
      const en = node.querySelector('enclosure[url], link[rel="enclosure"][href]');
      if (!en) continue;
      try {
        const href = checkURL(new URL(en.getAttribute('url') || en.getAttribute('href'), r.url || url).href);
        items.push({url:href,title:node.querySelector('title')?.textContent || linkTitle(href),by,
          spoken:true, transcripts:window.MarianaTranscripts.fromEpisode(node, r.url || url)});
      } catch {}
      if (items.length >= 100) break;
    }
    if (!items.length) return 'No playable enclosures in this feed.';
    return 'Added ' + await append(items) + ' episode(s).';
  } catch (err) {
    if (err instanceof TypeError) throw Error('Feed unavailable. Its host must allow browser RSS access. A direct episode audio URL may still play.');
    throw err;
  } finally { clearTimeout(timer); feedBusy = false; }
}
async function useLibraryItem(item, playNow) {
  if (!library.rows.includes(item)) return;
  if (!(memoryFiles.get(item.id) || await storedFile('get', item.id))) {
    status('This file is no longer stored. Import it again to play it.');
    return;
  }
  if (!library.rows.includes(item)) return;
  let queued = queue.find(entry => entry.id === item.id);
  if (!queued) {
    queued = {...item, marks:[], pos:0};
    queue.push(queued);
    persist(); drawQueue();
  }
  if (playNow) await select(queued, true);
  else status('In your queue: ' + item.title);
}

async function forgetLibraryItem(item) {
  const index = library.rows.indexOf(item);
  if (index < 0) return;
  library.rows.splice(index, 1);
  if (!queue.some(entry => entry.id === item.id)) {
    memoryFiles.delete(item.id);
    await storedFile('delete', item.id);
  }
  persist(); workspace.render(); djStudio?.refreshLibrary?.(); status('Removed from library: ' + item.title);
}

function mediaFile(file) {
  return /^(audio|video)\//.test(file.type) ||
    /\.(aac|aiff?|ape|avi|flac|m4[abv]|mkv|mov|mp[234]|ogg|opus|wav|webm|wma)$/i.test(file.name);
}

async function importFiles(files) {
  const playable = files.filter(mediaFile);
  if (!playable.length) { status('No supported media files were selected.'); return; }
  let temporary = 0;
  for (const file of playable) {
    const key = id(), video = Boolean(window.MarianaVideo?.isVideo(file));
    const stored = await storedFile('put', key, file);
    if (!stored) { memoryFiles.set(key, file); temporary++; }
    library.rows.push({id:key, title:file.name, by:video ? 'Local video' : 'Local audio', video, tabOnly:!stored});
  }
  persist(); workspace.render(); djStudio?.refreshLibrary?.();
  status('Imported ' + playable.length + (playable.length === 1 ? ' file' : ' files') +
    (temporary ? '. ' + temporary + ' available for this tab only.' : '.'));
}
for (const input of [el('files'), el('library-folder')]) input.onchange = async () => {
  const files = [...input.files];
  input.value = '';
  try { await importFiles(files); } catch (error) { status(error.message || 'Could not import these files.'); }
};
el('add-url').onsubmit = async event => { event.preventDefault();
  try { status(await addLink(el('url').value.trim(), el('source-kind').value === 'feed')); el('url').value = ''; }
  catch (err) { status(err.message); }
};
el('seek').oninput = () => seek(audio.duration * Number(el('seek').value) / 100);
el('rew').onclick = () => seek(audio.currentTime - 15);
el('fwd').onclick = () => seek(audio.currentTime + 30);
el('play').onclick = () => audio.paused ? play() : audio.pause();
el('next').onclick = () => move(1);
el('rate').value = saved.rate || '1';
if (!el('rate').value) el('rate').value = '1';
el('voice').onchange = async () => {
  if (!current || current.url) return;
  current.voiceMode = el('voice').value; persist();
  try { await voiceMode(); } catch { status('This browser plays this file without voice processing.'); }
};
el('rate').onchange = () => { audio.playbackRate = Number(el('rate').value); saved.rate = el('rate').value; persist(); };
el('sleep').onchange = () => {
  clearTimeout(sleepTimer); const minutes = Number(el('sleep').value);
  if (minutes) sleepTimer = setTimeout(() => { audio.pause(); el('sleep').value = '0'; status('Sleep timer ended.'); }, minutes * 60000);
  status(minutes ? 'Playback will pause in ' + minutes + ' minutes.' : 'Sleep timer off.');
};
el('bookmark').onclick = () => {
  if (!current || audio.readyState < 1) return status('Load a recording to add a bookmark.');
  const pos = Math.floor(audio.currentTime);
  current.marks = [...new Set([...(current.marks || []), pos])].sort((a,b) => a-b);
  persist(); drawMarks(); status('Bookmarked ' + time(pos));
};
if ('mediaSession' in navigator) {
  const actions = {play, pause:() => audio.pause(), nexttrack:() => move(1), previoustrack:() => move(-1),
    seekto:e => seek(e.seekTime), seekbackward:e => seek(audio.currentTime - (e.seekOffset || 15)), seekforward:e => seek(audio.currentTime + (e.seekOffset || 30))};
  for (const [action, handler] of Object.entries(actions)) { try { navigator.mediaSession.setActionHandler(action,handler); } catch {} }
}
function mode(value) {
  document.body.dataset.mode = value;
  document.body.dataset.commandOpen = 'false';
  el('flow-command').setAttribute('aria-expanded','false');
  for (const btn of document.querySelectorAll('nav button')) btn.setAttribute('aria-pressed', String(btn.dataset.mode === value));
  saved.mode = value; persist();
}
for (const btn of document.querySelectorAll('nav button')) btn.onclick = () => mode(btn.dataset.mode);
function applyTheme(key) {
  const preset = window.MARIANA_THEMES[key]; if (!preset) return false;
  document.body.dataset.preset = key;
  saved.theme = key; el('theme').value = key; el('colors').replaceChildren();
  for (const [name, defaultColor] of Object.entries(preset.chrome)) {
    const label = document.createElement('label'), input = document.createElement('input');
    const color = saved.overrides?.[key]?.[name] || defaultColor;
    document.documentElement.style.setProperty('--'+name,color);
    label.textContent = name; input.type = 'color';
    if (/^#[a-f0-9]{6}(?:[a-f0-9]{2})?$/i.test(color)) input.value = color.slice(0,7);
    input.oninput = () => {
      saved.overrides = saved.overrides || {}; saved.overrides[key] = saved.overrides[key] || {}; saved.overrides[key][name] = input.value;
      document.documentElement.style.setProperty('--'+name,input.value); persist();
    };
    label.append(input); el('colors').append(label);
  }
  persist(); return true;
}
for (const [key,t] of Object.entries(window.MARIANA_THEMES)) el('theme').add(new Option(t.name,key));
el('theme').onchange = () => applyTheme(el('theme').value);
el('reset').onclick = () => { if (saved.overrides) delete saved.overrides[saved.theme]; applyTheme(saved.theme); };
function transcript(line) { const out = el('transcript'); out.textContent = (out.textContent+'\n'+line).slice(-9000); out.scrollTop=out.scrollHeight; }
async function command(text) {
  const [cmd='', ...args] = globalThis.MarianaCommandMatch.parse(text,globalThis.MarianaPortableGrammar), arg=args.join(' ');
  const area = ({accounts:'settings', profile:'settings', theme:'settings', fx:'studio', dj:'studio',
    karaoke:'studio', lyrics:'studio', clip:'studio', speech:'studio', strudel:'studio', voice:'rooms', jam:'rooms',
    wall:'rooms', sources:'discover', podbean:'discover', librivox:'discover', lv:'discover', libri:'discover', home:'discover',
    files:'library', library:'library', queue:'library', native:'settings'})[cmd.toLowerCase()];
  if (area && document.body.dataset.mode === 'flow') {
    const target = args[0]?.toLowerCase() === 'setup' && cmd.toLowerCase() === 'accounts' ?
      ({karaoke:'studio',podcasts:'discover',audiobooks:'discover'})[args[1]?.toLowerCase()] : '';
    workspace.open(target || area);
  }
  switch (cmd.toLowerCase()) {
    case 'video': return picture?.command(args, audio === localPicture && (audio.readyState === 0 || audio.videoWidth > 0))
      ?? 'Picture controls are unavailable.';
    case 'strudel': return strudelStudio.command(args);
    case 'karaoke': return karaoke.command(arg);
    case 'lyrics': if (args[0]?.toLowerCase() === 'voices') return karaoke.voices(); return 'Use lyrics voices for singer-labelled lyrics.';
    case 'help': return 'karaoke help · podbean help · librivox help · add URL · feed URL · native · files · library · queue · play [#] · pause · stop · next · previous · seek SECONDS · speed RATE · bookmark · fx help · dj help · speech help · clip help · sources [query] · accounts · voice · jam help · wall · strudel help · tone help · theme [NAME] · flow · console';
    case 'librivox': case 'lv': case 'libri': return window.MarianaLibrivox.command(args);
    case 'podbean': return window.MarianaPodbean.command(args);
    case 'jam': return window.MarianaJams.command(args);
    case 'profile': return window.MarianaProfiles.run(args);
    case 'accounts': return window.MarianaAccounts.command(args);
    case 'sources': return window.MarianaDirectory.consoleSearch(arg);
    case 'home': if (args[0]?.toLowerCase() === 'sources') return window.MarianaDirectory.consoleSearch(args.slice(1).join(' '));
      return 'Use home sources [query] to search the culture directory.';
    case 'wall': {
      const heading = el('wall-title'); heading.focus(); heading.scrollIntoView({block:'start'});
      return 'Music wall opened. Add a post, browse a profile or exchange a wall.';
    }
    case 'soundbank':
    case 'tone': {
      const bank = cmd.toLowerCase() === 'soundbank';
      if (bank && (!args.length || args[0] === 'help')) return 'soundbank list [family] · soundbank play <table> [Hz] · soundbank export <table>';
      if (bank && args[0] === 'list' && args.length <= 2) return window.MarianaSoundbank.list(args[1]);
      if (bank && args[0] === 'export' && args.length === 2) {
        const url = URL.createObjectURL(window.MarianaSoundbank.table(args[1]));
        const link = document.createElement('a');
        link.href = url; link.download = args[1] + '.wav'; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
        return 'Exported ' + link.download;
      }
      if (bank && (args[0] !== 'play' || args.length < 2 || args.length > 3)) throw Error('Enter soundbank help for usage.');
      if (!arg || args[0] === 'help') return window.MarianaTone.help + '\n' + window.MarianaToneProcedures.help;
      const request = ++toneRequest, before = generation;
      let rendered;
      if (bank) {
        const hz = Number(args[2] ?? 220), name = args[1];
        const file = new File([window.MarianaSoundbank.render(name, hz)], name + '.wav', {type:'audio/wav'});
        rendered = {file, title:name + ' · ' + hz + ' Hz'};
      } else if (window.MarianaToneProcedures.families.includes(args[0].toLowerCase())) {
        const plan = await window.MarianaToneProcedures.plan(args);
        if (typeof plan === 'string') return plan;
        rendered = await window.MarianaToneProcedures.render(plan, () => request === toneRequest && before === generation);
      } else {
        rendered = await window.MarianaTone.render(args);
      }
      const {file,title} = rendered;
      if (request !== toneRequest || before !== generation) return 'A newer selection took precedence.';
      const key = id();
      const stored = await storedFile('put', key, file);
      if (request !== toneRequest || before !== generation) {
        if (stored) await storedFile('delete', key);
        return 'A newer selection took precedence.';
      }
      if (!stored) memoryFiles.set(key, file);
      const item = {id:key,title,by:'Tone generator',marks:[],pos:0};
      queue.push(item); persist(); await select(item,true);
      return stored ? title : title + ' (this session only)';
    }
    case 'fx': return effectStudio.command(args);
    case 'dj': return djStudio.command(args);
    case 'speech': return micStudio?.command(args) || 'Microphone studio unavailable.';
    case 'clip': return clipStudio.command(args);
    case 'voice': window.MarianaVoice.open(); return 'Choose or create a meeting link in Voice room.';
    case 'files': el('files').click(); return 'Select media files to import.';
    case 'native':
      workspace.open('settings');
      el('native-link-title').parentElement.open = true;
      el('native-invitation-url').focus();
      return 'Run web session at the Mariana prompt and paste its invitation here.';
    case 'library': {
      const action = args[0]?.toLowerCase();
      if (!action) { el('library-query').focus(); return 'Local library opened.'; }
      if (action === 'list' || action === 'search') {
        const query = args.slice(1).join(' ');
        el('library-query').value = query;
        el('library-kind').value = 'all';
        workspace.render();
        return library.view(query).slice(0,40).map(({item,number}) => number + '. ' + item.title).join('\n') ||
          'No matching local media.';
      }
      const index = /^\d+$/.test(args[1] || '') ? Number(args[1]) : 0;
      const item = library.rows[index-1];
      if (['play','queue'].includes(action) && args.length === 2 && item) {
        await useLibraryItem(item, action === 'play'); break;
      }
      return 'Use library, library list, library search TEXT, library play NUMBER, or library queue NUMBER.';
    }
    case 'add': case 'feed': return addLink(arg, cmd.toLowerCase()==='feed');
    case 'queue': return queue.map((x,i)=>(i+1)+'. '+x.title).join('\n') || 'Queue empty.';
    case 'play': {
      const flags = args.filter(token => /^--(?:video|audio|auto)$/.test(token));
      const requested = args.filter(token => !flags.includes(token));
      if (flags.length > 1 || requested.length > 1) throw Error('Use play [queue number|current] [--audio|--video|--auto].');
      const mode = flags[0]?.slice(2) || 'auto';
      if (!requested.length && !flags.length) { await play(); break; }
      if (!requested.length || requested[0].toLowerCase() === 'current') {
        if (!current) return 'Choose a queue item first.';
        if (!flags.length) { await play(); break; }
        return picture?.command([mode === 'audio' ? 'close' : 'open'], audio === localPicture && (audio.readyState === 0 || audio.videoWidth > 0))
          ?? 'Picture controls are unavailable.';
      }
      const item = queue[Number(requested[0]) - 1];
      if (!item) return 'Use play with a queue number.';
      await select(item, true, mode);
      break;
    }
    case 'pause': audio.pause(); break;
    case 'stop': audio.pause(); if (Number.isFinite(audio.duration)) seek(0); rememberPosition(); break;
    case 'next': await move(1); break;
    case 'previous': await move(-1); break;
    case 'seek': if (!arg || !Number.isFinite(Number(arg))) return 'Use seek SECONDS.'; seek(Number(arg)); break;
    case 'speed': if (![...el('rate').options].some(o => o.value===arg)) return 'Choose an available playback speed.'; el('rate').value=arg; el('rate').onchange(); break;
    case 'bookmark': el('bookmark').click(); break;
    case 'theme': if (!arg || !applyTheme(arg.toLowerCase())) return Object.keys(window.MARIANA_THEMES).join(', '); break;
    case 'console': case 'flow': mode(cmd.toLowerCase()); break;
    default: return 'Unknown browser command. Type help, or run web session in native Mariana to use its full command catalog.';
  }
}
const commandInput = globalThis.MarianaCommandInput.mount({
  input:el('cmd'), list:el('cmd-suggestions'), status:el('cmd-announcement'), historyButton:el('cmd-history'),
  suggest:({line,cursor,correctionsOnly}) => globalThis.MarianaCommandMatch.suggest(line,cursor,globalThis.MarianaPortableGrammar,{
    correctionsOnly, dynamic:(tokens,prefix) => globalThis.MarianaPortableValues.suggest(tokens,prefix,{queue,current,el,themes:window.MARIANA_THEMES,library:library.rows})
  })
});
function showCommands(open) {
  document.body.dataset.commandOpen=String(open); el('flow-command').setAttribute('aria-expanded',String(open));
  if (open) { el('cmd').focus(); el('cmd').scrollIntoView?.({block:'nearest'}); }
  else { commandInput.dismiss(); el('flow-command').focus(); }
}
el('flow-command').onclick = () => showCommands(document.body.dataset.commandOpen!=='true');
document.addEventListener('keydown',event => {
  if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase()==='k') {
    event.preventDefault();
    if (document.body.dataset.mode==='flow') showCommands(true); else el('cmd').focus();
  } else if (event.key==='Escape' && document.body.dataset.mode==='flow' && document.body.dataset.commandOpen==='true') showCommands(false);
});
el('command').onsubmit = async event => {
  event.preventDefault();
  const input=el('cmd'), original=input.value, text=original.trim();
  if (!text || await commandInput.review() || input.value!==original) return;
  try { globalThis.MarianaCommandMatch.parse(text); }
  catch (error) { transcript(error.message); input.focus(); return; }
  commandInput.remember(text); input.value=''; transcript('› '+text);
  try { const result=await command(text); if (result) transcript(result); } catch(error) { transcript(error.message); }
};
applyTheme(window.MARIANA_THEMES[saved.theme] ? saved.theme : Object.keys(window.MARIANA_THEMES)[0]);
const launchView = new URLSearchParams(location.search).get('view');
mode(launchView === 'voice' ? 'flow' : ['console', 'flow'].includes(launchView) ? launchView : saved.mode === 'flow' ? 'flow' : 'console');
if (launchView === 'voice') { workspace.open('rooms'); window.MarianaVoice.open(); }
el('clip-open').addEventListener('click', () => workspace.open('studio'), {capture:true});
select(queue.find(item => item.id === saved.selected) || queue[0] || null, false);
if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol) && location.hostname !== 'app.mariana.invalid')
  navigator.serviceWorker.register('./sw.js').catch(() => status('Offline launch unavailable in this browser.'));

window.MarianaJamTransport = {
  state: () => current && {title:current.title, seconds:audio.currentTime, paused:audio.paused},
  async apply(cue) {
    const selected = current;
    if (!selected || selected.title !== cue.title) throw Error('Load the matching track first: ' + cue.title);
    if (!Number.isFinite(audio.duration) || cue.seconds > audio.duration)
      throw Error('The loaded track cannot seek to this position.');
    if (cue.action === 'pause') audio.pause();
    seek(cue.seconds);
    if (cue.action === 'play' && current === selected && audio.paused) await audio.play();
  },
};

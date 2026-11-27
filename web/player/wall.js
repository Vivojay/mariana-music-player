'use strict';

(() => {
  const FORMAT = 'mariana.wall.v1';
  const MAX_BYTES = 8 * 1024 * 1024;
  const MAX_POSTS = 2000;
  function text(value, limit, optional = false) {
    if (typeof value !== 'string') throw Error('Expected plain text.');
    const clean = value.trim();
    if ((!optional && !clean) || [...clean].length > limit || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(clean)) {
      throw Error('Use plain text, up to ' + limit + ' characters.');
    }
    return clean;
  }
  function uuid(value) {
    if (typeof value !== 'string' || !/^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(value)) throw Error('Invalid wall or post ID.');
    return value.toLowerCase();
  }
  function createID() {
    if (crypto.randomUUID) return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('');
    return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
  }
  function post(raw) {
    const {id, kind, artist, title, body, stars, created} = raw || {};
    if (!['track','album','review','take','listen'].includes(kind)) throw Error('Unsupported post type.');
    if (!Number.isInteger(stars) || (kind === 'review' ? stars < 1 || stars > 5 : stars !== 0)) throw Error('Reviews use one to five stars.');
    if (!Number.isInteger(created) || created < 0 || created > 253402300799) throw Error('Invalid post time.');
    return {id:uuid(id),kind,artist:text(artist,160),title:text(title,240,kind === 'take'),
      body:text(body,600,!['review','take'].includes(kind)),stars,created};
  }
  function snapshot(raw) {
    if (raw?.format !== FORMAT || !Array.isArray(raw.posts) || raw.posts.length > MAX_POSTS) throw Error('Expected a Mariana wall with up to 2,000 posts.');
    const posts = raw.posts.map(post);
    if (new Set(posts.map(p => p.id)).size !== posts.length) throw Error('Duplicate post ID.');
    return {format:FORMAT,id:uuid(raw.id),name:text(raw.name,80),posts};
  }
  function encode(wall) {
    const json = JSON.stringify(snapshot(wall), null, 2);
    if (new TextEncoder().encode(json).length > MAX_BYTES) throw Error('Wall exceeds 8 MiB.');
    return json;
  }
  function decode(json) {
    if (typeof json !== 'string' || json.length > MAX_BYTES) throw Error('Wall exceeds 8 MiB.');
    if (new TextEncoder().encode(json).length > MAX_BYTES) throw Error('Wall exceeds 8 MiB.');
    return snapshot(JSON.parse(json));
  }
  // These lines are drawn locally and double as accessible copy for the image.
  function cardText(entry, displayName) {
    return [entry.kind.toUpperCase() + ' · ' + displayName, entry.title, entry.artist,
      entry.stars ? entry.stars + ' / 5 stars' : '', entry.body].filter(Boolean).join('\n');
  }
  function wrapCardText(context, text, width) {
    const lines = [];
    let line = '';
    for (const word of text.split(/\s+/u).filter(Boolean)) {
      const next = line ? line + ' ' + word : word;
      if (context.measureText(next).width <= width) { line = next; continue; }
      if (line) { lines.push(line); line = ''; }
      const glyphs = typeof Intl.Segmenter === 'function'
        ? Array.from(new Intl.Segmenter(undefined,{granularity:'grapheme'}).segment(word), s => s.segment)
        : Array.from(word);
      for (const char of glyphs) {
        if (line && context.measureText(line + char).width > width) { lines.push(line); line = ''; }
        line += char;
      }
    }
    if (line) lines.push(line);
    return lines;
  }
  function drawCard(canvas, source, name, colors) {
    const entry = post(source), owner = text(name,80);
    const w = 1080, margin = 70, available = w - margin * 2;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw Error('Card drawing is unavailable on this device.');
    const title = entry.title || entry.artist;
    const blocks = [
      [title, 'bold 68px Georgia, serif', 80, colors.text],
      [entry.title ? entry.artist : '', '42px system-ui, sans-serif', 54, colors.accent],
      [entry.stars ? entry.stars + ' / 5 stars' : '', 'bold 36px system-ui, sans-serif', 50, colors.accent],
      [entry.body, '36px system-ui, sans-serif', 54, colors.text],
    ].filter(([copy]) => copy).map(([copy,font,leading,color]) => {
      ctx.font = font; return {font,leading,color,lines:wrapCardText(ctx,copy,available)};
    });
    ctx.font = 'bold 29px system-ui, sans-serif';
    const credit = wrapCardText(ctx,owner,available);
    const contentHeight = blocks.reduce((n,b) => n+b.leading*b.lines.length+18,0);
    canvas.width = w; canvas.height = Math.max(1080,390+contentHeight+credit.length*40+140);
    ctx.fillStyle = colors.background; ctx.fillRect(0,0,w,canvas.height);
    ctx.save(); ctx.beginPath(); ctx.rect(0,0,w,300); ctx.clip();
    const wash = ctx.createLinearGradient(0,300,w,0);
    wash.addColorStop(0,colors.panel); wash.addColorStop(1,colors.glow);
    ctx.fillStyle = wash; ctx.fillRect(0,0,w,300);
    const cx=829, cy=116;
    ctx.fillStyle=colors.background; ctx.beginPath(); ctx.arc(cx,cy,287,0,Math.PI*2); ctx.fill();
    ctx.lineWidth=2; ctx.strokeStyle=colors.accent; ctx.globalAlpha=.42;
    for (let r=82;r<284;r+=11) { ctx.beginPath();ctx.arc(cx,cy,r,0,Math.PI*2);ctx.stroke(); }
    ctx.globalAlpha=1;ctx.fillStyle=colors.accent;ctx.beginPath();ctx.arc(cx,cy,70,0,Math.PI*2);ctx.fill();
    ctx.fillStyle=colors.background;ctx.beginPath();ctx.arc(cx,cy,8,0,Math.PI*2);ctx.fill();ctx.restore();
    ctx.fillStyle=colors.background;ctx.fillRect(0,0,374,80);
    ctx.fillStyle=colors.text;ctx.font='bold 35px system-ui, sans-serif';ctx.fillText('Mariana',margin,52);
    ctx.fillStyle=colors.accent;ctx.font='bold 26px monospace';ctx.fillText(entry.kind.toUpperCase(),margin,365);
    let y=390;
    for (const block of blocks) {
      ctx.fillStyle=block.color;ctx.font=block.font;
      for (const line of block.lines) {y+=block.leading;ctx.fillText(line,margin,y);}
      y+=18;
    }
    const footer=canvas.height-44-credit.length*40;
    ctx.fillStyle=colors.accent;ctx.fillRect(margin,footer-60,available,2);
    ctx.fillStyle=colors.muted;ctx.font='24px system-ui, sans-serif';ctx.fillText('From the music wall of',margin,footer-18);
    ctx.fillStyle=colors.text;ctx.font='bold 29px system-ui, sans-serif';
    credit.forEach((line,index) => ctx.fillText(line,margin,footer+(index+1)*40));
    return cardText(entry,owner);
  }
  if (typeof document === 'undefined') {
    globalThis.MarianaWall = {post, snapshot, encode, decode, cardText, drawCard, wrapCardText};
    return;
  }

  const element = id => document.getElementById(id);
  const view = element('wall-view'), profile = element('wall-profile'), compose = element('wall-post');
  const info = element('wall-status'), list = element('wall-posts'), field = element('wall-json');
  const picker = element('wall-file'), more = element('wall-more'), download = element('wall-download');
  let database, limit = 24, generation = 0, objectURL;
  const store = 'walls';

  // Read and write under one IndexedDB transaction so two open tabs can append safely.
  function record(key, change) {
    return new Promise((resolve, reject) => {
      const tx = database.transaction(store, change ? 'readwrite' : 'readonly');
      const bucket = tx.objectStore(store);
      const req = bucket.get(key);
      let result, error;
      req.onsuccess = () => {
        try {
          result = change ? change(req.result) : req.result;
          if (change) bucket.put(result, key);
        } catch (failure) { error = failure; tx.abort(); }
      };
      tx.oncomplete = () => resolve(result);
      tx.onerror = tx.onabort = () => reject(error || tx.error || Error('Could not save this wall.'));
    });
  }
  function profiles() {
    return new Promise((resolve, reject) => {
      const tx = database.transaction(store);
      const rows = [], request = tx.objectStore(store).openCursor();
      request.onsuccess = () => {
        const cursor = request.result;
        if (cursor) { rows.push({key:cursor.key,name:cursor.value.name}); cursor.continue(); }
      };
      tx.oncomplete = () => resolve(rows);
      tx.onabort = tx.onerror = () => reject(tx.error || Error('Could not list walls.'));
    });
  }
  function make(tag, string) {
    const node = document.createElement(tag);
    node.textContent = string;
    return node;
  }
  function run(fn) {
    return async event => {
      event.preventDefault();
      try { if (!database) throw Error('Local wall storage is unavailable.'); await fn(event); }
      catch (err) { info.textContent = err.message || 'Could not update the wall.'; }
    };
  }
  async function render(selected = view.value || 'self') {
    const seq = ++generation;
    const [rows,wall] = await Promise.all([profiles(),record(selected)]);
    if (seq !== generation || !wall) return;
    rows.sort((a,b) => (b.key === 'self') - (a.key === 'self') || a.name.localeCompare(b.name));
    view.replaceChildren(...rows.map(row => new Option(row.key === 'self' ? 'My wall' : row.name,row.key)));
    view.value = selected;
    const own = selected === 'self';
    profile.hidden = !own;
    element('wall-compose').hidden = !own;
    if (own) profile.elements.namedItem('name').value = wall.name;
    element('wall-empty').textContent = wall.posts.length ? '' : own ? 'Add a track, album, review or hot take.' : 'This wall is empty.';
    list.replaceChildren();
    const sorted = wall.posts.slice().reverse().sort((a,b) => b.created - a.created);
    for (const entry of sorted.slice(0,limit)) {
      const li = document.createElement('li'), card = document.createElement('article');
      const date = new Date(entry.created * 1000).toLocaleDateString();
      card.append(make('small', entry.kind + ' · ' + date), make('h3', entry.title || entry.artist));
      if (entry.title) card.append(make('p', entry.artist));
      if (entry.stars) card.append(make('p', entry.stars + ' / 5 stars'));
      if (entry.body) card.append(make('p', entry.body));
      const cardButton = make('button','Create PNG card'); cardButton.type = 'button';
      cardButton.setAttribute('aria-label','Create PNG card for ' + (entry.title || entry.artist));
      cardButton.onclick = run(() => prepareCard(entry,wall.name));
      card.append(cardButton);
      if (own) {
        const remove = make('button','Remove'); remove.type = 'button';
        remove.setAttribute('aria-label', 'Remove ' + (entry.title || entry.artist));
        remove.onclick = run(async () => {
          await record('self', existing => ({...existing,posts:existing.posts.filter(p => p.id !== entry.id)}));
          await render('self'); info.textContent = 'Post removed.';
        });
        card.append(remove);
      }
      li.append(card); list.append(li);
    }
    more.hidden = sorted.length <= limit;
  }
  view.onchange = run(async () => { limit = 24; await render(view.value); });
  more.onclick = run(async () => { limit += 24; await render(); });
  function fields() {
    const kind = compose.elements.kind.value;
    for (const [name,visible] of [['body',kind === 'take' || kind === 'review'],['title',kind !== 'take'],['stars',kind === 'review']]) {
      const input = compose.elements.namedItem(name);
      input.closest('label').hidden = !visible; input.disabled = !visible; input.required = visible;
    }
  }
  compose.elements.kind.onchange = fields; fields();
  profile.onsubmit = run(async () => {
    const name = text(profile.elements.namedItem('name').value,80);
    await record('self', existing => ({...existing,name}));
    await render('self'); info.textContent = 'Profile saved.';
  });
  compose.onsubmit = run(async () => {
    const values = new FormData(compose);
    const entry = post({id:createID(),kind:values.get('kind'),artist:values.get('artist'),title:values.get('title') || '',
      body:values.get('body') || '',stars:Number(values.get('stars') || 0),created:Math.floor(Date.now()/1000)});
    await record('self', existing => {
      if (existing.posts.length >= MAX_POSTS) throw Error('Remove a post before adding another.');
      return {...existing,posts:[...existing.posts,entry]};
    });
    compose.reset(); fields(); limit = 24; await render('self'); info.textContent = 'Added to your wall.';
  });
  async function importWall(json) {
    const wall = decode(json);
    if (wall.id === (await record('self')).id) throw Error('This snapshot is your own wall.');
    await record(wall.id, () => wall);
    field.value = ''; limit = 24; await render(wall.id);
    info.textContent = 'Imported ' + wall.name + ' · ' + wall.posts.length + ' posts.';
  }
  picker.onchange = run(async () => {
    const file = picker.files[0]; picker.value = '';
    if (!file) return;
    if (file.size > MAX_BYTES) throw Error('Wall exceeds 8 MiB.');
    await importWall(await file.text());
  });
  element('wall-import').onclick = run(() => importWall(field.value));
  const nativePhone = location.hostname === 'app.mariana.invalid' || window.MarianaNativeShell === 'ios';
  let cardFile, cardURL, cardGeneration = 0;
  const cardPanel = element('wall-card'), preview = element('wall-card-preview'), copy = element('wall-card-copy');
  const share = element('wall-card-share'), downloadCard = element('wall-card-download'), caption = element('wall-card-caption');
  async function prepareCard(entry, name) {
    const version = ++cardGeneration;
    const css = getComputedStyle(document.documentElement);
    const colors = Object.fromEntries(['background','panel','text','accent','glow','muted'].map(token =>
      [token,css.getPropertyValue('--' + token).trim()]));
    const canvas = document.createElement('canvas');
    const description = drawCard(canvas,entry,name,colors);
    const blob = await new Promise(resolve => canvas.toBlob(resolve,'image/png'));
    if (version !== cardGeneration) return;
    if (!blob) throw Error('PNG export is unavailable on this device.');
    if (cardURL) URL.revokeObjectURL(cardURL);
    cardURL = URL.createObjectURL(blob);
    cardFile = new File([blob],'mariana-' + entry.kind + '.png',{type:'image/png'});
    preview.src = cardURL; preview.alt = description; caption.value = description;
    downloadCard.href = cardURL; downloadCard.download = cardFile.name; downloadCard.hidden = nativePhone;
    try { share.hidden = !(navigator.share && navigator.canShare?.({files:[cardFile]})); }
    catch { share.hidden = true; }
    copy.hidden = !(navigator.clipboard?.write && typeof ClipboardItem !== 'undefined');
    cardPanel.hidden = false; element('wall-card-title').focus();
    info.textContent = 'PNG card ready. You can also select and copy its text.';
  }
  share.onclick = run(async () => {
    try { await navigator.share({files:[cardFile]}); info.textContent = 'Card shared.'; }
    catch (error) { if (error.name !== 'AbortError') throw error; info.textContent = 'Sharing cancelled.'; }
  });
  copy.onclick = run(async () => {
    try {
      await navigator.clipboard.write([new ClipboardItem({'image/png':cardFile})]);
      info.textContent = 'PNG copied.';
    } catch { caption.focus(); caption.select(); info.textContent = 'Image copy unavailable. Choose Copy to copy the selected card text.'; }
  });
  element('wall-card-text').onclick = run(async () => {
    caption.focus(); caption.select();
    try { await navigator.clipboard.writeText(caption.value); info.textContent = 'Card text copied.'; }
    catch { info.textContent = 'Choose Copy to copy the selected card text.'; }
  });
  element('wall-card-close').onclick = () => {
    ++cardGeneration; cardFile = null; if (cardURL) URL.revokeObjectURL(cardURL);
    cardURL = ''; preview.removeAttribute('src'); downloadCard.removeAttribute('href'); cardPanel.hidden = true;
    element('wall-title').focus();
  };
  const transfer = element('wall-transfer');
  let exportJSON, shareFile;
  transfer.onclick = run(async () => {
    if (!exportJSON) return;
    if (shareFile) {
      try {
        await navigator.share({files:[shareFile]});
        info.textContent = 'Wall shared.';
        return;
      } catch (error) {
        if (error.name === 'AbortError') { info.textContent = 'Sharing cancelled.'; return; }
      }
    }
    field.value = exportJSON; field.focus(); field.select();
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(exportJSON);
      else if (!document.execCommand('copy')) throw Error('Clipboard unavailable.');
      info.textContent = 'Wall JSON copied.';
    } catch { info.textContent = 'Choose Copy from the selected text menu to copy your wall.'; }
  });
  element('wall-export').onclick = run(async () => {
    const json = encode(await record('self'));
    field.value = json; field.focus(); field.select();
    if (objectURL) URL.revokeObjectURL(objectURL);
    if (nativePhone) {
      exportJSON = json;
      const file = new File([json], 'mariana-wall.json', {type:'application/json'});
      try { shareFile = navigator.share && navigator.canShare?.({files:[file]}) ? file : null; }
      catch { shareFile = null; }
      transfer.textContent = shareFile ? 'Share JSON' : 'Copy JSON'; transfer.hidden = false;
      info.textContent = 'Your wall snapshot is ready.';
      return;
    }
    objectURL = URL.createObjectURL(new Blob([json],{type:'application/json'}));
    download.href = objectURL; download.hidden = false;
    info.textContent = 'Your wall is ready to copy or download.';
  });
  try {
    const open = indexedDB.open(window.MarianaProfiles?.key('mariana-local-walls') ?? 'mariana-local-walls',1);
    open.onupgradeneeded = () => open.result.createObjectStore(store);
    open.onsuccess = async () => {
      database = open.result;
      try {
        await record('self', value => value || {format:FORMAT,id:createID(),name:'Listener',posts:[]});
        await render();
      } catch (err) { info.textContent = err.message; }
    };
    open.onerror = open.onblocked = () => { info.textContent = 'Local wall storage is unavailable.'; };
  } catch { info.textContent = 'Local wall storage is unavailable.'; }
})();

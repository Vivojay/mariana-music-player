'use strict';

(() => {
  const LIMIT = 2 * 1024 * 1024;
  const THRESHOLD = 0.9;
  const usage = 'karaoke status | start | stop | current | singers | part NAME | previous | next | import | compare | export | invite [SINGER] | open | accept | vocals on|off|0|25|50|75|100 | clear | demo';
  function check(ok, reason) { if (!ok) throw Error(reason); }
  const uint = value => Number.isSafeInteger(value) && value >= 0 && value <= 86400000;
  const score = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
  const label = (value, limit) => typeof value === 'string' && value.trim() &&
    [...value].length <= limit && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value);
  const percent = value => Math.floor(value * 1000 + 1e-9) / 10 + '%';

  function validate(sheet) {
    check(sheet?.schema === 'mariana.karaoke.v1', 'Choose a Mariana karaoke v1 timing sheet (.json).');
    check(typeof sheet.media_sha256 === 'string' && /^[a-f0-9]{64}$/.test(sheet.media_sha256), 'Missing or invalid media SHA-256.');
    check(uint(sheet.duration_ms) && sheet.duration_ms > 0, 'Invalid recording duration.');
    check(label(sheet.source, 180) && score(sheet.confidence), 'The sheet must identify its timing source and whole-recording confidence.');
    check(Array.isArray(sheet.segments) && sheet.segments.length && sheet.segments.length <= 10000, 'Invalid number of lyric segments.');
    let cursor = 0, wordCount = 0, confidence = sheet.confidence;
    const singers = new Set();
    for (const segment of sheet.segments) {
      check(segment && segment.start_ms === cursor && uint(segment.end_ms) &&
        segment.end_ms > cursor && segment.end_ms <= sheet.duration_ms, 'Timing must cover the full recording without gaps or overlapping segments.');
      check(Array.isArray(segment.voices) && segment.voices.length <= 16, 'Invalid singer lanes.');
      const local = new Set();
      for (const lane of segment.voices) {
        check(lane && label(lane.singer, 80) && !local.has(lane.singer.trim()), 'Each part needs a distinct singer name.');
        const singer = lane.singer.trim();
        local.add(singer); singers.add(singer);
        check(Array.isArray(lane.words) && lane.words.length && lane.words.length <= 512, 'Each singer part needs one or more timed words.');
        let last = segment.start_ms;
        for (const word of lane.words) {
          check(word && label(word.text, 128) && score(word.confidence), 'Each word needs readable text and alignment confidence.');
          check(uint(word.start_ms) && uint(word.end_ms) && word.start_ms >= last && word.end_ms > word.start_ms &&
            word.end_ms <= segment.end_ms, 'Word times overlap or fall outside their singer part.');
          last = word.end_ms; confidence = Math.min(confidence, word.confidence); wordCount++;
        }
      }
      cursor = segment.end_ms;
    }
    check(cursor === sheet.duration_ms && wordCount > 0, 'The sheet needs complete coverage and at least one timed word.');
    return {sheet, confidence, singers:[...singers]};
  }

  function locate(segments, ms) {
    if (!Number.isFinite(ms)) return -1;
    let low = 0, high = segments.length - 1;
    while (low <= high) {
      const index = (low + high) >>> 1, s = segments[index];
      if (ms < s.start_ms) high = index - 1;
      else if (ms >= s.end_ms) low = index + 1;
      else return index;
    }
    return -1;
  }

  function availability(verified, duration) {
    if (verified.confidence < THRESHOLD)
      return 'Unavailable · timing confidence ' + percent(verified.confidence) + ' is below the required 90%.';
    if (!Number.isFinite(duration) || duration <= 0) return 'Waiting for a measurable recording duration.';
    if (Math.abs(Math.round(duration * 1000) - verified.sheet.duration_ms) > 250)
      return 'Unavailable · track duration differs from this timing sheet.';
    return '';
  }

  async function fingerprint(file, signal) {
    if (signal.aborted) throw Error('Cancelled.');
    if (file.size <= 16 * 1024 * 1024 && globalThis.crypto?.subtle) {
      const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
      return [...new Uint8Array(digest)].map(v => v.toString(16).padStart(2, '0')).join('');
    }
    check(typeof Worker === 'function', 'This browser cannot verify this recording. Try a browser with Web Worker support.');
    return new Promise((resolve, reject) => {
      const worker = new Worker('./karaoke-hash.js');
      const finish = (fn, value) => { signal.removeEventListener('abort', abort); worker.terminate(); fn(value); };
      const abort = () => finish(reject, Error('Cancelled.'));
      signal.addEventListener('abort', abort, {once:true});
      worker.onerror = () => finish(reject, Error('Could not verify the recording in this browser.'));
      worker.onmessage = ({data}) => data.error ? finish(reject, Error(data.error)) : finish(resolve, data.value);
      worker.postMessage(file);
    });
  }

  let demoRequest;
  async function demoData() {
    if (!window.MARIANA_PRACTICE_DUET) {
      if (!demoRequest) demoRequest = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = './practice-duet.js';
        script.onload = resolve;
        script.onerror = () => { script.remove(); demoRequest = null; reject(Error('The bundled practice duet is unavailable.')); };
        document.head.append(script);
      });
      await demoRequest;
    }
    const {audio, sheet} = window.MARIANA_PRACTICE_DUET;
    const bytes = Uint8Array.from(atob(audio), ch => ch.charCodeAt(0));
    return {file:new Blob([bytes], {type:'audio/wav'}), sheet};
  }

  function mount({el, active, media, getFile, store, seek, playDemo, replaceMix}) {
    const note = el('karaoke-status'), message = el('karaoke-feedback'), stage = el('karaoke-stage');
    const lines = el('karaoke-lines'), part = el('karaoke-part'), controls = el('karaoke-controls');
    const next = el('karaoke-next'), back = el('karaoke-prev'), toggle = el('karaoke-toggle'), pick = el('karaoke-file');
    let owner = null, verified = null, request, running = false, homeText = '', activeIndex = -2, wordNodes = [];
    let partName = null, frame, lastStatus = '', demoIntent = false;
    const sheets = new Map();
    const stemPicker = el('karaoke-stem'), level = el('karaoke-vocal-level');
    let stems = null, mixJob, appliedLevel = 1, pendingMix = false;
    function resetMix() {
      mixJob?.abort(); stems = null; appliedLevel = 1; pendingMix = false;
      level.value = '1'; level.disabled = true;
    }
    async function applyLevel(value) {
      const item = owner;
      if (!stems || !item) return 'Choose a matching isolated vocal stem first.';
      if (value === appliedLevel && !pendingMix) return 'Original vocal gain is already set.';
      mixJob?.abort(); const job = mixJob = new AbortController(); pendingMix = true;
      try {
        message.textContent = 'Preparing vocal mix…';
        const file = value === 1 ? await getFile(item) : await window.MarianaKaraokeMix.render(stems, value, job.signal);
        if (job.signal.aborted || item !== active()) return '';
        await replaceMix(item, file);
        if (job.signal.aborted || item !== active()) return '';
        appliedLevel = value; level.value = String(value);
        return message.textContent = 'Original vocals at ' + Math.round(100*value) + '%.';
      } catch (err) {
        if (!job.signal.aborted) { level.value = String(appliedLevel); message.textContent = err.message; }
        return '';
      } finally { if (!job.signal.aborted) pendingMix = false; }
    }
    level.onchange = () => { void applyLevel(Number(level.value)); };
    stemPicker.onchange = async () => {
      const supplied = stemPicker.files?.[0]; stemPicker.value = '';
      if (!supplied || !owner || owner.url) return;
      mixJob?.abort(); const job = mixJob = new AbortController(), item = owner;
      try {
        message.textContent = 'Checking the isolated vocal against this mix…';
        const pair = await window.MarianaKaraokeMix.prepare(await getFile(item), supplied, media().duration, job.signal);
        if (job.signal.aborted || item !== active()) return;
        if (appliedLevel !== 1) await replaceMix(item, await getFile(item));
        if (job.signal.aborted || item !== active()) return;
        stems = pair; appliedLevel = 1; pendingMix = false; level.value = '1'; level.disabled = false;
        message.textContent = 'Vocal stem ready. Choose a vocal level.';
      } catch (err) { if (!job.signal.aborted) message.textContent = err.message; }
    };
    const book = el('karaoke-book'), bookLines = el('karaoke-book-lines'), exportLink = el('karaoke-export');
    let plainLyrics = [];
    const plainByItem = new Map();
    let bookPage = 0, bookSegments = [], sheetURL = '';
    function drawBook() {
      bookLines.replaceChildren();
      if (!book.open || !bookSegments.length) return;
      const size = 16;
      for (const segment of bookSegments.slice(bookPage * size, (bookPage + 1) * size)) {
        const li = document.createElement('li');
        for (const lane of segment.voices) {
          const row = document.createElement('p'), by = document.createElement('strong');
          by.textContent = lane.singer.trim() + ' · '; row.dir = 'auto';
          row.append(by, document.createTextNode(lane.words.map(w => w.text.trim()).join(' '))); li.append(row);
        }
        bookLines.append(li);
      }
      el('karaoke-book-prev').disabled = bookPage === 0;
      el('karaoke-book-next').disabled = (bookPage + 1) * size >= bookSegments.length;
    }
    function setBook(data) {
      if (sheetURL) URL.revokeObjectURL(sheetURL);
      sheetURL = ''; exportLink.removeAttribute('href'); exportLink.hidden = !data;
      bookPage = 0; bookSegments = plainLyrics.length ? plainLyrics : data?.sheet.segments.filter(s => s.voices.length) || [];
      book.hidden = !bookSegments.length;
      if (data) {
        sheetURL = URL.createObjectURL(new Blob([JSON.stringify(data.sheet)], {type:'application/json'}));
        exportLink.href = sheetURL;
      } else if (book.hidden) book.open = false;
      drawBook();
    }
    book.ontoggle = drawBook;
    el('karaoke-book-prev').onclick = () => { if (bookPage > 0) bookPage--; drawBook(); };
    el('karaoke-book-next').onclick = () => { if ((bookPage + 1) * 16 < bookSegments.length) bookPage++; drawBook(); };
    let verifiedFile, verifiedHash;
    const setText = (node, text) => { if (node.textContent !== text) node.textContent = text; };
    function cancel() { request?.abort(); request = new AbortController(); return request; }
    function activeLyrics() {
      return verified.sheet.segments.map((s, i) => s.voices.some(v => partName === null || v.singer.trim() === partName) ? i : -1).filter(i => i >= 0);
    }
    let lyricIndices = [];
    function now() { return Math.floor((media().currentTime || 0) * 1000 + .5); }
    function seekLine(forward) {
      if (!enabled()) return;
      const ms = now(), index = lyricIndices[forward ? 'find' : 'findLast'](i =>
        forward ? verified.sheet.segments[i].start_ms > ms : verified.sheet.segments[i].start_ms < ms);
      if (index !== undefined) seek(verified.sheet.segments[index].start_ms / 1000);
    }
    function enabled() { return Boolean(owner && owner === active() && verified && !availability(verified, media().duration)); }
    function nextLyric(index) {
      // Binary search avoids rescanning a long score for each progress frame.
      let lo = 0, hi = lyricIndices.length;
      while (lo < hi) { const mid = (lo + hi) >>> 1; if (lyricIndices[mid] <= index) lo = mid + 1; else hi = mid; }
      return verified.sheet.segments[lyricIndices[lo]];
    }
    function buildLines(index) {
      activeIndex = index; wordNodes = []; lines.replaceChildren();
      const segment = verified.sheet.segments[index];
      const lanes = segment?.voices.filter(v => partName === null || v.singer.trim() === partName) || [];
      let spoken = '';
      if (!lanes.length) {
        const hint = !segment ? 'End of recording' : segment.voices.length ? 'Listening to the other part' : 'Instrumental';
        const p = document.createElement('p'); p.className = 'karaoke-rest'; p.textContent = hint; lines.append(p); spoken = hint;
      }
      for (const lane of lanes) {
        const row = document.createElement('div'); row.className = 'karaoke-lane';
        row.dataset.voice = verified.singers.indexOf(lane.singer.trim()) % 2 === 0 ? 'first' : 'second';
        const badge = document.createElement('span'); badge.className = 'karaoke-singer'; badge.textContent = lane.singer.trim();
        const line = document.createElement('p'); line.dir = 'auto';
        for (const [i, word] of lane.words.entries()) {
          if (i) line.append(document.createTextNode(' '));
          const span = document.createElement('span'); span.className = 'karaoke-word'; span.textContent = word.text.trim();
          wordNodes.push({span,word}); line.append(span);
        }
        spoken += (spoken ? '. ' : '') + badge.textContent + ': ' + line.textContent;
        row.append(badge, line); lines.append(row);
      }
      setText(el('karaoke-announce'), spoken);
      const following = segment ? nextLyric(index) : null;
      const preview = following?.voices.filter(v => partName === null || v.singer.trim() === partName)
        .map(v => v.singer.trim() + ' · ' + v.words.map(w => w.text.trim()).join(' ')).join(' / ');
      setText(el('karaoke-upcoming'), preview ? 'Up next   ' + preview : '');
    }
    const invites = window.MarianaKaraokeInvite.mount({el, hash:fingerprint,
      context:() => ({verified,ready:enabled(),part:partName,ms:now()}),
      apply:(singer,ms) => { setPart(singer); seek(ms/1000); }, notify:text => { message.textContent = text; }});
    function tick() {
      const available = enabled(); invites.refresh();
      const text = verified ? availability(verified, media().duration) ||
        'Available · ' + percent(verified.confidence) + ' timing confidence · ' + verified.sheet.source.trim() : homeText;
      if (text !== lastStatus) { setText(note, text); lastStatus = text; }
      controls.hidden = !available; stage.hidden = !(available && running);
      if (!available || !running) return;
      const ms = now(), index = locate(verified.sheet.segments, ms);
      if (index !== activeIndex) buildLines(index);
      for (const {span,word} of wordNodes) {
        const state = ms < word.start_ms ? 'waiting' : ms >= word.end_ms ? 'sung' : 'singing';
        if (span.dataset.state !== state) span.dataset.state = state;
        if (state === 'singing')
          span.style.setProperty('--sung', (100 * (ms - word.start_ms) / (word.end_ms - word.start_ms)).toFixed(1) + '%');
      }
      if (!media().paused && !document.hidden && !frame && typeof requestAnimationFrame === 'function')
        frame = requestAnimationFrame(() => { frame = null; tick(); });
    }
    function setRunning(value) {
      if (value && !enabled()) return false;
      running = value; toggle.textContent = running ? 'Stop karaoke' : 'Start karaoke';
      toggle.setAttribute('aria-pressed', String(running)); tick(); return true;
    }
    function setPart(name) {
      if (name !== null && !verified?.singers.includes(name)) return false;
      partName = name; part.selectedIndex = name === null ? 0 : verified.singers.indexOf(name) + 1;
      if (verified) lyricIndices = activeLyrics();
      activeIndex = -2; tick(); return true;
    }
    async function mediaHash(item, job) {
      const file = await getFile(item);
      if (job.signal.aborted) return false;
      check(file && typeof file.arrayBuffer === 'function', 'Re-add the local recording to verify this timing sheet.');
      if (verifiedFile !== file) {
        const hash = await fingerprint(file, job.signal);
        if (job.signal.aborted) return false;
        verifiedFile = file; verifiedHash = hash;
      }
      return verifiedHash;
    }
    async function bind(sheet, item, job) {
      const data = validate(sheet), hash = await mediaHash(item, job);
      if (job.signal.aborted) return false;
      check(hash === data.sheet.media_sha256, 'Unavailable · this timing sheet belongs to a different recording.');
      invites.invalidate(); verified = data; setBook(data);
      part.replaceChildren(new Option('All singers', 'all'), ...data.singers.map((s, i) => new Option(s, String(i))));
      setPart(null); return true;
    }
    async function change(item) {
      const job = cancel(); resetMix(); invites.invalidate(); owner = item; verifiedFile = null; verifiedHash = null;
      if (item?.id !== 'mariana-practice-duet-v1') demoIntent = false;
      verified = null; plainLyrics = []; setBook(null); activeIndex = -2; wordNodes = []; lines.replaceChildren(); message.textContent = '';
      setText(el('karaoke-announce'), ''); setText(el('karaoke-upcoming'), '');
      homeText = !item ? 'Choose a local recording or try the practice duet.' : item.url ?
        'Unavailable · online streams have no verified audio-file identity. Add the local recording for karaoke.' :
        'Unavailable · import a timing sheet for this recording (90% minimum confidence).';
      pick.disabled = !item || Boolean(item.url);
      el('karaoke-lyrics').disabled = !item; el('karaoke-ttml').disabled = stemPicker.disabled = pick.disabled;
      setRunning(false);
      if (!item) return;
      try {
        const plain = plainByItem.get(item.id) || await store('get', 'lyrics:' + item.id);
        if (job.signal.aborted) return;
        if (Array.isArray(plain)) { plainLyrics = plain; setBook(null); }
        if (pick.disabled) return;
        const sheet = sheets.get(item.id) || await store('get', 'karaoke:' + item.id);
        if (job.signal.aborted || !sheet) return;
        homeText = 'Verifying timing against this recording…'; tick();
        await bind(sheet, item, job);
        if (!job.signal.aborted && item.id === 'mariana-practice-duet-v1' && demoIntent) {
          // Metadata can arrive after the sheet, particularly on mobile.
          running = true; toggle.textContent = 'Stop karaoke'; toggle.setAttribute('aria-pressed', 'true'); demoIntent = false;
        }
      } catch (err) { if (!job.signal.aborted) homeText = err.message; }
      if (!job.signal.aborted) tick();
    }
    async function importFile(file, comparison = null) {
      if (!owner || owner.url || (!file && !comparison)) return;
      const job = cancel(), item = owner;
      try {
        let raw;
        if (comparison) {
          const digest = await mediaHash(item, job);
          if (job.signal.aborted) return;
          raw = await window.MarianaKaraokeTTML.compare(comparison, digest, Math.round(media().duration * 1000));
        } else {
          check(file.size <= LIMIT, 'Choose a timing sheet up to 2 MiB.');
          raw = JSON.parse((await file.text()).replace(/^\uFEFF/, ''));
        }
        if (job.signal.aborted) return;
        message.textContent = 'Verifying timing against this recording…';
        if (!(await bind(raw, item, job)) || job.signal.aborted) return;
        sheets.set(item.id, raw);
        const stored = await store('put', 'karaoke:' + item.id, raw);
        if (!job.signal.aborted) message.textContent = stored ? 'Timing sheet saved on this device.' : 'Timing sheet available for this session.';
      } catch (err) {
        if (!job.signal.aborted) {
          const reason = err instanceof SyntaxError ? 'This file is not valid karaoke JSON.' : err.message;
          message.textContent = reason + (verified ? ' The previous timing sheet is still loaded.' : '');
        }
      }
      if (!job.signal.aborted) tick();
    }
    async function demo() {
      const itemBeforeLoad = owner;
      try {
        const {file, sheet} = await demoData();
        if (owner !== itemBeforeLoad) return 'A newer selection took precedence.';
        const key = 'mariana-practice-duet-v1';
        sheets.set(key, sheet); demoIntent = true;
        await store('put', 'karaoke:' + key, sheet);
        if (owner !== itemBeforeLoad) { demoIntent = false; return 'A newer selection took precedence.'; }
        await playDemo(key, file); return 'Loaded the six-second Mariana practice duet.';
      } catch (err) { demoIntent = false; throw err; }
    }
    async function clear() {
      const item = owner;
      if (!item) return 'Choose a recording first.';
      cancel(); invites.invalidate(); sheets.delete(item.id); verified = null; setBook(null); setRunning(false);
      homeText = 'Unavailable · import a timing sheet for this recording (90% minimum confidence).'; tick();
      const removed = await store('delete', 'karaoke:' + item.id);
      if (owner === item) message.textContent = removed ? 'Timing sheet cleared.' : 'Cleared for this session. Device storage is unavailable.';
      return owner === item ? message.textContent : '';
    }

    const lyricFile = el('karaoke-lyrics');
    lyricFile.onchange = async () => {
      const file = lyricFile.files?.[0], item = owner; lyricFile.value = '';
      if (!file || !item) return;
      try {
        check(file.size <= LIMIT, 'Choose a TTML file up to 2 MiB.');
        const plain = window.MarianaKaraokeTTML.lyrics(await file.text());
        if (item !== owner) return;
        plainLyrics = plain; plainByItem.set(item.id, plain);
        setBook(verified); book.open = true; drawBook();
        const stored = await store('put', 'lyrics:' + item.id, plain);
        if (item === owner) message.textContent = stored ? 'Singer-labelled lyrics saved. Karaoke needs a scored alignment.' :
          'Singer-labelled lyrics available for this session.';
      } catch (err) { if (item === owner) message.textContent = err.message; }
    };
    const ttml = el('karaoke-ttml');
    ttml.onchange = () => { const files = [...ttml.files]; ttml.value = ''; void importFile(null, files); };
    pick.onchange = () => { const file = pick.files?.[0]; pick.value = ''; void importFile(file); };
    toggle.onclick = () => setRunning(!running);
    part.onchange = () => setPart(part.selectedIndex <= 0 ? null : verified.singers[part.selectedIndex - 1]);
    next.onclick = () => seekLine(true); back.onclick = () => seekLine(false);
    el('karaoke-demo').onclick = async () => { try { await demo(); } catch (err) { message.textContent = err.message; } };
    document.addEventListener('visibilitychange', tick);
    async function command(arg) {
      const [verb = 'status', ...words] = arg.trim().split(/\s+/).filter(Boolean);
      switch (verb.toLowerCase()) {
        case 'status': return note.textContent;
        case 'start': if (setRunning(true)) { el('karaoke-title').focus(); return 'Karaoke started.'; } return note.textContent;
        case 'stop': setRunning(false); return 'Karaoke stopped.';
        case 'invite': return invites.create(words.length ? words.join(' ').toLowerCase() === 'all' ? null : words.join(' ') : undefined);
        case 'open': invites.openPicker(); return 'Choose a Mariana duet invite to preview.';
        case 'accept': return invites.apply();
        case 'vocals': {
          const arg = words.join(' ').toLowerCase();
          if (!arg) return stems ? 'Original vocals at ' + Math.round(100 * appliedLevel) + '%.' : 'Choose a matching isolated vocal stem first.';
          const values = {on:1, off:0, 0:0, 25:.25, 50:.5, 75:.75, 100:1};
          if (!Object.prototype.hasOwnProperty.call(values,arg)) return 'Choose vocals on, off, 0, 25, 50, 75 or 100.';
          return applyLevel(values[arg]);
        }
        case 'export': if (!verified) return note.textContent; exportLink.click(); return 'Exported the bound karaoke timing sheet.';
        case 'compare': if (ttml.disabled) return note.textContent; ttml.click(); return 'Choose two independently prepared TTML word timings.';
        case 'import': if (pick.disabled) return note.textContent; pick.click(); return 'Choose the timing sheet for this recording.';
        case 'clear': return clear();
        case 'demo': return demo();
        case 'help': return usage;
        default: if (!enabled()) return note.textContent;
      }
      switch (verb.toLowerCase()) {
        case 'singers': return verified.singers.join(' · ');
        case 'part': {
          const name = words.join(' ');
          return setPart(name.toLowerCase() === 'all' ? null : name) ? 'Showing ' + (partName || 'all singers') + '.' :
            'Choose all or a singer: ' + verified.singers.join(', ');
        }
        case 'next': case 'prev': case 'previous': seekLine(verb.toLowerCase() === 'next'); return;
        case 'current': {
          const segment = verified.sheet.segments[locate(verified.sheet.segments, now())];
          if (!segment) return 'End of recording.';
          return segment.voices.filter(v => partName === null || v.singer.trim() === partName)
            .map(v => v.singer.trim() + ': ' + v.words.map(w => w.text.trim()).join(' ')).join('\n') || 'Instrumental or other part.';
        }
        default: return usage;
      }
    }
    function voices() {
      if (!owner) return 'Choose a recording first.';
      if (bookSegments.length) { book.open = true; drawBook(); book.scrollIntoView({block:'center'}); return 'Singer-labelled lyrics opened.'; }
      lyricFile.click(); return 'Choose singer-labelled TTML lyrics.';
    }
    return {change, tick, command, voices, forget:async id => {
      sheets.delete(id); plainByItem.delete(id);
      await store('delete', 'karaoke:' + id); await store('delete', 'lyrics:' + id);
    }};
  }
  window.MarianaKaraoke = Object.freeze({validate, availability, locate, mount});
})();

'use strict';

(() => {
  const formats = new Map([
    ['text/vtt', 'VTT'], ['application/x-subrip', 'SRT'], ['application/srt', 'SRT'],
    ['text/srt', 'SRT'], ['application/json', 'JSON'], ['application/transcript+json', 'JSON'],
    ['text/plain', 'Text'], ['text/html', 'Website'], ['application/xhtml+xml', 'Website'],
  ]);
  const limit = 2 * 1024 * 1024;
  const localLimit = 12 * 1024 * 1024;
  const maxCues = 20000;
  const pageSize = 40;
  const namespace = 'https://podcastindex.org/namespace/1.0';
  function variant(raw, base) {
    if (!raw || typeof raw.url !== 'string' || !raw.url.trim() || raw.url.length > 4096) return null;
    try {
      const url = new URL(raw.url, base);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
      const type = String(raw.type || '').split(';')[0].trim().toLowerCase();
      if (!formats.has(type)) return null;
      return {url:url.href, type, language:String(raw.language || '').slice(0, 40)};
    } catch { return null; }
  }

  function fromEpisode(node, feedURL) {
    const variants = [];
    for (const child of node.children) {
      if (child.localName !== 'transcript' || (child.namespaceURI !== namespace && child.prefix !== 'podcast')) continue;
      const item = variant({url:child.getAttribute('url'), type:child.getAttribute('type'), language:child.getAttribute('language')}, feedURL);
      if (item && !variants.some(v => v.url === item.url && v.language === item.language)) variants.push(item);
      if (variants.length === 16) break;
    }
    return variants.sort((a, b) => (formats.get(a.type) === 'Website') - (formats.get(b.type) === 'Website'));
  }

  function timestamp(s) {
    const match = /^(?:(\d+):)?(\d{1,2}):([0-5]\d)(?:[.,](\d{1,3}))?$/.exec(s);
    if (!match || Number(match[2]) > 59) return NaN;
    return Number(match[1] || 0) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number('0.' + (match[4] || '0'));
  }

  function cueText(raw) {
    // Strip WebVTT display annotations. The renderer always creates text nodes.
    return raw.replace(/<\/?(?:b|i|u|c(?:\.[^>]*?)?|v(?: [^>]*?)?|ruby|rt|lang(?: [^>]*?)?)>|<\d[\d:.,]*>/gi, '')
      .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&');
  }

  function parse(text, type) {
    const cues = [];
    function add(body, start = null, end = null) {
      if (typeof body !== 'string' || !body.trim()) return;
      if (start !== null && (!Number.isFinite(start) || start < 0 || !Number.isFinite(end) || end <= start)) return;
      if (cues.length >= maxCues) throw Error('Transcript exceeds the 20,000 cue limit.');
      cues.push({text:body.trim(), start});
    }
    const clean = text.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
    switch (formats.get(type)) {
      case 'JSON': {
        const data = JSON.parse(clean);
        if (!Array.isArray(data?.segments)) throw Error('Unsupported publisher JSON transcript.');
        for (const seg of data.segments) {
          if (typeof seg?.body !== 'string' || typeof seg.startTime !== 'number' || typeof seg.endTime !== 'number') continue;
          const speaker = typeof seg.speaker === 'string' && seg.speaker.trim() ? seg.speaker.trim() + ': ' : '';
          const language = data.schema === 'mariana.transcript-draft.v1' && typeof seg.language === 'string' &&
            /^[a-z]{2,3}(?:-[a-z0-9]{2,8}){0,3}$/i.test(seg.language) ? '[' + seg.language + '] ' : '';
          add(language + speaker + seg.body, seg.startTime, seg.endTime);
        }
        break;
      }
      case 'Text':
        for (const line of clean.split('\n')) add(line);
        break;
      case 'VTT': case 'SRT':
        for (const block of clean.split(/\n[ \t]*\n/)) {
          const lines = block.trim().split('\n');
          if (/^(?:WEBVTT(?:\s|$)|NOTE(?:\s|$)|STYLE$|REGION$)/.test(lines[0])) continue;
          const i = lines[0].includes('-->') ? 0 : 1;
          const times = /^\s*(\S+)\s+-->\s+(\S+)/.exec(lines[i] || '');
          if (times) {
            const raw = lines.slice(i + 1).join(' ');
            const voice = type === 'text/vtt' ? /^<v ([^<>]{1,80})>/i.exec(raw) : null;
            add((voice ? cueText(voice[1]) + ': ' : '') + cueText(raw), timestamp(times[1]), timestamp(times[2]));
          }
        }
        break;
      default: throw Error('Open this format on the publisher website.');
    }
    if (!cues.length) throw Error('This transcript contains no readable cues.');
    return cues;
  }

  async function fetchText(url, signal) {
    const response = await fetch(url, {credentials:'omit', referrerPolicy:'no-referrer', signal});
    if (!response.ok) throw Error('Publisher returned HTTP ' + response.status + '.');
    if (!response.body?.getReader) throw Error('Streaming transcript reads are unavailable here.');
    if (Number(response.headers.get('content-length')) > limit) {
      await response.body.cancel();
      throw Error('Transcript exceeds the 2 MiB reader limit.');
    }
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let bytes = 0, result = '';
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) return result + decoder.decode();
        bytes += chunk.value.byteLength;
        if (bytes > limit) throw Error('Transcript exceeds the 2 MiB reader limit.');
        result += decoder.decode(chunk.value, {stream:true});
      }
    } finally { await reader.cancel().catch(() => {}); }
  }

  function mount(lookup, seek, active) {
    const panel = lookup('episode-transcript'), controls = lookup('transcript-tools');
    const picker = lookup('transcript-variant'), load = lookup('transcript-load'), publisher = lookup('transcript-publisher');
    const search = lookup('transcript-query'), list = lookup('transcript-cues'), note = lookup('transcript-status');
    const next = lookup('transcript-next'), prev = lookup('transcript-prev');
    const address = lookup('transcript-address');
    const local = lookup('transcript-local'), localFile = lookup('transcript-file'), online = lookup('transcript-online');
    const drafts = new WeakMap();
    let item = null, choices = [], cues = [], request = null, page = 0;
    let localRead = 0;
    function draw() {
      const query = search.value.trim().toLocaleLowerCase();
      const hits = query ? cues.filter(cue => cue.text.toLocaleLowerCase().includes(query)) : cues;
      const start = page * pageSize, end = Math.min(start + pageSize, hits.length);
      list.replaceChildren();
      const owner = item;
      for (const cue of hits.slice(start, end)) {
        const li = document.createElement('li');
        if (cue.start !== null) {
          const btn = document.createElement('button');
          btn.type = 'button';
          const seconds = Math.floor(cue.start);
          btn.textContent = Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
          btn.setAttribute('aria-label', 'Jump to ' + btn.textContent);
          btn.onclick = () => { if (owner && owner === active()) seek(cue.start); };
          li.append(btn);
        }
        li.append(document.createTextNode(cue.text));
        list.append(li);
      }
      const summary = hits.length ? (start + 1) + '–' + end + ' of ' + hits.length : 'No matching lines.';
      note.textContent = item && drafts.has(item) ? 'Imported captions · ' + summary : summary;
      prev.disabled = page === 0; next.disabled = end >= hits.length;
    }
    function clear() {
      request?.abort(); request = null;
      cues = []; page = 0; controls.hidden = true; search.value = '';
      list.replaceChildren(); note.textContent = ''; address.hidden = true; address.value = '';
      const choice = choices[Number(picker.value)];
      publisher.hidden = !choice; load.disabled = !choice || formats.get(choice.type) === 'Website';
      if (choice) publisher.href = choice.url; else publisher.removeAttribute('href');
    }
    lookup('transcript-copy').onclick = async () => {
      const choice = choices[Number(picker.value)];
      if (!choice) return;
      try { await navigator.clipboard.writeText(choice.url); if (choices.includes(choice)) note.textContent = 'Publisher link copied.'; }
      catch {
        if (!choices.includes(choice)) return;
        address.hidden = false; address.value = choice.url; address.focus(); address.select();
        note.textContent = 'Copy the selected publisher link.';
      }
    };
    picker.onchange = clear;
    load.onclick = async () => {
      const owner = item, choice = choices[Number(picker.value)];
      if (!owner || !choice || load.disabled) return;
      const controller = new AbortController(); request?.abort(); request = controller;
      const timer = setTimeout(() => controller.abort(), 15000);
      load.disabled = true; note.textContent = 'Loading transcript…';
      try {
        const text = await fetchText(choice.url, controller.signal);
        if (owner !== active() || request !== controller) return;
        cues = parse(text, choice.type);
        controls.hidden = false; page = 0; draw();
      } catch (error) {
        if (owner !== active() || request !== controller) return;
        note.textContent = error instanceof TypeError ? 'Publisher access is restricted or offline. Open the publisher transcript.'
          : error.name === 'AbortError' ? 'Transcript request timed out. Try again.' : error.message;
      } finally {
        clearTimeout(timer);
        if (request === controller) { request = null; load.disabled = false; }
      }
    };
    search.oninput = () => { page = 0; draw(); };
    next.onclick = () => { page++; draw(); };
    prev.onclick = () => { page = Math.max(0, page - 1); draw(); };
    localFile.onchange = async () => {
      const file = localFile.files?.[0], owner = item, revision = ++localRead;
      localFile.value = '';
      if (!file || !owner || owner.url) return;
      note.textContent = 'Reading local captions…';
      try {
        const type = file.name.toLowerCase().endsWith('.vtt') ? 'text/vtt' : 'application/json';
        if (type === 'application/json' && !file.name.toLowerCase().endsWith('.json')) throw Error('Choose JSON or WebVTT.');
        if (file.size > localLimit) throw Error('Local captions exceed 12 MiB.');
        const parsed = parse(await file.text(), type);
        if (owner !== active() || revision !== localRead) return;
        drafts.set(owner, parsed);
        cues = parsed; controls.hidden = false; page = 0; search.value = ''; draw();
      } catch (error) {
        if (owner === active() && revision === localRead) note.textContent = error.message;
      }
    };
    return (episode) => {
      localRead++;
      localFile.value = '';
      item = episode;
      choices = (Array.isArray(item?.transcripts) ? item.transcripts.slice(0, 16) : []).map(raw => variant(raw)).filter(Boolean);
      const canImport = item && !item.url;
      panel.hidden = !canImport && choices.length === 0;
      local.hidden = !canImport;
      online.hidden = choices.length === 0;
      picker.replaceChildren(...choices.map((value, index) => new Option(
        [value.language, formats.get(value.type)].filter(Boolean).join(' · '), String(index))));
      clear();
      if (item && drafts.has(item)) {
        cues = drafts.get(item); controls.hidden = false; draw();
      }
    };
  }
  window.MarianaTranscripts = Object.freeze({ fromEpisode, mount, parse, fetchText });
})();

'use strict';
(() => {
  const tt = 'http://www.w3.org/ns/ttml', metadata = tt + '#metadata', params = tt + '#parameter';
  const xml = 'http://www.w3.org/XML/1998/namespace';
  const check = (ok, reason) => { if (!ok) throw Error(reason); };
  const key = text => text.normalize('NFKC').toLowerCase().replace(/ß/g, 'ss').replace(/ς/g, 'σ');

  function millis(text) {
    check(typeof text === 'string' && text.length <= 32, 'TTML word boundaries must use media-clock times.');
    const offset = /^(\d+(?:\.\d+)?)(ms|s)$/.exec(text);
    const clock = /^(?:(\d+):)?(\d{1,2}):([0-5]\d(?:\.\d+)?)$/.exec(text);
    function rounded(decimal, digits) {
      const [whole, fraction = ''] = decimal.split('.');
      return Number(whole) * 10 ** digits + Number(fraction.padEnd(digits,'0').slice(0,digits)) + (Number(fraction[digits]) >= 5 ? 1 : 0);
    }
    let value;
    if (offset) value = rounded(offset[1], offset[2] === 's' ? 3 : 0);
    else if (clock && +clock[2] < 60)
      value = ((+(clock[1] || 0)) * 3600 + +clock[2] * 60) * 1000 + rounded(clock[3], 3);
    else throw Error('Use TTML seconds, milliseconds or HH:MM:SS.sss.');
    check(value >= 0 && value <= 86400000, 'TTML time is outside the supported day.');
    return value;
  }

  function documentParts(text) {
    check(!/<!DOCTYPE|<!ENTITY/i.test(text), 'TTML document types and entity declarations are unsupported.');
    const doc = new DOMParser().parseFromString(text, 'application/xml'), root = doc.documentElement;
    check(root?.localName === 'tt' && root.namespaceURI === tt && (root.getAttributeNS(params, 'timeBase') || 'media') === 'media',
      'Choose a media-clock TTML document.');
    const body = [...root.children].find(node => node.localName === 'body' && node.namespaceURI === tt);
    check(body, 'No TTML lyric body was found.');
    const names = new Map();
    for (const agent of root.getElementsByTagNameNS(metadata, 'agent')) {
      const name = [...agent.children].find(node => node.localName === 'name' && node.namespaceURI === metadata);
      if (agent.hasAttributeNS(xml, 'id') && name) names.set(agent.getAttributeNS(xml, 'id'), name.textContent.trim());
    }
    return {body,names};
  }
  function lyrics(text) {
    const {body,names} = documentParts(text), verses = [];
    function read(node, inherited, voices = null, depth = 0) {
      check(depth <= 16, 'Too many nested TTML elements.');
      const agent = (node.getAttributeNS(metadata, 'agent') || inherited).replace(/^#+/, '');
      const singer = names.get(agent) || agent || 'Voice';
      if (node.localName === 'p' && node.namespaceURI === tt) {
        voices = []; verses.push({voices}); check(verses.length <= 10000, 'Too many lyric verses.');
      }
      for (const child of node.childNodes) {
        if (child.nodeType === 1) { read(child,agent,voices,depth+1); continue; }
        if (!voices || ![3,4].includes(child.nodeType)) continue;
        if (voices[voices.length - 1]?.singer !== singer) voices.push({singer,words:[{text:''}]});
        voices[voices.length - 1].words[0].text += child.textContent;
      }
    }
    read(body,'Voice');
    for (const verse of verses) {
      for (const lane of verse.voices) {
        lane.words[0].text = lane.words[0].text.replace(/\s+/gu, ' ').trim();
        check([...lane.singer].length <= 80 && [...lane.words[0].text].length <= 4096 &&
          !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(lane.singer + lane.words[0].text), 'Unsupported singer label or lyrics text.');
      }
      verse.voices = verse.voices.filter(lane => lane.words[0].text);
    }
    const result = verses.filter(verse => verse.voices.length);
    check(result.length, 'No singer-labelled lyrics found.'); return result;
  }
  function parse(text, duration) {
    const {body,names} = documentParts(text);
    check(body && (body.hasAttribute('end') || body.hasAttribute('dur')) &&
      ['0s','0ms','00:00:00','00:00:00.000'].includes(body.getAttribute('begin') || '0s'), 'The TTML body must cover the whole recording starting at zero.');
    const lines = [], coverage = [], rests = [];
    function walk(node, first, last, artist, line = null, depth = 0) {
      check(depth <= 12, 'Too many nested TTML elements.');
      check(node.namespaceURI === tt && ['body','div','p','span','br'].includes(node.localName) &&
        (node.getAttribute('timeContainer') || 'par') === 'par', 'Unsupported TTML container or markup.');
      const start = first + millis(node.getAttribute('begin') || '0s');
      let end = node.hasAttribute('end') ? first + millis(node.getAttribute('end')) : last;
      if (node.hasAttribute('dur')) end = Math.min(end, start + millis(node.getAttribute('dur')));
      check(first <= start && start < end && end <= last, 'Child timing exceeds its parent.');
      let singer = (node.getAttributeNS(metadata, 'agent') || artist).replace(/^#+/, '');
      check(!singer.includes(' '), 'Multiple agents on one word are unsupported.');
      if (node.localName === 'p') {
        check(!line && node.hasAttribute('begin') && (node.hasAttribute('end') || node.hasAttribute('dur')),
          'Each non-nested vocal phrase or instrumental section needs explicit timing.');
        line = []; lines.push(line);
        if (node.getAttributeNS(metadata, 'role') === 'x-instrumental') {
          check(!node.children.length && !node.textContent.trim(), 'Instrumental sections must contain no lyrics.');
          coverage.push([start,end]); rests.push([start,end]); return end;
        }
      }
      for (const child of node.childNodes) {
        if (child.nodeType === 1) { walk(child, start, end, singer, line, depth + 1); continue; }
        if (child.nodeType !== 3 && child.nodeType !== 4) continue;
        const word = child.textContent.trim();
        if (!word) continue;
        check(node.localName === 'span' && line && !node.children.length && node.hasAttribute('begin') &&
          (node.hasAttribute('dur') || node.hasAttribute('end')) && !/\s/u.test(word), 'Each sung word needs an explicitly timed TTML span.');
        line.push({singer:names.get(singer) || singer || 'Voice', text:word, start_ms:start, end_ms:end});
      }
      if (node.localName === 'p') {
        check(line.length, 'Mark empty phrases as instrumental.');
        let last = start;
        for (const word of [...line].sort((a,b) => a.start_ms-b.start_ms)) {
          check(word.start_ms-last <= 2000, 'A vocal phrase has an unexplained gap over two seconds.');
          last = Math.max(last,word.end_ms);
        }
        check(end-last <= 2000, 'Explicitly mark the instrumental after this vocal phrase.');
        coverage.push([start,end]);
      }
      return end;
    }
    const total = walk(body, 0, 86400000, 'Voice');
    check(Math.abs(total - duration) <= 250, 'The TTML duration differs from this recording.');
    check(lines.some(line => line.length), 'No word-timed verses found.');
    let cursor = 0;
    for (const [start,end] of coverage.sort((a,b) => a[0]-b[0])) {
      check(start <= cursor, 'Unknown interval. Explicitly mark all instrumental sections.');
      cursor = Math.max(cursor,end);
    }
    check(cursor === total, 'Unknown outro. Mark instrumental time through the end.');
    const busy = lines.flat().sort((a,b) => a.start_ms-b.start_ms);
    let idx = 0;
    for (const [start,end] of rests.sort((a,b) => a[0]-b[0])) {
      while (idx < busy.length && busy[idx].end_ms <= start) idx++;
      check(idx >= busy.length || busy[idx].start_ms >= end, 'An instrumental section overlaps sung words.');
    }
    return {total, lines:lines.filter(line => line.length)};
  }

  function reconcile(a, b, digest) {
    check(a.total === b.total, 'Both documents must cover the same timeline.');
    const byVoice = new Map(), counts = new Map(), groups = [];
    for (const line of b.lines) for (const word of line) {
      const singer = key(word.singer);
      if (!byVoice.has(singer)) byVoice.set(singer, []);
      byVoice.get(singer).push(word);
    }
    for (const lane of byVoice.values()) lane.sort((x,y) => x.start_ms-y.start_ms);
    const startOf = line => line.reduce((start,w) => Math.min(start,w.start_ms), Infinity);
    let confidence = 1, different = false;
    for (const line of [...a.lines].sort((x,y) => startOf(x)-startOf(y))) {
      const start = startOf(line), end = line.reduce((last,w) => Math.max(last,w.end_ms), 0);
      const prior = groups[groups.length - 1];
      const group = prior && start < prior.end_ms ? prior : {start_ms:start,end_ms:end,voices:new Map()};
      if (group !== prior) groups.push(group); else group.end_ms = Math.max(group.end_ms, end);
      for (const word of line) {
        const singer = key(word.singer), index = counts.get(singer) || 0;
        const other = byVoice.get(singer)?.[index];
        check(other && key(other.text) === key(word.text), 'Words or singer assignments differ between the supplied transcriptions.');
        counts.set(singer, index + 1);
        const distance = Math.max(Math.abs(word.start_ms-other.start_ms), Math.abs(word.end_ms-other.end_ms));
        different = different || distance > 0;
        const score = Math.max(0, 1 - distance/1000); confidence = Math.min(confidence, score);
        if (!group.voices.has(word.singer)) group.voices.set(word.singer, []);
        group.voices.get(word.singer).push({text:word.text,start_ms:word.start_ms,end_ms:word.end_ms,confidence:score});
      }
    }
    for (const [singer, words] of byVoice) check(counts.get(singer) === words.length, 'One transcription has unmatched words.');
    check(different, 'Identical word boundaries cannot establish independent alignment evidence.');
    const segments = []; let cursor = 0;
    for (const group of groups) {
      if (group.start_ms > cursor) segments.push({start_ms:cursor,end_ms:group.start_ms,voices:[]});
      segments.push({start_ms:group.start_ms,end_ms:group.end_ms,voices:[...group.voices].map(([singer,words]) => ({
        singer,words:words.sort((x,y) => x.start_ms-y.start_ms)}))}); cursor = group.end_ms;
    }
    if (cursor < a.total) segments.push({start_ms:cursor,end_ms:a.total,voices:[]});
    return {schema:'mariana.karaoke.v1',source:'Timing agreement between two user-selected TTML transcriptions',
      duration_ms:a.total,media_sha256:digest,confidence,segments};
  }
  async function compare(files, digest, duration) {
    check(files.length === 2 && Number.isFinite(duration) && duration > 0,
      'Select two independently prepared, word-timed TTML files for the loaded recording.');
    check(files.every(f => f.size <= 2 * 1024 * 1024), 'Each TTML document must fit within 2 MiB.');
    const texts = await Promise.all(files.map(async file => new TextDecoder('utf-8', {fatal:true}).decode(await file.arrayBuffer())));
    check(texts[0] !== texts[1], 'Choose two independently prepared timing documents.');
    return reconcile(parse(texts[0], duration), parse(texts[1], duration), digest);
  }
  window.MarianaKaraokeTTML = Object.freeze({compare, reconcile, parse, lyrics});
})();

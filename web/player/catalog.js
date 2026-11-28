'use strict';

// Catalogs are queried only after a search. Following saves a feed on this device.
(() => {
  const form = document.getElementById('catalog-search');
  const results = document.getElementById('catalog-results');
  const shelf = document.getElementById('catalog-shelf');
  const message = document.getElementById('catalog-status');
  const savedKey = window.MarianaProfiles?.key('mariana.public-feeds.v1') ?? 'mariana.public-feeds.v1';
  const subscriptions = new Map();
  let request;
  let podRequest;
  let openedShow;
  let recentPodShows = [];
  const pageSize = 10;
  const podHelp = 'podbean search WORDS · open SHOW · episodes [PAGE] · play NUMBER · queue NUMBER · follow [SHOW] · list · unfollow SHOW';

  function showSlug(input) {
    const raw = String(input).trim().toLowerCase();
    const slug = raw.match(/^(?:https?:\/\/)?([a-z0-9-]+)\.podbean\.com\/?$/)?.[1]
      || raw.match(/^https?:\/\/feed\.podbean\.com\/([a-z0-9-]+)\/feed\.xml$/)?.[1] || raw;
    if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(slug)
      || ['www','feed','api','help','developers','admin'].includes(slug)) {
      throw Error('Enter a Podbean show slug, show homepage, or public feed URL.');
    }
    return slug;
  }

  const podFeed = slug => 'https://feed.podbean.com/' + slug + '/feed.xml';
  function podEntry(input) {
    const slug = showSlug(input);
    return {feed:podFeed(slug), title:slug, by:'Podbean', type:'podcast'};
  }


  function safeURL(value) {
    try {
      const url = new URL(value);
      if (['https:', 'http:'].includes(url.protocol) && !url.username && !url.password) return url.href;
    } catch { /* Some catalog entries have no public feed. */ }
    return '';
  }

  function entry(raw) {
    const feed = safeURL(raw?.feed);
    if (!feed || typeof raw?.title !== 'string' || !['book', 'podcast'].includes(raw.type)) return null;
    return {feed, title:raw.title.slice(0, 300), by:String(raw.by || '').slice(0, 200), type:raw.type};
  }

  try {
    const rows = JSON.parse(localStorage.getItem(savedKey) || '[]');
    if (Array.isArray(rows)) {
      for (const raw of rows.slice(0, 250)) {
        const item = entry(raw);
        if (item) subscriptions.set(item.feed, item);
      }
    }
  } catch { /* The catalog also works without persistence. */ }

  function saveShelf() {
    drawShelf();
    try { localStorage.setItem(savedKey, JSON.stringify([...subscriptions.values()])); return true; }
    catch { message.textContent = 'Shelf updated for this session. Device storage is unavailable.'; return false; }
  }

  function showRow(item, savedRow) {
    const li = document.createElement('li');
    const text = document.createElement('span');
    const detail = document.createElement('small');
    text.textContent = item.title;
    detail.textContent = [item.type === 'book' ? 'LibriVox' : 'Podcast', item.by].filter(Boolean).join(' · ');
    text.append(detail);
    const browse = button(item.type === 'book' ? 'Chapters' : 'Episodes', () => browseFeed(item, li, browse));
    const toggle = button(savedRow ? 'Remove' : 'Save', () => {
      if (savedRow) subscriptions.delete(item.feed);
      else if (subscriptions.size >= 250 && !subscriptions.has(item.feed)) {
        message.textContent = 'Your shelf holds 250 feeds. Remove one to save another.';
        return;
      } else subscriptions.set(item.feed, item);
      message.textContent = savedRow ? 'Removed from your shelf.' : 'Saved to your shelf.';
      saveShelf();
    });
    li.append(text, browse, toggle);
    return li;
  }

  function drawShelf() {
    shelf.replaceChildren(...[...subscriptions.values()].map(item => showRow(item, true)));
    document.getElementById('shelf-heading').hidden = subscriptions.size === 0;
  }

  async function resource(url, signal) {
    const response = await fetch(url, {credentials:'omit', referrerPolicy:'no-referrer', signal});
    if (!response.ok) throw Error('The provider returned HTTP ' + response.status + '.');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let bytes = 0;
    let text = '';
    try {
      while (true) {
        const next = await reader.read();
        if (next.done) break;
        bytes += next.value.byteLength;
        if (bytes > 4 * 1024 * 1024) throw Error('This feed exceeds the 4 MB reader limit.');
        text += decoder.decode(next.value, {stream:true});
      }
    } finally { await reader.cancel().catch(() => {}); }
    return {text:text + decoder.decode(), url:response.url || url};
  }

  function failure(error) {
    if (error.name === 'AbortError') return 'Request timed out. Try again.';
    if (error instanceof TypeError) return 'This provider is unreachable or restricts browser requests. You can add a direct audio URL to the queue.';
    return error.message;
  }

  async function episodesFor(item, signal) {
    const payload = await resource(item.feed, signal);
    const xml = new DOMParser().parseFromString(payload.text, 'application/xml');
    if (xml.querySelector('parsererror')) throw Error('The provider returned an invalid feed.');
    const title = (xml.querySelector('channel > title, feed > title')?.textContent || item.title).trim().slice(0, 300);
    const episodes = [], seen = new Set();
    for (const node of Array.from(xml.querySelectorAll('item, entry')).slice(0, 1500)) {
      const link = Array.from(node.querySelectorAll('enclosure[url], link[rel="enclosure"][href]')).find(el => {
        const type = el.getAttribute('type') || '';
        const href = el.getAttribute('url') || el.getAttribute('href') || '';
        return !/mpegurl/i.test(type) && !/\.m3u8?(?:[?#]|$)/i.test(href)
          && (!type || /^(?:audio|video)\//i.test(type) || /\.(?:mp3|m4a|mp4|ogg|opus|webm|wav)(?:[?#]|$)/i.test(href));
      });
      const href = link?.getAttribute('url') || link?.getAttribute('href');
      if (!href) continue;
      let url;
      try { url = safeURL(new URL(href, payload.url).href); } catch { continue; }
      if (!url || seen.has(url)) continue;
      seen.add(url);
      episodes.push({url, title:(node.querySelector('title')?.textContent || 'Untitled section').trim().slice(0, 300),
        by:title, spoken:true, transcripts:window.MarianaTranscripts.fromEpisode(node, payload.url)});
    }
    if (!episodes.length) throw Error('This feed has no playable enclosures.');
    return {item:{...item, title}, episodes};
  }

  function numberInRange(raw, total) {
    if (!/^[1-9][0-9]{0,5}$/.test(raw) || Number(raw) > total) throw Error('Choose a number between 1 and ' + total + '.');
    return Number(raw);
  }

  async function selectEpisode(item, now) {
    const added = await append([item]);
    if (now) {
      const selected = queue.find(row => row.url === item.url);
      if (!selected) throw Error('This episode is no longer queued.');
      if (selected === current) await play();
      else await select(selected, true);
      return 'Selected · ' + item.title;
    }
    return added ? 'Added to your queue.' : 'Already in your queue.';
  }

  function drawEpisodes(show, row, page) {
    row.querySelector('.feed-episodes')?.remove();
    const panel = document.createElement('div'), episodes = document.createElement('ol');
    panel.className = 'feed-episodes';
    const start = (page - 1) * pageSize, pages = Math.ceil(show.episodes.length / pageSize);
    episodes.setAttribute('start', String(start + 1));
    for (const item of show.episodes.slice(start, start + pageSize)) {
      const line = document.createElement('li');
      const action = async now => {
        try { message.textContent = await selectEpisode(item, now); }
        catch (error) { message.textContent = failure(error); }
      };
      line.append(button(item.title, () => action(false), 'Queue ' + item.title),
        button('Play', () => action(true), 'Play ' + item.title));
      episodes.append(line);
    }
    const pageText = document.createElement('small');
    pageText.textContent = 'Page ' + page + ' of ' + pages;
    panel.append(episodes, pageText);
    if (page > 1) panel.append(button('Previous', () => drawEpisodes(show, row, page - 1)));
    if (page < pages) panel.append(button('Next', () => drawEpisodes(show, row, page + 1)));
    row.append(panel);
  }

  async function browseFeed(item, row, control) {
    const before = row.querySelector('.feed-episodes');
    if (before) { before.remove(); control.setAttribute('aria-expanded', 'false'); return; }
    control.disabled = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const show = await episodesFor(item, controller.signal);
      if (item.by === 'Podbean' && row.isConnected && !podRequest) openedShow = show;
      drawEpisodes(show, row, 1);
      control.setAttribute('aria-expanded', 'true');
      message.textContent = 'Select a title to queue it or choose Play.';
    } catch (error) { message.textContent = failure(error); }
    finally { clearTimeout(timer); control.disabled = false; }
  }

  async function podSearch(term, signal) {
    if (!term || term.length > 180) throw Error('Enter 1 to 180 characters after podbean search.');
    const url = new URL('https://itunes.apple.com/search');
    url.search = new URLSearchParams({media:'podcast', entity:'podcast', limit:'50', term});
    const data = JSON.parse((await resource(url, signal)).text);
    if (!Array.isArray(data.results)) throw Error('The podcast directory returned an unreadable response.');
    const found = new Map();
    for (const raw of data.results.slice(0, 50)) {
      if (!raw || typeof raw.feedUrl !== 'string' || !raw.feedUrl.includes('://')) continue;
      try {
        const item = podEntry(raw.feedUrl);
        item.title = String(raw.collectionName || item.title).slice(0, 300);
        if (!found.has(item.feed)) found.set(item.feed, item);
      } catch { /* This directory result has a different host. */ }
    }
    const rows = [...found.values()];
    if (!signal.aborted) recentPodShows = rows;
    return rows;
  }

  async function podCommand(args) {
    const [operation = 'help', ...values] = args;
    const op = operation.toLowerCase();
    if (op === 'search' || (op === 'open' && values.length === 1)) {
      if (op === 'open') openedShow = null;
      const item = op === 'open' ? podEntry(values[0]) : null;
      podRequest?.abort();
      const controller = new AbortController();
      podRequest = controller;

      const timer = setTimeout(() => controller.abort(), 15000);
      try {
        if (item) {
          const show = await episodesFor(item, controller.signal);
          if (podRequest !== controller) return 'A newer request took precedence.';
          openedShow = show;
          return podCommand(['episodes']);
        }
        const found = await podSearch(values.join(' '), controller.signal);
        return found.map(row => showSlug(row.feed) + ' · ' + row.title).join('\n')
          || 'No Podbean feeds in these Apple Podcasts directory results. Use podbean open SHOW.';
      } catch (error) { return failure(error); }
      finally { clearTimeout(timer); if (podRequest === controller) podRequest = null; }
    }
    if ((op === 'episodes' && values.length <= 1) || (['play','queue'].includes(op) && values.length === 1)) {
      if (!openedShow) return 'Open a Podbean show first.';
      const rows = openedShow.episodes;
      if (op !== 'episodes') return selectEpisode(rows[numberInRange(values[0], rows.length) - 1], op === 'play');
      const pages = Math.ceil(rows.length / pageSize);
      const page = numberInRange(values[0] || '1', pages), start = (page - 1) * pageSize;
      return [openedShow.item.title + ' · page ' + page + '/' + pages + ' · ' + rows.length + ' episodes',
        ...rows.slice(start, start + pageSize).map((row, i) => (start + i + 1) + '. ' + row.title)].join('\n');
    }
    if (op === 'list' && !values.length) {
      const items = [...subscriptions.values()].filter(item => {
        try { return podFeed(showSlug(item.feed)) === item.feed; } catch { return false; }
      });
      return items.map(item => showSlug(item.feed) + ' · ' + item.title).join('\n') || 'No followed Podbean shows.';
    }
    if (op === 'follow' && values.length <= 1) {
      const item = values.length ? podEntry(values[0]) : openedShow?.item;
      if (!item) return 'Open a show first or provide its slug.';
      if (subscriptions.size >= 250 && !subscriptions.has(item.feed)) return 'Your shelf holds 250 feeds.';
      subscriptions.set(item.feed, openedShow?.item.feed === item.feed ? openedShow.item : (subscriptions.get(item.feed) || item));
      return 'Following ' + showSlug(item.feed) + (saveShelf() ? '.' : ' for this session. Device storage is unavailable.');
    }
    if (op === 'unfollow' && values.length === 1) {
      const slug = showSlug(values[0]);
      if (!subscriptions.delete(podFeed(slug))) return slug + ' is already absent from your shelf.';
      return 'Removed ' + slug + (saveShelf() ? '.' : ' for this session. Device storage is unavailable.');
    }
    return podHelp;
  }

  let bookResults = [], bookRequest, lastBook, bookSearchRevision = 0;
  const bookHelp = 'librivox search TITLE | author SURNAME | genre GENRE | recent [DAYS] [--limit N --offset N] | show REF | chapters REF [PAGE] | play REF [CHAPTER] | queue REF [CHAPTER|all] | rss REF. Use a result number or id:CATALOG-ID.';

  async function findBooks(params, signal) {
    const url = new URL('https://librivox.org/api/feed/audiobooks/');
    url.search = new URLSearchParams({format:'json', ...params});
    const data = JSON.parse((await resource(url, signal)).text);
    if (data.books != null && !Array.isArray(data.books)) throw Error('The audiobook catalog returned an unreadable response.');
    const rows = [];
    for (const raw of (data.books || []).slice(0, Number(params.limit))) {
      const item = entry({type:'book', title:raw?.title, feed:raw?.url_rss,
        by:(Array.isArray(raw?.authors) ? raw.authors : []).map(a => [a?.first_name,a?.last_name].filter(Boolean).join(' ')).join(', ')});
      if (item) rows.push({...item, catalogId:/^[1-9][0-9]{0,11}$/.test(raw.id) ? String(raw.id) : '',
        language:String(raw.language || '').slice(0, 80), duration:String(raw.totaltime || '').slice(0, 32)});
    }
    return rows;
  }

  function bookQuery(op, args) {
    const term = [], params = {limit:10, offset:0};
    for (let i = 0; i < args.length; i++) {
      const key = args[i];
      if (key === '--limit') params.limit = numberInRange(args[++i], 50);
      else if (key === '--offset') {
        const offset = args[++i];
        if (!/^(?:0|[1-9][0-9]{0,8})$/.test(offset)) throw Error('Provide a nonnegative result offset.');
        params.offset = Number(offset);
      } else if (key.startsWith('--')) throw Error(bookHelp);
      else term.push(key);
    }
    if (op === 'recent') {
      const days = numberInRange(term.length ? term.join(' ') : '30', 3660);
      params.since = Math.floor(Date.now() / 1000) - days * 86400;
    } else {
      if (!term.length || term.join(' ').length > 200) throw Error(bookHelp);
      params[op === 'search' ? 'title' : op] = (op === 'search' ? '^' : '') + term.join(' ');
    }
    return params;
  }

  async function bookCommand(args) {
    const [raw = 'help', ...values] = args, op = raw.toLowerCase();
    if (op === 'help' || op === '?') return bookHelp;
    bookRequest?.abort();
    const controller = new AbortController();
    bookRequest = controller;
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      if (['search','author','genre','recent'].includes(op)) {
        const revision = ++bookSearchRevision;
        bookResults = [];
        const books = await findBooks(bookQuery(op, values), controller.signal);
        if (revision !== bookSearchRevision || bookRequest !== controller) return 'A newer request took precedence.';
        bookResults = books;
        return books.map((book, i) => [String(i + 1) + '. ' + book.title, book.by,
          book.catalogId && 'id:' + book.catalogId].filter(Boolean).join(' · ')).join('\n') || 'No matching books with public chapter feeds.';
      }
      if (!['show','rss','play','chapters','queue'].includes(op) || !values.length
        || values.length > (['show','rss'].includes(op) ? 1 : 2)) return bookHelp;
      const ref = values[0];
      let book;
      if (/^id:[1-9][0-9]{0,11}$/.test(ref)) {
        const id = ref.slice(3);
        book = bookResults.find(item => item.catalogId === id);
        if (!book) book = (await findBooks({id, limit:1}, controller.signal)).find(item => item.catalogId === id);
        if (!book) return 'No matching book with a public chapter feed.';
      } else {
        if (!bookResults.length) return 'Search for a book first or use id:CATALOG-ID.';
        book = bookResults[numberInRange(ref, bookResults.length) - 1];
      }
      if (op === 'show') return [book.title, book.by, book.language, book.duration, book.feed].filter(Boolean).join(' · ');
      if (op === 'rss') return book.feed;
      const show = lastBook?.item.feed === book.feed ? lastBook : await episodesFor(book, controller.signal);
      if (bookRequest !== controller) return 'A newer request took precedence.';
      lastBook = show;
      const rows = show.episodes;
      if (op === 'chapters') {
        const pages = Math.ceil(rows.length / pageSize), page = numberInRange(values[1] || '1', pages);
        const start = (page - 1) * pageSize;
        return [book.title + ' · chapters · page ' + page + '/' + pages,
          ...rows.slice(start, start + pageSize).map((row, i) => (start + i + 1) + '. ' + row.title)].join('\n');
      }
      const which = values[1] || (op === 'queue' ? 'all' : '1');
      if (op === 'queue' && which === 'all') return 'Added ' + await append(rows) + ' chapter(s) to your queue.';
      const chosen = rows[numberInRange(which, rows.length) - 1];
      if (op === 'play') await append(rows);
      return selectEpisode(chosen, op === 'play');
    } catch (error) { return failure(error); }
    finally { clearTimeout(timer); }
  }

  // Completion reads only the currently loaded results, public labels and local shelf.
  function podCompletionRows(action) {
    if (action === 'play' || action === 'queue') return (openedShow?.episodes || []).map(
      (row, index) => ({value:String(index + 1), description:row.title}));
    if (action === 'episodes') return Array.from({length:Math.ceil((openedShow?.episodes.length || 0) / pageSize)},
      (_, i) => ({value:String(i + 1), description:'Episode page ' + (i + 1)}));
    const items = action === 'unfollow' ? subscriptions.values()
      : [...(openedShow ? [openedShow.item] : []), ...recentPodShows, ...subscriptions.values()];
    const shows = [];
    for (const item of items) {
      try { shows.push({value:showSlug(item.feed), description:item.title}); } catch { /* Other RSS provider. */ }
    }
    return shows;
  }
  function bookCompletionRows(reference) {
    if (!reference) return bookResults.map((book, i) => ({value:String(i + 1), description:book.title}))
      .concat(bookResults.filter(book => book.catalogId).map(book => ({value:'id:' + book.catalogId, description:book.title})));
    const book = reference.startsWith('id:') ? bookResults.find(b => 'id:' + b.catalogId === reference) : bookResults[Number(reference) - 1];
    if (!lastBook || (book ? book.feed !== lastBook.item.feed : 'id:' + lastBook.item.catalogId !== reference)) return [];
    return lastBook.episodes.map((chapter, i) => ({value:String(i + 1), description:chapter.title}));
  }
  window.MarianaPodbean = {command:podCommand, completionRows:podCompletionRows};
  window.MarianaLibrivox = {command:bookCommand, completionRows:bookCompletionRows};
  form.addEventListener('submit', async event => {
    event.preventDefault();
    request?.abort();
    const controller = new AbortController();
    request = controller;
    const timer = setTimeout(() => controller.abort(), 15000);
    const term = form.elements.term.value.trim().slice(0, 180);
    const type = form.elements.catalog.value;
    results.replaceChildren();
    if (!term) { clearTimeout(timer); message.textContent = 'Enter a title.'; return; }
    try {
      message.textContent = 'Searching…';
      if (type === 'podbean' || type === 'podbean-show') {
        const shows = type === 'podbean' ? await podSearch(term, controller.signal)
          : [podEntry(term)];
        if (request !== controller) return;
        for (const show of shows) results.append(showRow(show, false));
        message.textContent = shows.length ? 'Choose Episodes to browse the show.' : 'No matching Podbean feeds in these Apple Podcasts results.';
        return;
      }
      let matches;
      if (type === 'book') {
        const revision = ++bookSearchRevision;
        bookResults = [];
        matches = await findBooks({limit:12, title:'^' + term}, controller.signal);
        if (revision !== bookSearchRevision || request !== controller) return;
        bookResults = matches;
      } else {
        const url = new URL('https://itunes.apple.com/search');
        url.search = new URLSearchParams({media:'podcast', entity:'podcast', limit:'12', term});
        const data = JSON.parse((await resource(url, controller.signal)).text);
        if (request !== controller) return;
        matches = (Array.isArray(data.results) ? data.results : []).slice(0, 12).map(raw =>
          entry({type, title:raw.collectionName, feed:raw.feedUrl, by:raw.artistName})).filter(Boolean);
      }
      for (const item of matches) results.append(showRow(item, false));
      message.textContent = results.children.length ? results.children.length + ' results.' : 'No public feeds found.';
    } catch (error) { if (request === controller) message.textContent = failure(error); }
    finally { clearTimeout(timer); }
  });
  drawShelf();
})();

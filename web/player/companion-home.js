(() => {
  'use strict';

  function mount({root, request, submit, requestArtwork}) {
    if (!root) return null;
    let visible = false, busy = false, hostBusy = false, timer, model, modelKey, generation = 0;
    const expanded = new Set();

    function make(tag, label, className) {
      const el = document.createElement(tag);
      if (label) el.textContent = label;
      if (className) el.className = className;
      return el;
    }

    let artworkBatch = null;
    function clearArtwork() {
      if (!artworkBatch) return;
      artworkBatch.controller.abort();
      for (const url of artworkBatch.urls) URL.revokeObjectURL(url);
      artworkBatch = null;
    }

    async function addArtwork(card, key) {
      const batch = artworkBatch;
      if (!batch || typeof key !== 'string' || !/^[a-f0-9]{64}\.(jpg|png|webp)$/.test(key)) return;
      const {controller:{signal}, urls, pending} = batch;
      if (!pending.has(key)) pending.set(key, requestArtwork(key, signal).then(blob => {
        if (signal.aborted || !/^image\/(jpeg|png|webp)$/.test(blob.type) || !blob.size || blob.size > 2 * 1024 * 1024)
          return null;
        const url = URL.createObjectURL(blob);
        urls.add(url);
        return url;
      }).catch(() => null));
      const url = await pending.get(key);
      if (!url || signal.aborted || !card.isConnected) return;
      const image = make('img', '', 'paired-home-artwork');
      image.alt = '';
      image.loading = 'lazy';
      image.decoding = 'async';
      image.addEventListener('error', () => image.remove(), {once:true});
      image.src = url;
      card.prepend(image);
    }

    function action(label, command) {
      const button = make('button', label);
      button.type = 'button';
      button.dataset.homeAction = '';
      button.disabled = busy || hostBusy;
      button.addEventListener('click', () => void send(command));
      return button;
    }

    function updateButtons() {
      for (const button of root.querySelectorAll('button[data-home-action]')) {
        button.disabled = busy || hostBusy || button.dataset.homeUnavailable === 'true';
      }
    }

    async function send(command) {
      if (!visible || busy || hostBusy) return;
      busy = true;
      updateButtons();
      try {
        await submit(command);
      } finally {
        busy = false;
        updateButtons();
        void refresh(true);
      }
    }

    const heading = make('h2', 'Home');
    const onlineStatus = make('p', '', 'paired-home-status');
    onlineStatus.setAttribute('role', 'status');
    const commandStatus = make('p', '', 'paired-home-command-status');
    commandStatus.setAttribute('role', 'status');
    const controls = make('div', '', 'paired-home-controls');
    const query = make('input');
    query.type = 'search';
    query.maxLength = 160;
    query.placeholder = 'Search news, releases, sources';
    query.setAttribute('aria-label', 'Search Home');
    const discovery = make('div', '', 'paired-home-selection');
    const rows = make('div');
    const detail = make('div');
    detail.append(heading, onlineStatus);
    const bar = make('header', '', 'paired-home-bar');
    bar.append(detail, controls);
    root.append(bar, commandStatus, query, discovery, rows);

    const validChoiceId = value => typeof value === 'string' && value.length <= 128 &&
      /^(release|catalogue):[A-Za-z0-9_.:-]+$/.test(value);

    function drawDiscovery() {
      discovery.replaceChildren();
      const selection = model.discovery;
      if (!selection) return;
      const {itemId, revision, state, title, message, page, hasMore} = selection;
      if (!validChoiceId(itemId) ||
          !Number.isSafeInteger(revision) || revision <= 0) return;
      const known = model.sections.some(section => section.items.some(item => item.id === itemId && item.selectable));
      if (!known) return;
      discovery.append(make('h3', title), make('p', message), action('Close selection', 'home cancel'));
      if (page > 0) discovery.append(action('Previous episodes', `home pick ${itemId} ${page}`));
      if (hasMore && Number.isSafeInteger(page) && page >= 0 && page < 7) {
        discovery.append(action('More episodes', `home pick ${itemId} ${page + 2}`));
      }
      const list = make('ol', '', 'paired-home-choice-list');
      for (const row of selection.rows || []) {
        if (!Number.isSafeInteger(row.number) || row.number < 1 || row.number > 30) continue;
        const li = make('li');
        const label = make('div');
        label.append(make('strong', row.title), make('small', [row.artist, row.source].filter(Boolean).join(' · ')));
        li.append(label);
        if (state === 'tracks') li.append(action('Find versions', `home versions ${revision} ${row.number}`));
        if (state === 'choices' && row.playable) li.append(
          action('Play', `home play ${revision} ${row.number}`),
          action('Queue', `home queue ${revision} ${row.number}`)
        );
        list.append(li);
      }
      if (list.childElementCount) discovery.append(list);
    }

    function draw() {
      clearArtwork();
      if (visible && requestArtwork) artworkBatch = {controller: new AbortController(), urls: new Set(), pending: new Map()};
      rows.replaceChildren();
      if (!model) {
        onlineStatus.textContent = 'Reading the native homepage…';
        return;
      }
      const labels = {
        loading: 'Refreshing discovery',
        ready: 'Online discovery on',
        stale: 'Showing cached discoveries',
        partial: 'Some discovery sources unavailable',
        error: 'Online discovery unavailable',
        offline: 'Local and cached sources',
      };
      const stateLabel = model.onlineEnabled ? labels[model.state] : 'Online discovery off';
      onlineStatus.textContent = [stateLabel, model.message !== stateLabel ? model.message : null].filter(Boolean).join(' · ');
      const consent = action(model.onlineEnabled ? 'Turn online discovery off' : 'Enable online discovery',
        model.onlineEnabled ? 'home online disable' : 'home online enable');
      const update = action('Refresh news and releases', 'home refresh');
      update.dataset.homeUnavailable = String(!model.onlineEnabled || model.state === 'loading');
      update.disabled = update.disabled || update.dataset.homeUnavailable === 'true';
      controls.replaceChildren(consent, update);
      drawDiscovery();

      const terms = query.value.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
      for (const section of model.sections) {
        const matches = section.items.filter(item => terms.every(term =>
          [item.title, item.summary, item.source, section.title].join(' ').toLocaleLowerCase().includes(term)));
        if (terms.length && !matches.length) continue;
        const part = make('section', '', 'paired-home-section');
        part.append(make('h3', section.title));
        const limit = terms.length || expanded.has(section.key) ? matches.length : 6;
        const cards = make('div', '', 'paired-home-cards');
        for (const item of matches.slice(0, limit)) {
          const card = make('article', '', 'paired-home-card');
          void addArtwork(card, item.artwork);
          card.append(make('small', [item.source, item.published].filter(Boolean).join(' · ')));
          card.append(make('h4', item.title));
          if (item.summary) card.append(make('p', item.summary));
          if (item.link) {
            try {
              const url = new URL(item.link);
              if (url.protocol === 'https:' && !url.username && !url.password) {
                const link = make('a', 'Open source');
                link.href = url.href;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                card.append(link);
              }
            } catch {}
          }
          if (item.selectable && validChoiceId(item.id)) {
            const label = item.kind === 'station' ? 'Live station' :
              item.id.startsWith('catalogue:') ? 'Browse episodes' : 'Find playable versions';
            card.append(action(label, `home pick ${item.id}`));
          }
          cards.append(card);
        }
        if (matches.length) part.append(cards);
        else if (['culture', 'releases'].includes(section.key)) {
          part.append(make('p', model.onlineEnabled ? 'No cached items yet. Try Refresh.' :
            'Enable online discovery to retrieve this feed.'));
        }
        if (matches.length > limit) {
          const more = make('button', `Show all ${matches.length}`);
          more.type = 'button';
          more.onclick = () => { expanded.add(section.key); draw(); };
          part.append(more);
        }
        rows.append(part);
      }
      if (terms.length && !rows.childElementCount) rows.append(make('p', 'No cached or bundled cards match.'));
    }

    let requestGeneration = null;
    async function refresh(force = false) {
      clearTimeout(timer);
      if (!visible || document.hidden && !force || requestGeneration === generation) return;
      const epoch = generation;
      requestGeneration = epoch;
      try {
        const result = await request();
        if (!visible || generation !== epoch) return;
        const next = result?.homepage ?? result;
        if (!Array.isArray(next?.sections)) throw Error('Homepage unavailable');
        const key = JSON.stringify(next);
        if (!busy && key !== modelKey) {
          model = next;
          modelKey = key;
          draw();
        }
      } catch {
        if (visible && generation === epoch && !model) onlineStatus.textContent = 'Home is temporarily unavailable.';
      } finally {
        if (requestGeneration === epoch) requestGeneration = null;
        if (visible && generation === epoch) {
          const updating = model?.state === 'loading' || ['loading', 'working'].includes(model?.discovery?.state);
          timer = setTimeout(() => void refresh(), updating ? 1200 : 5000);
        }
      }
    }

    query.addEventListener('input', draw);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(true); });

    return {
      show() {
        if (visible) return;
        visible = true;
        draw();
        void refresh(true);
      },
      hide() {
        if (!visible) return;
        visible = false;
        generation++;
        clearTimeout(timer);
        clearArtwork();
      },
      setBusy(value) {
        if (hostBusy === value) return;
        hostBusy = value;
        updateButtons();
        if (!hostBusy) void refresh(true);
      },
      setPending(message) {
        commandStatus.textContent = message || '';
      },
      clear() {
        commandStatus.textContent = '';
        hostBusy = false;
        model = modelKey = null;
        query.value = '';
        expanded.clear();
        discovery.replaceChildren();
        controls.replaceChildren();
        draw();
      },
    };
  }

  globalThis.MarianaPairedHome = {mount};
})();

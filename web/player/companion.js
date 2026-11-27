(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  function pairLink(value, mode) {
    let link;
    try { link = new URL(value); } catch { throw new Error('Paste the private invitation printed by web session.'); }
    if (link.protocol !== 'http:' || link.hostname !== '127.0.0.1' || !link.port ||
        link.username || link.password || link.pathname !== '/' || !/^#pair=[\w-]{43}$/.test(link.hash))
      throw new Error('Use the 127.0.0.1 invitation from Mariana on this computer.');
    link.search = mode === 'flow' ? '?view=flow' : '';
    return link.href;
  }
  const launch = byId('native-invitation');
  if (launch) {
    launch.onsubmit = event => {
      event.preventDefault();
      try {
        const input = byId('native-invitation-url');
        const url = pairLink(input.value.trim(), document.body.dataset.mode);
        input.value = '';
        window.location.assign(url);
      } catch (error) { byId('native-invitation-note').textContent = error.message; }
    };
    return;
  }
  if (!byId('native-workspace')) return;
  const invitation = new URLSearchParams(location.hash.slice(1)).get('pair');
  history.replaceState(null, '', location.pathname + location.search);
  const output = byId('native-log'), note = byId('native-message'), pending = byId('native-pending');
  const catalog = [];
  let token, timer, lastJob, busy = false;
  let browserAction, policyVersion = 0, revoking = false;
  const approval = byId('native-approval'), sessionTime = byId('native-session-time');
  const browserNotice = byId('native-browser-notice'), revoke = byId('native-revoke');
  const commands = [...document.querySelectorAll('#native-transport button'), ...byId('native-command').querySelectorAll('input,button')];
  const consoleView = globalThis.MarianaPairedConsole?.mount(byId('native-console'));
  const flow = globalThis.MarianaPairedFlow?.mount({byId, send:sendControl, clock});
  const home = globalThis.MarianaPairedHome?.mount({
    root:byId('native-home-content'), request:() => api('homepage',token), submit:text => send(text,true),
    requestArtwork:(key,signal) => api('homepage-image',token,{key},signal),
  });
  const collections = globalThis.MarianaCollections?.mount({
    root:byId('native-collections'), request:data => api('collections',token,data),
    submit:(command,binding) => send(command,false,undefined,binding),
  });
  const similar = globalThis.MarianaPairedSimilar?.mount({
    root:byId('native-similar'), request:data => api('similarity',token,data),
    submit:(command,key) => send(command,true,key),
  });
  let shownMedia = {};
  const collectionPanels = new Set(['queue','playlists','albums','favorites','live']);
  const nav = [...byId('native-flow-nav').querySelectorAll('button[data-panel]')];
  const switches = [...document.querySelectorAll('.top nav button[data-mode]')];
  let panel = 'commands', capabilities = {}, collectionTimer = null;
  function panelAvailable(key) {
    if (key === 'home') return capabilities.homepage && Boolean(home);
    if (key === 'library') return capabilities.library;
    if (key === 'similar') return capabilities.similarity && Boolean(similar);
    if (collectionPanels.has(key)) return capabilities.collections && Boolean(collections);
    return key === 'commands';
  }
  function showPanel(key, force = false, target) {
    if (!panelAvailable(key)) return;
    if (!force && panel === key) return;
    panel = key;
    const isFlow = document.body.dataset.mode === 'flow';
    document.body.dataset.nativePanel = key;
    for (const button of nav) {
      button.hidden = !panelAvailable(button.dataset.panel);
      if (button.dataset.panel === key) button.setAttribute('aria-current','page');
      else button.removeAttribute('aria-current');
    }
    byId('native-home').hidden = !isFlow || key !== 'home';
    byId('native-library').hidden = !isFlow || key !== 'library';
    byId('native-collections').hidden = !isFlow || !collectionPanels.has(key);
    byId('native-similar').hidden = !isFlow || key !== 'similar';
    byId('native-command-card').hidden = !isFlow || key !== 'commands';
    if (isFlow && token && key === 'home') home?.show();
    else home?.hide();
    clearInterval(collectionTimer);
    if (isFlow && token && collectionPanels.has(key)) {
      void collections?.show(key);
      collectionTimer = setInterval(() => { if (!busy) void collections?.refresh(); }, 6500);
    } else collections?.hide?.();
    if (isFlow && token && key === 'library') void readLibrary(libraryOffset);
    if (isFlow && token && key === 'similar') similar.show(target); else similar?.hide();
  }
  function setView(mode) {
    document.body.dataset.mode = mode;
    for (const btn of switches) btn.setAttribute('aria-pressed', String(btn.dataset.mode === mode));
    consoleView?.setMode(mode);
    showPanel(panel,true);
  }
  for (const btn of switches) btn.onclick = () => setView(btn.dataset.mode);
  for (const btn of nav) btn.onclick = () => showPanel(btn.dataset.panel);
  byId('native-find-similar').onclick = () => {
    if (shownMedia.occurrence) showPanel('similar',true,{occurrence:shownMedia.occurrence,title:shownMedia.title});
  };
  function finish(message) {
    assist.forget();
    token = undefined; clearTimeout(timer); clearInterval(collectionTimer);
    flow?.setEnabled(false); home?.hide(); home?.clear(); collections?.clear(); similar?.clear();
    if (pendingControl) pendingControl.reject(Error(message));
    pendingControl = null;
    browserAction = undefined; browserNotice.textContent = '';
    byId('native-library-results').replaceChildren();
    byId('native-library-query').value = '';
    byId('native-controls').hidden = true; byId('pairing').hidden = true; note.textContent = message;
    if (consoleView) consoleView.clear(); else output.textContent = '';
    byId('native-text').value = '';
  }
  async function api(path, auth, data = {}, signal) {
    const response = await fetch('/api/' + path, {
      method:'POST', credentials:'omit', cache:'no-store', redirect:'error', referrerPolicy:'same-origin', keepalive:path === 'close',
      headers:{'Content-Type':'application/json', Authorization:'Bearer ' + auth}, body:JSON.stringify(data), signal,
    });
    if (path === 'homepage-image' && response.ok) return response.blob();
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Mariana could not complete this request.');
    return result;
  }
  function clock(sec) {
    if (!Number.isFinite(sec)) return '–';
    const total = Math.max(0, Math.floor(sec));
    const mins = Math.floor(total / 60), seconds = String(total % 60).padStart(2,'0');
    return mins < 60 ? mins + ':' + seconds : Math.floor(mins / 60) + ':' + String(mins % 60).padStart(2,'0') + ':' + seconds;
  }
  function showPending(message) {
    pending.textContent = message;
    byId('native-intent-status').textContent = message;
    home?.setPending?.(message);
  }
  function lock(locked) {
    if (locked) assist.dismiss();
    busy = locked;
    for (const control of commands) control.disabled = locked;
    collections?.setBusy(locked); flow?.setBusy(locked); home?.setBusy?.(locked); similar?.setBusy?.(locked);
    for (const control of byId('native-library-results').querySelectorAll('button')) control.disabled = locked;
    byId('native-find-similar').disabled = locked || byId('native-find-similar').hidden;
  }
  function drawSession(state) {
    const status = state?.mode === 'session' ?
      (state.shareOutput ? 'Approved for this session · Command output shared' : 'Approved for this session · Command output stays in Mariana') :
      'Terminal review for commands beyond transport';
    if (approval.textContent !== status) approval.textContent = status;
    sessionTime.textContent = Number.isFinite(state?.expirySeconds) ? 'Session time left ' + clock(state.expirySeconds) : '';
    revoke.hidden = state?.mode !== 'session';
  }
  function applyBrowserAction(action, value) {
    if (action === 'view') {
      if (!['console','flow'].includes(value)) return 'Unknown browser view.';
      setView(value);
      return;
    }
    if (action === 'focus') {
      const targets = new Map([
        ['command',busy ? 'commands-title' : 'native-text'],
        ['search','native-find'], ['library','native-library-query'], ['now','native-title'],
      ]);
      const id = targets.get(value);
      if (!id) return 'Unknown browser focus target.';
      if (value === 'library' && !capabilities.library) return 'This tab has not enabled native library browsing.';
      if (['library','now','search'].includes(value) && document.body.dataset.mode === 'console') setView('flow');
      if (value === 'library') showPanel('library');
      if (['command','search'].includes(value) && document.body.dataset.mode === 'flow') showPanel('commands');
      const target = byId(id);
      target.focus();
      target.scrollIntoView({block:'center'});
      return;
    }
    if (action === 'notice') {
      if (typeof value !== 'string' || !value.trim() || value.length > 500) return 'Invalid terminal message.';
      browserNotice.textContent = value;
      return;
    }
    if (action === 'draft') {
      if (busy) return 'Wait for the current command to finish before drafting another.';
      if (typeof value !== 'string' || !value.trim() || value.length > 2048 || /[\r\n\0]/.test(value))
        return 'Invalid command draft.';
      if (document.body.dataset.mode === 'flow') showPanel('commands');
      assist.dismiss();
      editor.value = value;
      editor.focus();
      editor.setSelectionRange(value.length,value.length);
      editor.scrollIntoView({block:'center'});
      return;
    }
    if (action === 'library') {
      if (!capabilities.library) return 'This tab has not enabled native library browsing.';
      if (document.body.dataset.mode === 'console') setView('flow');
      showPanel('library');
      if (typeof value !== 'string' || value.length > 160 || /[\r\n\0]/.test(value))
        return 'Invalid library search.';
      const query = byId('native-library-query');
      query.value = value;
      query.focus();
      query.scrollIntoView({block:'center'});
      void readLibrary(0);
      return;
    }
    if (action === 'clear' && (value == null || value === '')) {
      if (consoleView) consoleView.clear(); else output.textContent = '';
      return;
    }
    return 'Unsupported browser action.';
  }
  function receiveBrowserAction(event, auth) {
    if (!event || typeof event.id !== 'string' || !/^[\w-]{1,96}$/.test(event.id)) return;
    if (event.id !== browserAction?.id) {
      browserAction = {id:event.id, error:applyBrowserAction(event.action,event.value)};
    }
    const action = browserAction;
    if (action.sending || action.acknowledged) return;
    action.sending = true;
    void api('browser-ack', auth, {id:action.id,error:action.error}).then(() => {
      action.acknowledged = true;
    }, () => {
      // A later state poll retries delivery of the acknowledgement only.
      action.sending = false;
    });
  }
  function draw(result) {
    const state = result.playback || {}, job = result.job;
    shownMedia = state;
    const canFind = capabilities.similarity && state.occurrence && state.source === 'local' && state.library_index;
    byId('native-find-similar').hidden = !canFind;
    byId('native-find-similar').disabled = busy || !canFind;
    for (const key of ['accent','panel','text','muted','background','border','glow']) {
      const color = state.palette?.[key];
      if (/^#[a-f0-9]{6}(?:[a-f0-9]{2})?$/i.test(color || '')) document.documentElement.style.setProperty('--' + key,color);
    }
    byId('native-title').textContent = state.title || 'Nothing playing';
    byId('native-artist').textContent = state.artist || '';
    byId('native-position').textContent = [state.display_state,
      state.queue_position && 'Queue ' + state.queue_position + ' of ' + state.queue_count].filter(Boolean).join(' · ');
    flow?.update(state);
    consoleView?.setPlayback(state);
    if (!job || submitting || (expectedId && job.id !== expectedId)) return;
    if (job.state !== 'done') {
      lock(true); showPending(job.state === 'review' ? 'Review the command in your Mariana terminal.' : 'Running in Mariana…');
    } else {
      if (lastJob !== job.id) {
        if (consoleView) consoleView.appendJob(job);
        else {
          output.textContent = (output.textContent + '\n› ' + job.command + '\n' + job.output).trimStart().slice(-64000);
          output.scrollTop = output.scrollHeight;
        }
        if (collectionPanels.has(panel) && document.body.dataset.mode === 'flow') void collections?.refresh();
        if (panel === 'similar' && document.body.dataset.mode === 'flow' && job.command === 'similar scan --limit 12')
          similar?.refresh();
      }
      if (pendingControl?.id === job.id) {
        const settled = pendingControl; pendingControl = null;
        if (job.ok === true) settled.resolve(); else settled.reject(Error(job.output || 'Control failed.'));
      }
      const restoreFocus = busy && (document.activeElement === document.body || document.activeElement === editor);
      lastJob = job.id; expectedId = null; lock(false); showPending('');
      if (restoreFocus) consoleView?.focus();
    }
  }
  let pollVersion = 0, submitting = false, expectedId = null, pendingControl = null;
  async function poll() {
    const version = pollVersion, policy = policyVersion, auth = token;
    try {
      const result = await api('state', auth);
      if (!token || token !== auth) return;
      if (version === pollVersion) draw(result);
      if (policy === policyVersion && !revoking) drawSession(result.session);
      receiveBrowserAction(result.browserAction, auth);
      timer = setTimeout(poll, busy ? 220 : 450);
    } catch (error) {
      if (token) finish('Connection ended. Run web session in Mariana to reconnect. ' + error.message);
    }
  }
  async function submitJob(endpoint, payload) {
    if (!token || busy) throw Error('Wait for the current request to finish.');
    const auth = token;
    lock(true); pollVersion++; submitting = true;
    try {
      const acknowledgement = await api(endpoint, auth, payload);
      if (token !== auth) throw Error('The connection ended.');
      expectedId = acknowledgement.id;
      showPending('Sent to Mariana.');
      return expectedId;
    } catch (error) { lock(false); throw error; }
    finally { submitting = false; }
  }
  async function send(command, remember=false, libraryKey, collectionAction) {
    if (!token || busy || !command.trim()) return;
    try {
      await submitJob('command', {command, libraryKey, collectionAction});
      if (remember) assist.remember(command);
      if (editor.value.trim() === command) editor.value = '';
    } catch (error) { showPending(error.message); }
  }
  async function sendControl(payload) {
    const id = await submitJob('control', payload);
    return new Promise((resolve,reject) => { pendingControl = {id,resolve,reject}; });
  }
  const editor = byId('native-text');
  const assist = window.MarianaCommandInput.mount({
    input: editor, list: byId('native-suggestions'), status: byId('native-assist-status'), historyButton: byId('native-history'),
    suggest: async request => token && !busy ? (await api('assist', token, request)).suggestions : [],
  });
  byId('native-command').onsubmit = async event => {
    event.preventDefault();
    const line = editor.value, auth = token;
    if (!auth || busy || await assist.review()) return;
    if (auth === token && line === editor.value) await send(line.trim(), true);
  };
  for (const btn of byId('native-transport').querySelectorAll('button')) btn.onclick = () => {
    if (!flow?.transport(btn.dataset.command)) void send(btn.dataset.command);
  };
  setView(new URLSearchParams(location.search).get('view') === 'flow' ? 'flow' : 'console');
  let catalogOffset = 0;
  function suggest() {
    const query = byId('native-find').value.trim().toLowerCase();
    const category = byId('native-category').value;
    const results = byId('native-matches');
    const matching = catalog.filter(item => (!category || item.category === category) && item.keywords.includes(query));
    const entries = matching.slice(catalogOffset, catalogOffset+32);
    results.replaceChildren();
    for (const entry of entries) {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = entry.name; button.title = entry.summary;
      button.onclick = () => { editor.value = entry.name + ' '; editor.focus(); };
      results.append(button);
    }
    byId('native-catalog-count').textContent = matching.length
      ? (catalogOffset+1) + '–' + (catalogOffset+entries.length) + ' of ' + matching.length + ' command forms'
      : 'No matching commands.';
    byId('native-catalog-pages').hidden = matching.length <= 32;
    byId('native-catalog-prev').disabled = catalogOffset <= 0;
    byId('native-catalog-next').disabled = catalogOffset+32 >= matching.length;
  }
  let libraryOffset = 0, libraryVersion = 0;
  async function readLibrary(offset) {
    const auth = token, version = ++libraryVersion;
    const stat = byId('native-library-count'), page = byId('native-library-results');
    stat.textContent = 'Reading library…';
    try {
      const result = await api('library', auth, {query:byId('native-library-query').value,offset});
      if (auth !== token || version !== libraryVersion) return;
      if (!Array.isArray(result.rows)) throw Error('Library browsing is unavailable.');
      libraryOffset = offset;
      page.replaceChildren();
      for (const row of result.rows) {
        const li = document.createElement('li'), main = document.createElement('div');
        li.classList.toggle('similar-available', Boolean(capabilities.similarity));
        const title = document.createElement('strong'), detail = document.createElement('small');
        title.textContent = row.title; detail.textContent = row.detail;
        main.append(title, detail); li.append(main);
        const actions = [['Play','play'],['Queue','queue add']];
        if (capabilities.similarity) actions.push(['Similar','similar']);
        for (const [label, prefix] of actions) {
          const action = document.createElement('button');
          action.type = 'button'; action.textContent = label; action.disabled = busy;
          action.setAttribute('aria-label', label + ' ' + row.title);
          action.onclick = prefix === 'similar'
            ? () => showPanel('similar',true,{number:row.number,key:row.key,title:row.title})
            : () => void send(prefix + ' ' + row.number, true, row.key);
          li.append(action);
        }
        page.append(li);
      }
      stat.textContent = result.total ? (offset+1) + '–' + (offset+result.rows.length) + ' of ' + result.total : 'No matching recordings.';
      byId('native-library-pages').hidden = result.total <= 40;
      byId('native-library-prev').disabled = offset === 0;
      byId('native-library-next').disabled = offset + 40 >= result.total;
    } catch (error) {
      if (auth === token && version === libraryVersion) stat.textContent = error.message;
    }
  }
  byId('native-library-form').onsubmit = event => { event.preventDefault(); void readLibrary(0); };
  byId('native-library-prev').onclick = () => void readLibrary(Math.max(0,libraryOffset-40));
  byId('native-library-next').onclick = () => void readLibrary(libraryOffset+40);
  for (const input of [byId('native-find'),byId('native-category')])
    input.oninput = () => { catalogOffset = 0; suggest(); };
  byId('native-catalog-prev').onclick = () => { catalogOffset = Math.max(0,catalogOffset-32); suggest(); };
  byId('native-catalog-next').onclick = () => { catalogOffset += 32; suggest(); };
  byId('pair').disabled = !invitation;
  if (!invitation) note.textContent = 'Run web session at the Mariana prompt and open its private invitation.';
  byId('pair').onclick = async () => {
    byId('pair').disabled = true;
    try {
      const result = await api('pair', invitation, {library:byId('share-native-library').checked});
      token = result.token;
      for (const entry of result.catalog) {
        const names = new Set([entry.canonical, ...(entry.forms || []).filter(f=>f.tokens.length).map(f=>[entry.canonical,...f.tokens].join(' '))]);
        for (const name of names) catalog.push({name,summary:entry.summary,category:entry.category,
          keywords:[name,entry.summary,entry.category,...entry.aliases].join(' ').toLowerCase()});
      }
      for (const category of [...new Set(catalog.map(entry => entry.category))].sort())
        byId('native-category').add(new Option(category,category));
      suggest();
      byId('pairing').hidden = true; byId('native-controls').hidden = false; note.textContent = '';
      capabilities = result;
      flow?.setEnabled(result.controls === true);
      showPanel(panelAvailable('home') ? 'home' : 'commands',true);
      drawSession(result.session);
      consoleView?.focus();
      await poll();
    } catch (error) { finish('Could not connect. Run web session again. ' + error.message); }
  };
  revoke.onclick = async () => {
    if (!token || revoking) return;
    const auth = token;
    policyVersion++;
    revoking = true;
    revoke.disabled = true;
    try {
      const result = await api('revoke', auth);
      if (token === auth) {
        drawSession(result.session);
        byId('disconnect').focus();
        note.textContent = 'Terminal review is active again.';
      }
    } catch (error) {
      if (token === auth) note.textContent = error.message;
    } finally {
      revoking = false;
      revoke.disabled = false;
    }
  };
  byId('disconnect').onclick = async () => {
    const auth = token;
    finish('Disconnected. You can continue in Mariana.');
    try { await api('close', auth); }
    catch { note.textContent = 'Tab disconnected. Return to Mariana with Ctrl+C if its connection is still open.'; }
  };
  globalThis.addEventListener?.('pagehide', () => {
    if (token) void api('close', token).catch(() => {});
  });
})();

(() => {
  'use strict';
  const key = window.MarianaProfiles?.key('mariana.strudel.draft.1') ?? 'mariana.strudel.draft.1';
  const help = 'strudel · strudel render [full] · strudel play [full] · strudel queue [full] · strudel live [online] · strudel stop · strudel list · strudel new NAME · strudel show NAME · strudel save NAME · strudel import · strudel export · strudel delete NAME --yes';
  const maxWavBytes = 16 * 1024 * 1024;

  function projectID(rawName) {
    const name = String(rawName ?? '').trim();
    if (!name || name.length > 48 || /[\x00-\x1f\x7f]/.test(name)) throw Error('Use a project name of 1 to 48 printable characters.');
    return {name, id:key + ':' + name.toLowerCase()};
  }

  function openLibrary() {
    return new Promise((resolve, reject) => {
      if (!globalThis.indexedDB) {
        reject(Error('This browser cannot store projects. Use Download source.'));
        return;
      }
      const request = indexedDB.open('mariana-strudel-projects', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('projects', {keyPath:'id'});
      request.onsuccess = () => resolve(request.result);
      request.onerror = request.onblocked = () => reject(Error('Could not open project storage.'));
    });
  }

  async function projectOperation(operation, id, draft, expected) {
    const db = await openLibrary();
    try {
      return await new Promise((resolve, reject) => {
        const writes = ['new', 'save', 'delete'].includes(operation);
        const tx = db.transaction('projects', writes ? 'readwrite' : 'readonly');
        const store = tx.objectStore('projects');
        const request = operation === 'list' ? store.getAll() : store.get(id);
        let result, failure;
        tx.onabort = tx.onerror = () => reject(Error(failure || 'The project operation did not complete.'));
        tx.oncomplete = () => resolve(result);
        request.onsuccess = () => {
          const existing = request.result;
          if (operation === 'list') {
            result = existing.filter(project => project.profile === key).sort((a,b) => a.name.localeCompare(b.name));
            return;
          }
          if (operation === 'new' && existing) failure = 'A project with that name exists. Use strudel show to open it.';
          if (operation !== 'new' && !existing) failure = 'Unknown project. Use strudel list.';
          if (operation === 'save' && existing?.revision !== expected) failure = 'The saved revision changed. Open it with strudel show before saving again.';
          if (failure) { tx.abort(); return; }
          result = existing;
          if (operation === 'save' || operation === 'new') {
            result = {...draft, revision:(existing?.revision || 0) + 1, id, profile:key};
            store.put(result);
          } else if (operation === 'delete') store.delete(id);
        };
      });
    } finally { db.close(); }
  }

  function upstreamURL(source) {
    const bytes = new TextEncoder().encode(source);
    let text = '';
    for (const byte of bytes) text += String.fromCharCode(byte);
    return 'https://strudel.cc/#' + btoa(text);
  }

  function connectEngine(frame, action, code, seconds, signal) {
    const nonce = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
    const href = new URL('strudel-runtime/index.html', document.baseURI);
    href.hash = nonce;
    return new Promise((resolve, reject) => {
      let sent = false;
      function finish(error, value) {
        clearTimeout(deadline);
        signal.removeEventListener('abort', aborted);
        window.removeEventListener('message', receive);
        if (error) reject(error); else resolve(value);
      }
      function aborted() { finish(Error('Strudel stopped.')); }
      function receive(event) {
        const data = event.data;
        if (event.source !== frame.contentWindow || event.origin !== 'null' || data?.nonce !== nonce) return;
        if (data.type === 'ready' && !sent) {
          sent = true;
          frame.contentWindow.postMessage({nonce, action, code, seconds}, '*');
        } else if (sent && data.type === 'error') {
          finish(Error(String(data.message || 'Strudel failed.').slice(0,240)));
        } else if (sent && data.type === 'live-ready' && action === 'live') {
          finish(null, true);
        } else if (sent && data.type === 'rendered' && action === 'render') {
          const bytes = data.buffer;
          if (!(bytes instanceof ArrayBuffer) || bytes.byteLength < 44 || bytes.byteLength > maxWavBytes
            || new DataView(bytes).getUint32(0) !== 0x52494646 || new DataView(bytes).getUint32(8) !== 0x57415645) {
            finish(Error('Strudel sent an invalid WAV.'));
            return;
          }
          finish(null, new Blob([bytes], {type:'audio/wav'}));
        }
      }
      const deadline = setTimeout(() => finish(Error('Strudel did not respond. Confirm the full engine is installed.')), action === 'live' ? 14000 : 90000);
      signal.addEventListener('abort', aborted, {once:true});
      window.addEventListener('message', receive);
      frame.src = href.href;
      if (signal.aborted) aborted();
    });
  }

  function mount(get, enqueue, pausePlayer) {
    const engine = globalThis.MarianaStrudelPattern;
    const source = get('strudel-source'), seconds = get('strudel-seconds'), status = get('strudel-status');
    const player = get('strudel-audio'), result = get('strudel-result'), download = get('strudel-wav');
    const sourceLink = get('strudel-download'), share = get('strudel-share'), picker = get('strudel-import');
    let active, file, url, sourceURL, running, liveFrame, openedProject, importVersion = 0;
    const phone = globalThis.MarianaNativeShell === 'ios' || location.hostname === 'app.mariana.invalid';
    const host = document.createElement('div');
    host.hidden = true;
    host.className = 'strudel-live-host';
    const controls = document.createElement('div');
    controls.className = 'controls';
    function studioButton(title, args) {
      const element = document.createElement('button');
      element.type = 'button';
      element.textContent = title;
      element.onclick = async () => {
        try { note(await command(args)); }
        catch (error) { note(error.message); }
      };
      return element;
    }
    controls.append(studioButton('Live editor', ['live']), studioButton('Render full WAV', ['render','full']),
      studioButton('Stop', ['stop']), studioButton('Open Strudel online', ['live','online']));
    if (!phone) status.before(controls, host);
    const note = text => { status.textContent = text; };
    try {
      const draft = JSON.parse(localStorage.getItem(key));
      if (typeof draft?.source === 'string' && new TextEncoder().encode(draft.source).length <= engine.maxBytes) {
        source.value = draft.source;
        if (Number.isInteger(draft.seconds) && draft.seconds >= 1 && draft.seconds <= 60) seconds.value = String(draft.seconds);
      }
    } catch { /* The starter is available when browser storage is disabled. */ }
    function stopEngine() {
      running?.abort();
      running = null;
      liveFrame?.remove();
      liveFrame = null;
      host.hidden = true;
    }
    function invalidate() {
      stopEngine();
      active?.abort(); active = null; file = null;
      if (url) {
        player.pause(); player.removeAttribute('src'); player.load(); URL.revokeObjectURL(url); url = '';
      }
      result.hidden = true; download.removeAttribute('href');
    }
    function updateSourceLink() {
      if (sourceURL) URL.revokeObjectURL(sourceURL);
      sourceURL = URL.createObjectURL(new Blob([source.value], {type:'text/plain;charset=utf-8'}));
      sourceLink.href = sourceURL;
    }
    function edited() {
      importVersion++; invalidate(); updateSourceLink();
      if (new TextEncoder().encode(source.value).length > engine.maxBytes) {
        note('The editor accepts up to 64 KiB of UTF-8 text. Shorten the source to save this draft.');
        return;
      }
      try {
        localStorage.setItem(key, JSON.stringify({source:source.value, seconds:Number(seconds.value)}));
        note('Draft saved on this device.');
      } catch { note('This device could not save the draft. Keep a copy of the source.'); }
    }
    function sharing() {
      download.hidden = sourceLink.hidden = phone;
      share.disabled = !file || !globalThis.MarianaClipShare.available(file);
    }
    function frame(label, online = false) {
      const element = document.createElement('iframe');
      element.title = label;
      element.sandbox = online ? 'allow-scripts allow-same-origin' : 'allow-scripts';
      element.allow = 'autoplay';
      element.referrerPolicy = 'no-referrer';
      element.width = '100%';
      element.height = online ? '520' : '360';
      return element;
    }
    async function fullEngine(action, request) {
      if (phone) throw Error('Use the full Strudel engine in a desktop browser. This app includes the offline preview.');
      const code = source.value, length = Number(seconds.value);
      if (new TextEncoder().encode(code).length > engine.maxBytes) throw Error('Choose a pattern of at most 64 KiB.');
      if (!Number.isInteger(length) || length < 1 || length > 60) throw Error('Use 1 to 60 whole seconds.');
      const asset = await fetch(new URL('strudel-engine.json', document.baseURI), {signal:request.signal}).catch(() => null);
      if (request.signal.aborted) throw Error('Strudel stopped.');
      if (!asset?.ok || (await asset.json().catch(() => null))?.full !== true) {
        throw Error('Full Strudel is not installed in this build. Use “Open Strudel online” or build the engine from the checkout.');
      }
      if (request.signal.aborted) throw Error('Strudel stopped.');
      const element = frame('Isolated Strudel editor');
      liveFrame = element;
      running = request;
      host.hidden = action !== 'live';
      host.appendChild(element);
      return connectEngine(element, action, code, length, request.signal);
    }
    async function live(online) {
      if (phone) throw Error('Open Flow in a desktop browser to use the Strudel live editor.');
      const code = source.value;
      if (new TextEncoder().encode(code).length > engine.maxBytes) throw Error('Choose a pattern of at most 64 KiB.');
      invalidate();
      const request = new AbortController();
      running = request;
      try {
        if (online) {
          const element = frame('Online Strudel editor', true);
          element.src = upstreamURL(code);
          liveFrame = element;
          host.hidden = false;
          host.appendChild(element);
          pausePlayer();
          return 'Online Strudel opened below. Press Play there.';
        }
        note('Opening the Strudel editor…');
        await fullEngine('live', request);
        if (request.signal.aborted) return 'Strudel stopped.';
        pausePlayer();
        return 'Strudel is ready. Press Play in the editor below.';
      } catch (error) {
        if (running === request) stopEngine();
        throw error;
      }
    }
    async function build(full = false) {
      invalidate();
      const request = new AbortController(); active = request;
      note(full ? 'Rendering with Strudel…' : 'Rendering the oscillator preview…');
      try {
        const blob = full ? await fullEngine('render', request) : await engine.render(source.value, Number(seconds.value), request.signal);
        if (request.signal.aborted) return false;
        file = new File([blob], 'mariana-pattern.wav', {type:'audio/wav'});
        url = URL.createObjectURL(file); player.src = url; download.href = url;
        result.hidden = false; sharing(); note('Preview ready.'); return true;
      } catch (error) {
        if (!request.signal.aborted) note(error.message);
        return false;
      } finally {
        if (active === request) {
          active = null;
          if (full) stopEngine();
        }
      }
    }
    function showProject(project) {
      openedProject = project;
      source.value = project.source;
      seconds.value = String(project.seconds);
      edited();
      return project.name + ' · revision ' + project.revision;
    }
    async function projectCommand(verb, args) {
      if (verb === 'list' && args.length === 0) {
        const projects = await projectOperation('list');
        return projects.map(project => project.name + ' · revision ' + project.revision).join('\n') || 'No saved projects. Use strudel new NAME.';
      }
      if (verb === 'import' && args.length === 0) { picker.click(); return 'Choose a UTF-8 Strudel source file.'; }
      if (verb === 'export' && args.length === 0) {
        if (sourceLink.hidden) return 'Use Copy source on this device.';
        sourceLink.click();
        return 'Downloading the current source as mariana-pattern.js.';
      }
      if (verb === 'delete' && args.length === 1) return 'Confirm with strudel delete NAME --yes.';
      if (args.length !== 1 && !(verb === 'delete' && args.length === 2 && args[1] === '--yes')) return help;
      const {id, name} = projectID(args[0]);
      if (verb === 'delete') {
        const removed = await projectOperation('delete', id);
        if (openedProject?.id === id) openedProject = null;
        return 'Deleted ' + removed.name + '. Its source remains in the editor.';
      }
      if (verb === 'new') {
        return showProject(await projectOperation('new', id, {name, source:source.defaultValue, seconds:8}));
      }
      if (verb === 'show') return showProject(await projectOperation('show', id));
      if (verb === 'save') {
        if (openedProject?.id !== id) return 'Open the project with strudel show NAME, or create it with strudel new NAME.';
        const length = Number(seconds.value);
        if (!Number.isInteger(length) || length < 1 || length > 60) throw Error('Use 1 to 60 whole seconds.');
        if (new TextEncoder().encode(source.value).length > engine.maxBytes) throw Error('Choose a pattern of at most 64 KiB.');
        const revision = openedProject.revision;
        const saved = await projectOperation('save', id, {name:openedProject.name, source:source.value, seconds:length}, revision);
        // A slow save must not reload its snapshot over later edits or a different project.
        if (openedProject?.id === id && openedProject.revision === revision) openedProject = saved;
        return saved.name + ' saved · revision ' + saved.revision;
      }
      return help;
    }
    const projectCommands = new Set(['list','new','show','save','delete','import','export']);
    async function command(args) {
      const verb = args[0]?.toLowerCase() ?? '';
      if (projectCommands.has(verb)) return projectCommand(verb, args.slice(1));
      const mode = args[1]?.toLowerCase();
      if (args.length > 2 || (mode !== undefined && !(verb === 'live' ? mode === 'online' : ['play','render','queue'].includes(verb) && mode === 'full'))) return help;
      const full = mode === 'full';
      switch (verb) {
        case '': source.focus(); source.scrollIntoView({block:'center'}); return 'Strudel editor opened.';
        case 'live': return live(mode === 'online');
        case 'stop': invalidate(); return 'Strudel stopped.';
        case 'render': await build(full); return status.textContent;
        case 'play': {
          if ((!file || full) && !await build(full)) return status.textContent;
          pausePlayer();
          try { await player.play(); return 'Playing the rendered pattern.'; }
          catch { return 'Use Play in the Strudel audio controls.'; }
        }
        case 'queue': {
          if ((!file || full) && !await build(full)) return status.textContent;
          return enqueue(file);
        }
        default: return help;
      }
    }
    source.addEventListener('input', edited); seconds.addEventListener('input', edited);
    picker.onchange = async event => {
      const input = event.target, selected = input.files[0], version = ++importVersion; input.value = '';
      if (!selected) return;
      try {
        if (selected.size > engine.maxBytes + 3) throw Error('Choose a UTF-8 source file of up to 64 KiB.');
        const text = new TextDecoder('utf-8', {fatal:true}).decode(await selected.arrayBuffer());
        if (new TextEncoder().encode(text).length > engine.maxBytes) throw Error('Choose a UTF-8 source file of up to 64 KiB.');
        if (version !== importVersion) return;
        source.value = text; edited();
      } catch (error) { if (version === importVersion) note(error.message); }
    };
    get('strudel-copy').onclick = async () => {
      try { await navigator.clipboard.writeText(source.value); note('Source copied.'); }
      catch { source.focus(); source.select(); note('Source selected. Use your device’s Copy action.'); }
    };
    get('strudel-render').onclick = () => build();
    get('strudel-queue').onclick = async () => {
      try { note(await command(['queue'])); } catch (error) { note(error.message); }
    };
    share.onclick = async () => {
      try { if (file) await globalThis.MarianaClipShare.share(file, 'system', Number(seconds.value)); }
      catch (error) { if (error.name !== 'AbortError') note(error.message); }
    };
    player.addEventListener('play', pausePlayer);
    window.addEventListener('mariana-clip-share-ready', sharing);
    updateSourceLink(); sharing();
    return {command, stopPreview:() => { player.pause(); stopEngine(); }};
  }
  globalThis.MarianaStrudel = {mount};
})();

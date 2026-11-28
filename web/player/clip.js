(() => {
  'use strict';
  const help = 'clip · clip start [TIME] · clip end [TIME] · clip range START END · clip status · clip link [TIME] · clip social · clip clear · clip export [--format wav|story|video] · clip share';
  const rounded = n => String(Math.round(n * 1000) / 1000);
  const stamp = n => {
    const ms = Math.round(n * 1000);
    return Math.floor(ms / 60000) + ':' + String(Math.floor(ms / 1000) % 60).padStart(2, '0') + '.' + String(ms % 1000).padStart(3, '0');
  };

  function mount(get, state, localBlob, pausePlayer) {
    const panel = get('clip-panel'), openButton = get('clip-open'), note = get('clip-status');
    const start = get('clip-start'), end = get('clip-end'), format = get('clip-format');
    const preview = get('clip-preview'), save = get('clip-download'), share = get('clip-share');
    const markStart = get('clip-mark-start'), markEnd = get('clip-mark-end'), build = get('clip-build');
    const length = get('clip-length'), bar = get('clip-selection'), target = get('clip-target');
    let item = null, duration = NaN, ready = null, objectUrl = '', job = null, defaultRange = true;

    async function destinations(file, seconds) {
      const host = globalThis.MarianaClipShare.host();
      get('clip-target-label').hidden = !host;
      if (!host) return;
      target.replaceChildren(new Option('All apps · system share sheet', 'system'));
      try {
        const rows = await globalThis.MarianaClipShare.targets(file, seconds, format.value === 'story');
        if (ready !== file) return;
        for (const row of rows) {
          const option = new Option(row.name + (row.reason ? ' · ' + row.reason : ''), row.id);
          option.disabled = Boolean(row.reason); target.add(option);
        }
      } catch { /* System handoff remains available if the app list changes. */ }
    }
    function resetExport() {
      job?.abort(); job = null; ready = null;
      if (objectUrl) { preview.pause(); preview.removeAttribute('src'); preview.load(); URL.revokeObjectURL(objectUrl); }
      objectUrl = ''; save.removeAttribute('href'); get('clip-result').hidden = true;
      build.disabled = !Number.isFinite(duration); build.textContent = 'Prepare clip';
    }
    function limits() { return globalThis.MarianaClipMedia.range(start.value, end.value, duration); }
    function updateRange() {
      try {
        const {from, to} = limits();
        length.textContent = stamp(to - from);
        bar.style.setProperty('--in', (from * 100 / duration) + '%');
        bar.style.setProperty('--out', (to * 100 / duration) + '%');
        build.disabled = Boolean(job);
      } catch {
        length.textContent = '—'; build.disabled = true;
        bar.style.setProperty('--in', '0%'); bar.style.setProperty('--out', '0%');
      }
    }
    function changed() { defaultRange = false; resetExport(); note.textContent = ''; updateRange(); }
    function resetRange(position = 0) {
      defaultRange = true; resetExport();
      if (!Number.isFinite(duration) || duration <= 0) { start.value = ''; end.value = ''; }
      else {
        const from = Math.min(Math.max(0, position), Math.max(0, duration - Math.min(15, duration)));
        start.value = rounded(from); end.value = rounded(Math.min(duration, from + 15));
      }
      note.textContent = ''; updateRange();
    }
    const phone = globalThis.location?.hostname === 'app.mariana.invalid' || globalThis.MarianaNativeShell === 'ios';
    function publicSource() {
      return globalThis.MarianaClipMedia.youtubeLink(item?.url, defaultRange ? state().position : Number(start.value)) ||
        globalThis.MarianaPublicLink?.(item?.url);
    }
    async function phoneSocial() {
      const url = publicSource();
      if (!url) {
        panel.hidden = false;
        get('clip-public-form').hidden = false;
        get('clip-public-input').focus();
        return 'Paste a public music link to choose a destination.';
      }
      await globalThis.MarianaClipShare.shareLink(url);
      return 'Choose a destination in the system share sheet.';
    }
    function sync() {
      const s = state();
      const d = s.item && Number.isFinite(s.duration) && s.duration > 0 ? s.duration : NaN;
      if (s.item !== item || !Object.is(d, duration)) {
        const changedItem = item !== s.item;
        item = s.item; duration = d;
        if (changedItem || !start.value || !Number.isFinite(d)) resetRange(s.position || 0);
        else { resetExport(); updateRange(); }
        get('clip-source').textContent = item?.title || 'Load a recording to start.';
        const social = get('clip-social');
        if (social && phone) {
          social.removeAttribute('target');
          social.onclick = event => {
            event.preventDefault();
            phoneSocial().then(message => { note.textContent = message; }, error => { note.textContent = error.message; });
          };
        }
        if (social && !phone) social.onfocus = social.onpointerdown = () => {
          const url = globalThis.MarianaClipMedia.youtubeLink(item?.url, defaultRange ? state().position : Number(start.value));
          social.href = 'share-link.html' + (url ? '#' + encodeURIComponent(url) : '');
        };
        get('clip-link').hidden = !globalThis.MarianaClipMedia.youtubeLink(item?.url, 0);
        get('clip-fieldset').disabled = !Number.isFinite(d);
        if (item && !Number.isFinite(d)) note.textContent = 'Clip selection requires a loaded recording with a known duration.';
      }
      openButton.disabled = !s.item;
    }
    function open() {
      sync();
      if (!item) throw Error('Load a recording before opening the clip editor.');
      if (panel.hidden) {
        panel.hidden = false;
        if (defaultRange && Number.isFinite(duration)) resetRange(state().position || 0);
      }
      openButton.setAttribute('aria-expanded', 'true');
      get('clip-title').focus(); panel.scrollIntoView?.({block:'nearest'});
    }
    function mark(field, value) {
      sync();
      if (!Number.isFinite(duration)) throw Error('Load a finite recording before setting a mark.');
      const n = globalThis.MarianaClipMedia.seconds(value ?? state().position);
      if (n > duration + .001) throw Error('The mark is outside this recording.');
      field.value = rounded(Math.min(n, duration)); changed();
      return (field === start ? 'In' : 'Out') + ' set to ' + stamp(n) + '.';
    }
    async function prepare() {
      sync();
      const {from, to} = limits();
      const story = format.value === 'story';
      const original = format.value === 'video', video = story || original;
      if (video && to - from > 90.001) throw Error('Choose up to 90 seconds for video export.');
      resetExport();
      const operation = new AbortController(), source = item;
      job = operation; build.disabled = true;
      const timeout = setTimeout(() => operation.abort(), (video ? 150 : 55) * 1000);
      let context;
      try {
        if (video) {
          if (!globalThis.MarianaClipStory.codec()) throw Error('Choose Audio clip in this browser.');
          const Audio = globalThis.AudioContext || globalThis.webkitAudioContext;
          context = new Audio();
          let resumeTimer;
          try {
            await Promise.race([context.resume(), new Promise((_, reject) => {
              resumeTimer = setTimeout(() => reject(Error('Tap Prepare clip to enable video audio in this browser.')), 3500);
            })]);
          } finally { clearTimeout(resumeTimer); }
        }
        note.textContent = 'Reading the selected recording…';
        const blob = source.url ? await globalThis.MarianaClipMedia.retrieve(source.url, operation.signal) : await localBlob(source);
        if (job !== operation) return '';
        let exportBlob;
        if (original) {
          if (!blob) throw Error('Add the original video file to your library again.');
          note.textContent = 'Rendering original video. Keep this tab open.';
          exportBlob = await globalThis.MarianaClipStory.original(blob, from, to, context, operation.signal);
        } else {
          exportBlob = await globalThis.MarianaClipMedia.render(blob, from, to, duration, operation.signal);
        }
        if (job !== operation) return '';
        if (story) {
          note.textContent = 'Rendering a ' + rounded(to - from) + '-second portrait video. Keep this tab open.';
          const colors = {};
          for (const name of ['background','panel','text','muted','accent'])
            colors[name] = getComputedStyle(document.documentElement).getPropertyValue('--' + name).trim();
          exportBlob = await globalThis.MarianaClipStory.record(exportBlob, source.title, colors, context, operation.signal);
        }
        if (job !== operation || operation.signal.aborted) return '';
        const ext = exportBlob.type === 'video/webm' ? 'webm' : exportBlob.type === 'video/mp4' ? 'mp4' : 'wav';
        const stem = String(source.title || 'Mariana').replace(/\.[a-z0-9]{2,5}$/i, '').replace(/[^\p{L}\p{N} _.-]/gu, '').slice(0, 64).trim() || 'Mariana';
        ready = new File([exportBlob], stem + '-' + rounded(from) + '-' + rounded(to) + '.' + ext, {type:exportBlob.type});
        objectUrl = URL.createObjectURL(ready);
        save.href = objectUrl; save.download = ready.name; preview.src = objectUrl;
        preview.classList.toggle('clip-portrait', video);
        get('clip-result').hidden = false;
        share.disabled = !globalThis.MarianaClipShare.available(ready);
        await destinations(ready, to - from);
        if (job !== operation) return '';
        save.hidden = Boolean(globalThis.MarianaClipShare.host() || globalThis.MarianaNativeShell === 'ios' ||
          globalThis.location?.hostname === 'app.mariana.invalid');
        note.textContent = share.disabled ?
          (save.hidden ? 'File handoff is unavailable in this WebView. Open Mariana in a browser to save or share.' : 'Clip ready. Download it to use in another app.') :
          'Clip ready. Preview it or choose an app to share it with.';
        return note.textContent;
      } catch (error) {
        if (job !== operation) return '';
        throw Error(operation.signal.aborted ? 'Clip preparation timed out. Try a shorter selection or a local recording.' : error.message);
      } finally {
        clearTimeout(timeout);
        if (context && context.state !== 'closed') await context.close().catch(() => {});
        if (job === operation) { job = null; updateRange(); }
      }
    }
    async function handoff() {
      if (!ready) throw Error('Prepare the clip first, then choose Share clip.');
      try {
        const {from, to} = limits(), choice = globalThis.MarianaClipShare.host() ? (target.value || 'system') : 'system';
        await globalThis.MarianaClipShare.share(ready, choice, to - from, format.value === 'story');
        return choice === 'system' ? 'Clip handed to the share sheet.' : 'Clip handed to the selected app.';
      }
      catch (error) { if (error.name === 'AbortError') return 'Sharing cancelled. Your clip is ready.'; throw error; }
    }
    function action(fn) {
      return async () => { try { const message = await fn(); if (message) note.textContent = message; }
        catch (err) { note.textContent = err.message; } };
    }
    openButton.onclick = action(open);
    get('clip-close').onclick = () => {
      resetExport(); panel.hidden = true; openButton.setAttribute('aria-expanded','false'); openButton.focus();
    };
    start.oninput = end.oninput = format.onchange = changed;
    markStart.onclick = action(() => mark(start)); markEnd.onclick = action(() => mark(end));
    build.onclick = action(prepare); share.onclick = action(handoff);
    const linkForm = get('clip-public-form');
    if (linkForm) linkForm.onsubmit = async event => {
      event.preventDefault();
      try {
        await globalThis.MarianaClipShare.shareLink(get('clip-public-input').value);
        note.textContent = 'Choose a destination in the system share sheet.';
      } catch (error) { note.textContent = error.message; }
    };
    get('clip-link').onclick = action(async () => {
      const url = globalThis.MarianaClipMedia.youtubeLink(item?.url, start.value || state().position || 0);
      if (!url) return 'No official YouTube link is available.';
      try { await navigator.clipboard.writeText(url); return 'Timestamp link copied.'; }
      catch { return url; }
    });
    preview.addEventListener('play', pausePlayer);
    window.addEventListener('mariana-clip-share-ready', () => { if (ready) { share.disabled = !globalThis.MarianaClipShare.available(ready); const {from,to} = limits(); void destinations(ready,to - from); } });
    const storyOption = get('clip-story-option');
    if (!globalThis.MarianaClipStory.codec()) { get('clip-video-option').disabled = true; storyOption.disabled = true; storyOption.textContent = 'Portrait video · unavailable in this browser'; }
    window.addEventListener('pagehide', resetExport);

    async function command(args) {
      const [cmd = '', ...rest] = args;
      if (cmd === 'help') return help;
      if (!cmd) { open(); return 'Clip editor opened.'; }
      sync();
      if (cmd === 'social' && !rest.length) {
        if (phone) return phoneSocial();
        const url = globalThis.MarianaClipMedia.youtubeLink(item?.url, defaultRange ? state().position : Number(start.value));
        const link = get('clip-social'); link.href = 'share-link.html' + (url ? '#' + encodeURIComponent(url) : '');
        link.click(); return 'Use the public music link composer to choose a destination.';
      }
      if (cmd === 'link' && rest.length < 2) {
        const time = globalThis.MarianaClipMedia.seconds(rest[0] ?? (start.value || state().position || 0));
        return globalThis.MarianaClipMedia.youtubeLink(item?.url, time) || 'No official YouTube link is available for this item.';
      }
      if (cmd === 'status') {
        if (!Number.isFinite(duration)) return 'Clip unavailable. Load a finite recording.';
        return (item.title || 'Recording') + ' · ' + start.value + '–' + end.value + ' s' + (ready ? ' · prepared' : '');
      }
      if (cmd === 'clear' && !rest.length) { resetRange(state().position); return 'Clip selection reset.'; }
      if (cmd === 'range' && rest.length === 2) {
        const r = globalThis.MarianaClipMedia.range(rest[0], rest[1], duration);
        start.value = rounded(r.from); end.value = rounded(r.to); changed();
        return 'Clip range ' + stamp(r.from) + '–' + stamp(r.to) + '.';
      }
      if ((cmd === 'start' || cmd === 'end') && rest.length < 2) return mark(cmd === 'start' ? start : end, rest[0]);
      if (cmd === 'export') {
        if (rest.length && !(rest.length === 2 && rest[0] === '--format' && ['wav','story','video'].includes(rest[1]))) return help;
        if (rest.length) format.value = rest[1];
        panel.hidden = false; openButton.setAttribute('aria-expanded', 'true');
        return prepare();
      }
      if (cmd === 'share' && !rest.length) {
        if (ready) return handoff();
        panel.hidden = false; openButton.setAttribute('aria-expanded', 'true');
        return prepare();
      }
      return help;
    }
    return {sync, command, stopPreview:() => { if (objectUrl && !preview.paused) preview.pause(); }};
  }
  globalThis.MarianaClips = {mount, help};
})();

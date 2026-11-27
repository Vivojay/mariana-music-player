/* Handoff is always initiated by an explicit user action. The OS supplies eligible apps. */
(() => {
  'use strict';
  let android = null, pending = null;
  if (globalThis.location?.origin === 'https://app.mariana.invalid') {
    window.addEventListener('message', event => {
      if ((event.source && event.source !== window) ||
          (event.origin && event.origin !== 'null' && event.origin !== location.origin) ||
          event.data !== 'MarianaClipPort' || !event.ports?.[0]) return;
      android?.close();
      pending?.reject(Error('The phone share channel was reset.'));
      android = event.ports[0];
      window.dispatchEvent(new Event('mariana-clip-share-ready'));
      android.onmessage = e => {
        if (!pending) return;
        if (e.data === 'ok') pending.resolve('ok');
        else if (String(e.data).startsWith('[')) {
          try { pending.resolve(JSON.parse(e.data)); } catch { pending.reject(Error('Invalid phone target list.')); }
        } else pending.reject(Error(String(e.data)));
      };
    });
  }
  function host() {
    if (android) return 'android';
    if (globalThis.MarianaNativeShell === 'ios' && globalThis.webkit?.messageHandlers?.marianaClip) return 'ios';
    return '';
  }
  function available(file) {
    if (host()) return true;
    try { return Boolean(navigator.share && navigator.canShare?.({files:[file]})); } catch { return false; }
  }
  async function post(platform, fields) {
    if (platform === 'ios') return globalThis.webkit.messageHandlers.marianaClip.postMessage(fields);
    if (pending) throw Error('A share is already being prepared.');
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending = null; reject(Error('The phone did not finish receiving this clip.')); }, 12000);
      const finish = fn => value => { clearTimeout(timer); pending = null; fn(value); };
      pending = {resolve:finish(resolve),reject:finish(reject)};
      try { android.postMessage(JSON.stringify(fields)); } catch (error) { pending.reject(error); }
    });
  }
  let busy = false;
  async function targets(file, seconds, portrait) {
    const platform = host();
    if (!platform) return [];
    const rows = await post(platform, {op:'targets', mime:file.type, seconds, portrait});
    return Array.isArray(rows) ? rows : [];
  }
  async function share(file, target = 'system', seconds = 0, portrait = false) {
    const platform = host();
    if (!platform) {
      if (!available(file)) throw Error('File sharing is unavailable in this browser. Download the clip to select it in another app.');
      await navigator.share({files:[file]}); return;
    }
    if (busy) throw Error('A share is already being prepared.');
    busy = true;
    try {
      await post(platform, {op:'start', name:file.name, mime:file.type, size:file.size, target, seconds, portrait});
      for (let offset = 0; offset < file.size; offset += 49152) {
        const bytes = new Uint8Array(await file.slice(offset, offset + 49152).arrayBuffer());
        let binary = '';
        for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
        await post(platform, {op:'chunk', data:btoa(binary)});
      }
      await post(platform, {op:'finish'});
    } catch (error) {
      try { await post(platform, {op:'cancel'}); } catch { /* Let the original error reach the caller. */ }
      throw error;
    } finally { busy = false; }
  }
  async function shareLink(raw) {
    const url = globalThis.MarianaPublicLink?.(raw);
    if (!url) throw Error('Choose an official public music link.');
    const platform = host();
    if (!platform) throw Error('The phone share sheet is not ready. Try again.');
    if (busy) throw Error('Finish sharing the current clip first.');
    await post(platform, {op:'link', url});
  }
  globalThis.MarianaClipShare = {available, share, host, targets, shareLink};
})();

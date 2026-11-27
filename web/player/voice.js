/* The remote conference runs on its own origin and is created only after Join. */
(() => {
  'use strict';
  const get = id => document.getElementById(id);
  const link = get('voice-link');
  const status = get('voice-status');
  const external = get('voice-external');
  const frameContainer = get('voice-frame');
  const nativeShell = window.MarianaNativeShell || location.hostname === 'app.mariana.invalid' || location.protocol === 'file:';

  const provider = new URL(window.MarianaMeetingOrigin || 'https://meet.jit.si').origin;
  const embedded = !nativeShell && provider !== 'https://meet.jit.si' && provider !== location.origin;
  get('voice-host').textContent = new URL(provider).host;
  link.placeholder = provider + '/…';

  function meetingLink(raw) {
    try {
      const url = new URL(raw.trim());
      if (url.origin !== provider || url.username || url.password || url.search || url.hash ||
          !/^\/[A-Za-z0-9_-]{3,160}$/.test(url.pathname)) return null;
      return provider + url.pathname;
    } catch { return null; }
  }

  function updateLink() {
    const url = meetingLink(link.value);
    external.hidden = !url || (nativeShell && provider !== 'https://meet.jit.si');
    if (url) external.href = url;
    else external.removeAttribute('href');
    get('voice-copy').disabled = !url;
    if (nativeShell && provider !== 'https://meet.jit.si' && url)
      feedback('Copy this invite and open it in your system browser.');
    return url;
  }

  function feedback(text) { status.textContent = text; }
  function setActive(active) {
    get('voice-leave').hidden = !active;
    get('voice-join').disabled = active;
    get('voice-new').disabled = active;
    link.readOnly = active;
  }
  function open() {
    get('voice-panel').open = true;
    get('voice-panel').scrollIntoView?.({block: 'start'});
    link.focus();
  }

  get('voice-new').onclick = () => {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    const slug = Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('');
    link.value = provider + '/Mariana-' + slug;
    updateLink();
    feedback(nativeShell && provider !== 'https://meet.jit.si' ? 'Copy the invite and join in your system browser.' : 'Invite ready. Share it with participants, then choose Join.');
  };
  link.oninput = updateLink;
  get('voice-copy').onclick = async () => {
    const url = updateLink();
    if (!url) return;
    try { await navigator.clipboard.writeText(url); feedback('Meeting invite copied.'); }
    catch { link.focus(); link.select(); feedback('Meeting invite selected. Use your device’s Copy action.'); }
  };
  get('voice-form').onsubmit = event => {
    event.preventDefault();
    const url = updateLink();
    if (!url) return feedback('Enter a link from the displayed meeting provider with a single meeting name.');
    if (!embedded) return feedback('Join using the browser link. Use the hang-up control in the meeting to leave.');
    if (frameContainer.firstElementChild) return;
    const frame = document.createElement('iframe');
    frame.title = 'Jitsi Meet voice room';
    frame.allow = 'microphone; camera; fullscreen; display-capture; autoplay';
    frame.referrerPolicy = 'no-referrer';
    frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups allow-presentation');
    frame.src = url + '#config.startWithAudioMuted=true&config.startWithVideoMuted=true';
    frameContainer.appendChild(frame);
    setActive(true);
    feedback('Complete the meeting’s prejoin screen. If the provider blocks embedding or sign-in, leave this view and open the meeting in your browser.');
  };
  get('voice-leave').onclick = () => {
    frameContainer.replaceChildren();
    setActive(false);
    feedback('Embedded meeting closed.');
  };
  if (!embedded) get('voice-join').hidden = true;
  updateLink();
  window.MarianaVoice = {open};
})();

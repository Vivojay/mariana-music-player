import '@strudel/repl';
import { renderPatternAudio } from '@strudel/webaudio';

const url = new URL(location.href);
const nonce = url.hash.slice(1);
const owner = url.origin;
const status = document.getElementById('status');
const editorMount = document.getElementById('editor');
const parentWindow = window.parent;
const maxBytes = 64 * 1024;
const maxWavBytes = 16 * 1024 * 1024;
const actions = new Set(['live', 'render']);

function response(type, details = {}, transfer = []) {
  parentWindow.postMessage({type, nonce, ...details}, owner === 'null' ? '*' : owner, transfer);
}

async function getEditor(element) {
  const deadline = performance.now() + 8000;
  while (!element.editor) {
    if (performance.now() > deadline) throw Error('Strudel did not initialize.');
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  await element.editor.prebaked;
  return element.editor;
}

async function offlineRender(editor, code, seconds) {
  const repl = editor.repl;
  const pattern = await repl.evaluate(code, false, true);
  if (!pattern) throw Error('Strudel produced no pattern.');
  const cycles = Number(repl.scheduler.cps);
  if (!Number.isFinite(cycles) || cycles <= 0 || cycles > 20) throw Error('Use a tempo above 0 and at most 20 cycles per second.');

  // The pinned upstream API exports by clicking a WAV download link.
  // Capture its Blob inside this frame and give bytes to the Mariana player.
  const makeURL = URL.createObjectURL.bind(URL);
  const click = HTMLAnchorElement.prototype.click;
  let audio;
  const objectURLs = [];
  URL.createObjectURL = value => {
    if (value instanceof Blob) audio = value;
    const objectURL = makeURL(value);
    objectURLs.push(objectURL);
    return objectURL;
  };
  HTMLAnchorElement.prototype.click = function suppressDownload() {};
  try {
    await renderPatternAudio(pattern, cycles, 0, seconds * cycles, 48000, 128, false, 'mariana-pattern');
    if (!audio || audio.size < 44 || audio.size > maxWavBytes) throw Error('Strudel produced no usable WAV.');
    return await audio.arrayBuffer();
  } finally {
    URL.createObjectURL = makeURL;
    HTMLAnchorElement.prototype.click = click;
    for (const objectURL of objectURLs) URL.revokeObjectURL(objectURL);
  }
}

window.addEventListener('message', async event => {
  const data = event.data;
  if (event.source !== parentWindow || event.origin !== owner || data?.nonce !== nonce || !/^[a-f0-9]{32}$/.test(nonce)
    || !actions.has(data.action) || typeof data.code !== 'string' || new TextEncoder().encode(data.code).length > maxBytes
    || !Number.isInteger(data.seconds) || data.seconds < 1 || data.seconds > 60 || editorMount.childElementCount) return;

  const element = document.createElement('strudel-editor');
  element.setAttribute('code', data.code);
  element.code = data.code;
  editorMount.appendChild(element);
  try {
    const editor = await getEditor(element);
    if (data.action === 'live') {
      // The embedded Strudel editor owns the audio gesture and Play/Stop buttons.
      status.textContent = 'Press Play in the editor to run this pattern.';
      response('live-ready');
    } else {
      status.textContent = 'Rendering WAV…';
      try {
        const buffer = await offlineRender(editor, data.code, data.seconds);
        response('rendered', {buffer}, [buffer]);
      } finally {
        editor.clear();
      }
    }
  } catch (error) {
    const message = String(error?.message || 'Strudel failed.').replace(/[\x00-\x1f\x7f]/g, ' ').slice(0,240);
    status.textContent = message;
    response('error', {message});
  }
});

if (window !== parentWindow && /^[a-f0-9]{32}$/.test(nonce)) response('ready');

'use strict';

const { app, BrowserWindow, dialog, protocol, session, shell } = require('electron');
const { readFile } = require('node:fs/promises');
const path = require('node:path');

const scheme = 'mariana-lite';
const start = scheme + '://player/';
const assets = path.join(__dirname, 'web');
const mime = new Map([
  ['.css', 'text/css'], ['.html', 'text/html'], ['.js', 'text/javascript'],
  ['.mjs', 'text/javascript'], ['.json', 'application/json'], ['.md', 'text/plain'],
  ['.webmanifest', 'application/manifest+json'], ['.png', 'image/png'],
  ['.wasm', 'application/wasm'], ['.wav', 'audio/wav'], ['.svg', 'image/svg+xml'],
]);
protocol.registerSchemesAsPrivileged([{scheme, privileges:{
  standard:true, secure:true, supportFetchAPI:true, corsEnabled:true, stream:true,
}}]);

function ownPage(value) {
  try {
    const url = new URL(value);
    return url.protocol === scheme + ':' && url.host === 'player' && !url.username && !url.password;
  } catch { return false; }
}

function external(value) {
  try {
    const url = new URL(value);
    if (url.username || url.password) return;
    const invitation = url.protocol === 'http:' && url.hostname === '127.0.0.1' && url.port &&
      /^#pair=[A-Za-z0-9_-]{43}$/.test(url.hash);
    if (url.protocol === 'https:' || invitation)
      void shell.openExternal(url.href).catch(() => {});
  } catch {}
}

async function load(request) {
  if (!['GET','HEAD'].includes(request.method) || !ownPage(request.url)) return new Response(null, {status:405});
  const url = new URL(request.url);
  const file = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
  const mimeType = mime.get(path.extname(file));
  if (!mimeType || file.split('/').some(part => !/^[\w.-]+$/.test(part) || part === '.' || part === '..'))
    return new Response(null, {status:404});
  try {
    const bytes = await readFile(path.join(assets,file));
    return new Response(request.method === 'HEAD' ? null : bytes, {headers:{
      'Content-Type':mimeType, 'Content-Length':String(bytes.length),
      'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer',
    }});
  } catch { return new Response(null,{status:404}); }
}

function launch() {
  const window = new BrowserWindow({
    width:1240, height:850, minWidth:385, backgroundColor:'#0c0f1a',
    webPreferences:{nodeIntegration:false, contextIsolation:true, sandbox:true, webviewTag:false},
  });
  window.webContents.setWindowOpenHandler(({url}) => { external(url); return {action:'deny'}; });
  window.webContents.on('will-navigate', (event, url) => {
    if ((typeof url === 'string' && ownPage(url)) || ownPage(event.url)) return;
    event.preventDefault();
    external(typeof url === 'string' ? url : event.url);
  });
  window.webContents.on('will-attach-webview', event => event.preventDefault());
  void window.loadURL(start + '?view=flow');
}

app.whenReady().then(() => {
  protocol.handle(scheme, load);
  const web = session.defaultSession;
  let micAllowed = false;
  web.setPermissionCheckHandler((contents, permission, origin, details) =>
    contents !== null && ownPage(origin) && details.isMainFrame &&
    ((permission === 'media' && ['audio','unknown'].includes(details.mediaType) && micAllowed) ||
      permission === 'fullscreen' || permission === 'clipboard-sanitized-write'));
  web.setPermissionRequestHandler((contents, permission, reply, details) => {
    if (!details.isMainFrame || !ownPage(details.requestingUrl || contents.getURL())) return reply(false);
    if (['fullscreen','clipboard-sanitized-write'].includes(permission)) return reply(true);
    if (permission !== 'media' || details.mediaTypes?.length !== 1 || details.mediaTypes[0] !== 'audio')
      return reply(false);
    if (micAllowed) return reply(true);
    void dialog.showMessageBox(BrowserWindow.fromWebContents(contents), {
      message:'Allow Mariana to use your microphone for this session?',
      buttons:['Deny','Allow'], defaultId:0, cancelId:0, type:'question',
    }).then(result => { micAllowed = result.response === 1; reply(micAllowed); },
      () => reply(false));
  });
  launch();
  app.on('activate', () => { if (!BrowserWindow.getAllWindows().length) launch(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });

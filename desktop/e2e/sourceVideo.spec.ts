import { _electron as electron, expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('native source-picture protocol preserves HD picture in two muted viewers', async () => {
  test.setTimeout(60_000)
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mariana-source-picture-'))
  const source = path.join(root, 'picture.mp4')
  const bootstrap = path.join(root, 'viewer.mjs')
  let application: Awaited<ReturnType<typeof electron.launch>> | undefined
  try {
    execFileSync('ffmpeg', ['-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
      'testsrc2=size=1920x1080:rate=60', '-t', '4', '-an', '-c:v', 'libx264',
      '-preset', 'ultrafast', '-movflags', '+faststart', source], { timeout: 30_000, stdio: 'pipe' })
    // Load the actual host protocol in an isolated native shell. No user profile,
    // provider credentials, audio output, or application library are involved.
    fs.writeFileSync(bootstrap, `
      import { app, BrowserWindow, protocol } from 'electron';
      import fs from 'node:fs';
      import http from 'node:http';
      import { serveSourceVideo } from ${JSON.stringify(pathToFileURL(path.resolve('dist-electron/localVideoProtocol.js')).href)};
      globalThis.viewerDiagnostics = [];
      const record = (event, details={}) => globalThis.viewerDiagnostics.push({event,time:performance.now(),...details});
      app.on('browser-window-created', (_event, window) => {
        const id = window.id;
        record('created', {id});
        window.on('closed', () => record('closed', {id}));
        window.webContents.on('did-finish-load', () => record('loaded', {id}));
        window.webContents.on('dom-ready', () => record('dom-ready', {id}));
        window.webContents.on('did-fail-load', (_event, code, description) => record('load-failed', {code,description}));
        window.webContents.on('render-process-gone', (_event, details) => record('renderer-gone', details));
      });
      protocol.registerSchemesAsPrivileged([{scheme:'mariana-video',privileges:{standard:true,secure:true,stream:true}}]);
      app.setPath('userData', ${JSON.stringify(path.join(root, 'profile'))});
      const viewers = [];
      let viewersCreated;
      const bothViewersCreated = new Promise(resolve => { viewersCreated = resolve });
      const bytes = fs.readFileSync(${JSON.stringify(source)});
      const server = http.createServer(async (request, response) => {
        record('http', {method:request.method,range:request.headers.range});
        // Source readiness must not serialize fixture-window construction.
        // This gate also makes an accidental await inside the creation loop fail.
        await bothViewersCreated;
        const match = /^bytes=(\\d*)-(\\d*)$/.exec(request.headers.range || '');
        const start = match && match[1] ? Number(match[1]) : 0;
        const end = match && match[2] ? Math.min(bytes.length-1, Number(match[2])) : bytes.length-1;
        response.writeHead(match ? 206 : 200, {'Content-Type':'video/mp4','Content-Length':end-start+1,
          'Accept-Ranges':'bytes', ...(match ? {'Content-Range':'bytes '+start+'-'+end+'/'+bytes.length} : {})});
        response.end(request.method === 'HEAD' ? undefined : bytes.subarray(start,end+1));
      });
      server.listen(0,'127.0.0.1',async () => {
        await app.whenReady();
        const handle = 'a'.repeat(32);
        const status = {revision:1,state:'ready',handle,media_id:'one',transport:'source'};
        const resource = {url:'http://127.0.0.1:'+server.address().port+'/'+'x'.repeat(32)+'/media',
          handle,revision:1,mediaId:'one'};
        protocol.handle('mariana-video', async request => {
          record('protocol', {method:request.method,range:request.headers.get('range')});
          const response = await serveSourceVideo(request, () => ({status,resource,mediaId:'one'}));
          record('response', {status:response.status,length:response.headers.get('content-length')});
          return response;
        });
        const loads = [];
        for (let n=0;n<2;n++) {
          const window = new BrowserWindow({width:n ? 480:900,height:n ? 300:600,show:false,
            webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
          viewers.push(window);
          loads.push(window.loadURL('data:text/html,'+encodeURIComponent('<video muted playsinline preload="metadata" style="width:100%" src="mariana-video://current/'+handle+'.mp4"></video>'))
            .then(() => { record('load-resolved', {id:window.id}); window.show() }));
        }
        viewersCreated();
        await Promise.all(loads);
      });
      app.on('window-all-closed',()=>{viewers.length=0;server.close();app.quit()});
    `)
    application = await electron.launch({ args: [bootstrap] })
    await expect.poll(() => application!.windows().length).toBe(2)
    for (const page of application.windows()) {
      await expect.poll(() => page.locator('video').evaluate(node => (node as HTMLVideoElement).readyState)).toBeGreaterThan(0)
      const metadata = await page.locator('video').evaluate(node => {
        const picture = node as HTMLVideoElement
        return { width: picture.videoWidth, height: picture.videoHeight, muted: picture.muted, duration: picture.duration }
      })
      expect(metadata).toMatchObject({ width: 1920, height: 1080, muted: true })
      expect(metadata.duration).toBeCloseTo(4, 1)
      await page.locator('video').evaluate(async node => {
        const picture = node as HTMLVideoElement
        picture.currentTime = 1.25
        await picture.play()
      })
      await expect.poll(() => page.locator('video').evaluate(node => (node as HTMLVideoElement).currentTime)).toBeGreaterThan(1.5)
      expect(await page.locator('video').evaluate(node => (node as HTMLVideoElement).getVideoPlaybackQuality().totalVideoFrames)).toBeGreaterThan(0)
    }
    if (process.env.MARIANA_SOURCE_VIDEO_DIAGNOSTICS === '1') {
      console.log('Native picture events:', JSON.stringify(await application.evaluate(() =>
        (globalThis as typeof globalThis & { viewerDiagnostics: unknown[] }).viewerDiagnostics)))
    }
  } catch (error) {
    if (application && process.env.MARIANA_SOURCE_VIDEO_DIAGNOSTICS === '1') {
      console.log('Native picture diagnostics:', JSON.stringify(await application.evaluate(async ({ BrowserWindow }) => ({
        events: (globalThis as typeof globalThis & { viewerDiagnostics: unknown[] }).viewerDiagnostics,
        windows: await Promise.all(BrowserWindow.getAllWindows().map(async window => ({
          id: window.id, loading: window.webContents.isLoading(),
          media: await window.webContents.executeJavaScript(`(() => {
            const video = document.querySelector('video');
            return video ? {readyState:video.readyState,networkState:video.networkState,
              error:video.error?.message,width:video.videoWidth,height:video.videoHeight} : null;
          })()`).catch(error => ({ error: String(error) })),
        }))),
      }))))
    }
    throw error
  } finally {
    await application?.close()
    fs.rmSync(root, { recursive: true, force: true })
  }
})

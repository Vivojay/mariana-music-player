import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Exercise real browser Origin headers on the isolated loopback origin. Python
// API authorization and dispatch semantics are tested in test_web_session.py.
test('pairs, runs a command, receives terminal actions, and restores review', async ({ page }) => {
  const root = fileURLToPath(new URL('../player/', import.meta.url));
  const invite = 'i'.repeat(43);
  const key = 's'.repeat(43);
  let origin = '';
  let command = '';
  const seeks: Array<{action:string,value:number,occurrence:string}> = [];
  let position = 12;
  let job: object | null = null;
  let libraryQuery = '';
  let mode = 'session';
  let browserAction: {id:string,action:string,value?:string} | null = null;
  const acknowledgements: Array<{id:string,error?:string}> = [];
  let noticeRetried = false;
  const session = () => ({mode,shareOutput:mode === 'session',expirySeconds:600});
  const server = createServer((req, res) => {
    if (req.method === 'GET') {
      const path = new URL(req.url || '/', origin).pathname;
      const assets = ['companion.js','companion.css','companion-flow.js','companion-console.js','companion-console.css',
        'companion-collections.js','companion-collections.css','companion-home.js','companion-home.css',
        'platform.js','player.css','command-input.js','command-input.css'];
      const file = path === '/' ? 'companion.html' : assets.includes(path.slice(1)) ? path.slice(1) : null;
      if (!file) { res.writeHead(404).end(); return; }
      const mime = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'text/html';
      res.writeHead(200, {'Content-Type': mime, 'Referrer-Policy': 'same-origin'}).end(readFileSync(resolve(root, file)));
      return;
    }
    const pairing = req.url === '/api/pair';
    if (req.headers.origin !== origin || req.headers.authorization !== 'Bearer ' + (pairing ? invite : key)) {
      res.writeHead(403).end('{}'); return;
    }
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      let result: object = {};
      if (pairing) result = { token:key, session:session(), library:true, controls:true,
        catalog:[{canonical:'now',summary:'Now playing',category:'Playback',forms:[],aliases:[]}] };
      if (req.url === '/api/command') {
        command = JSON.parse(body).command; result = {id:'1'};
        job = {state:'done',id:'1',command,output:'Current position: 12 seconds'};
      }
      if (req.url === '/api/control') {
        seeks.push(JSON.parse(body));
        position = seeks.at(-1)!.value;
        job = {state:'done',id:'seek-1',command:'seek',output:'Control applied.',ok:true};
        result = {id:'seek-1'};
      }
      if (req.url === '/api/library') {
        libraryQuery = JSON.parse(body).query;
        result = {rows:[],total:0,offset:0};
      }
      if (req.url === '/api/state') result = {session:session(),browserAction,job,playback:{
        title:'Native recording', occurrence:'test-occurrence', state:'paused',display_state:'Paused',
        duration_seconds:120,position_seconds:position,seekable:true,volume:100,playback_rate:1,
      }};
      if (req.url === '/api/browser-ack') {
        const ack = JSON.parse(body);
        if (ack.id === 'show-notice' && !noticeRetried && browserAction) {
          noticeRetried = true;
          browserAction = {...browserAction,value:'A repeat poll must not replace the first notice.'};
          res.writeHead(503, {'Content-Type':'application/json'}).end('{}'); return;
        }
        acknowledgements.push(ack);
        if (browserAction?.id === ack.id) browserAction = null;
      }
      if (req.url === '/api/revoke') { mode = 'review'; result = {session:session()}; }
      res.writeHead(200, {'Content-Type':'application/json'}).end(JSON.stringify(result));
    });
  });
  await new Promise<void>(done => server.listen(0, '127.0.0.1', done));
  try {
    const address = server.address();
    if (!address || typeof address === 'string') throw new Error('No loopback server port');
    origin = 'http://127.0.0.1:' + address.port;
    await page.goto('/');
    await page.getByRole('button', {name:'Flow', exact:true}).click();
    await page.locator('#native-navigation').click();
    await page.locator('#native-invitation-url').fill(origin + '/#pair=' + invite);
    await page.getByRole('button', {name:'Open native workspace'}).click();
    await page.getByRole('button', {name:'Connect native session'}).click();
    await expect(page).toHaveURL(origin + '/?view=flow');
    await expect(page.locator('#native-title')).toHaveText('Native recording');
    await expect(page.locator('#native-approval')).toContainText('Approved for this session');
    await expect(page.locator('#native-session-time')).toHaveText('Session time left 10:00');
    await page.locator('#native-find').fill('now');
    await page.locator('#native-matches button').first().click();
    await page.getByRole('button', {name:'Run',exact:true}).click();
    await expect(page.locator('#native-log')).toContainText('Current position: 12 seconds');
    expect(command).toBe('now');
    await page.locator('#native-progress').evaluate((element:HTMLInputElement) => {
      element.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
      for (const position of [21,24.5,37.25]) {
        element.value=String(position);
        element.dispatchEvent(new Event('input',{bubbles:true}));
      }
      element.dispatchEvent(new Event('change',{bubbles:true}));
    });
    await expect.poll(() => seeks).toEqual([{action:'seek',value:37.25,occurrence:'test-occurrence'}]);
    await expect(page.locator('#native-clock')).toHaveText('0:37 / 2:00');
    browserAction = {id:'change-view',action:'view',value:'console'};
    await expect.poll(() => acknowledgements.at(-1)).toEqual({id:'change-view'});
    await expect(page.getByRole('button',{name:'Console',exact:true})).toHaveAttribute('aria-pressed','true');
    browserAction = {id:'focus-command',action:'focus',value:'command'};
    await expect.poll(() => acknowledgements.at(-1)).toEqual({id:'focus-command'});
    await expect(page.locator('#native-text')).toBeFocused();
    browserAction = {id:'draft-command',action:'draft',value:'similar current'};
    await expect.poll(() => acknowledgements.at(-1)).toEqual({id:'draft-command'});
    await expect(page.locator('#native-text')).toHaveValue('similar current');
    expect(command).toBe('now');
    browserAction = {id:'library-query',action:'library',value:'Slow Morning'};
    await expect.poll(() => libraryQuery).toBe('Slow Morning');
    await expect.poll(() => acknowledgements.at(-1)).toEqual({id:'library-query'});
    await expect(page.locator('#native-library-query')).toHaveValue('Slow Morning');
    browserAction = {id:'show-notice',action:'notice',value:'<b>Welcome, listener</b>'};
    await expect.poll(() => acknowledgements.at(-1)).toEqual({id:'show-notice'});
    expect(noticeRetried).toBe(true);
    await expect(page.locator('#native-browser-notice')).toHaveText('<b>Welcome, listener</b>');
    await expect(page.locator('#native-browser-notice b')).toHaveCount(0);
    browserAction = {id:'hide-log',action:'clear'};
    await expect.poll(() => acknowledgements.at(-1)).toEqual({id:'hide-log'});
    await expect(page.locator('#native-log')).toBeEmpty();
    browserAction = {id:'invalid-focus',action:'focus',value:'body'};
    await expect.poll(() => acknowledgements.at(-1)).toEqual({id:'invalid-focus',error:'Unknown browser focus target.'});
    await page.getByRole('button',{name:'Review commands again',exact:true}).click();
    await expect(page.locator('#native-approval')).toHaveText('Terminal review for commands beyond transport');
    await expect(page.getByRole('button',{name:'Review commands again',exact:true})).toBeHidden();
    await page.getByRole('button', {name:'Disconnect',exact:true}).click();
    await expect(page.locator('#native-message')).toContainText('Disconnected');
  } finally {
    server.closeAllConnections();
    await new Promise<void>(done => server.close(() => done()));
  }
});

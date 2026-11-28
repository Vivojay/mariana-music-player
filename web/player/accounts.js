(() => {
  'use strict';
  const config = window.MarianaAccountConfig;
  const entries = config.providers;
  const choose = document.getElementById('account-provider');
  const detail = document.getElementById('account-detail');
  const feedback = document.getElementById('account-feedback');
  const title = document.getElementById('connections-title');
  const browserServices = {
    spotify:{client:config.spotifyClientId,authorize:'https://accounts.spotify.com/authorize',
      token:'https://accounts.spotify.com/api/token',scope:'user-read-private playlist-read-private'},
    snapchat:{client:config.snapchatClientId,authorize:'https://accounts.snapchat.com/accounts/oauth2/auth',
      token:'https://accounts.snapchat.com/accounts/oauth2/token',scope:'https://auth.snapchat.com/oauth2/api/user.external_id https://auth.snapchat.com/oauth2/api/user.display_name'}
  };
  const scoped = key => window.MarianaProfiles?.key(key) ?? key;
  const pendingKey = id => scoped('mariana.'+id+'.consent.v1');
  let services = null;
  const finishing = new Map();
  const sessions = new Map(); // Access and refresh tokens live only in this document.
  let native = false;
  let pendingLink = null;
  let generation = 0;
  const linkedKey = id => scoped('mariana.profile.v1.' + id);
  const localAddress = location.protocol === 'http:' && ['127.0.0.1','localhost'].includes(location.hostname);
  const webGrant = id => Boolean(browserServices[id]?.client && window.isSecureContext && crypto.subtle
    && (location.protocol === 'https:' || (localAddress && id === 'spotify' && location.hostname === '127.0.0.1'))
    && !['app.mariana.invalid','appassets.androidplatform.net'].includes(location.hostname));
  function element(tag, text) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    return node;
  }
  function link(text, url) {
    const anchor = element('a', text);
    anchor.href = url;
    anchor.target = location.hostname === 'app.mariana.invalid' || window.MarianaNativeShell === 'ios' ? '_self' : '_blank'; anchor.rel = 'noopener noreferrer';
    return anchor;
  }
  function button(label, action) {
    const node = element('button', label);
    node.type = 'button';
    node.onclick = async () => {
      node.disabled = true;
      try { await action(); } catch (error) { feedback.textContent = error.message; }
      finally { node.disabled = false; }
    };
    return node;
  }
  function getLink(id) {
    try {
      const handle = localStorage.getItem(linkedKey(id));
      return handle ? profileURL(id, handle) : '';
    } catch { return ''; }
  }
  function profileURL(id, raw) {
    const handle = raw.trim().replace(/^@/, '');
    const pattern = id === 'youtube' ? /^UC[\w-]{22}$/
      : ['musicbrainz','listenbrainz'].includes(id) ? /^[\p{L}\p{M}\p{N}_.-][\p{L}\p{M}\p{N}_. -]{0,79}$/u
      : /^[\p{L}\p{N}_.-]{1,80}$/u;
    if (!pattern.test(handle) || handle === '.' || handle === '..') throw Error('Enter a valid ' + entries[id].hint + '.');
    return entries[id].profile + encodeURIComponent(handle);
  }
  async function remote(args) {
    const response = await fetch('/api/accounts', {method:'POST', credentials:'same-origin', cache:'no-store',
      headers:{'Content-Type':'application/json','X-Mariana-Accounts':'1'}, body:JSON.stringify(args)});
    if (!response.headers.get('Content-Type')?.includes('application/json')) throw Error('Mariana account service is unavailable.');
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Account request failed.');
    return data;
  }
  function b64(bytes) { return btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,''); }
  function redirect() { return new URL('./', location.href).href; }
  async function authorizeService(id) {
    const spec = browserServices[id];
    const verifier = b64(crypto.getRandomValues(new Uint8Array(48)));
    const state = b64(crypto.getRandomValues(new Uint8Array(32)));
    const popup = window.BroadcastChannel && window.open ? window.open('about:blank','_blank','popup') : null;
    let channel;
    try {
      if (popup) popup.opener = null;
      const challenge = b64(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier))));
      const job = {state,verifier,time:Date.now(),redirect:redirect()};
      sessionStorage.setItem(pendingKey(id),JSON.stringify(job));
      const url = new URL(spec.authorize);
      url.search = new URLSearchParams({client_id:spec.client,state,redirect_uri:redirect(),response_type:'code',
        scope:spec.scope,code_challenge:challenge,code_challenge_method:'S256'});
      if (!popup) { location.assign(url.href); return; }
      popup.sessionStorage.setItem('mariana.consent.popup',state);
      channel = new window.BroadcastChannel('mariana.consent.'+state);
      const timeout = window.setTimeout(()=>{
        channel.close();
        if (sessionStorage.getItem(pendingKey(id)) === JSON.stringify(job)) sessionStorage.removeItem(pendingKey(id));
      },300000);
      channel.onmessage = async event=>{
        if (event.data?.state !== state) return;
        channel.close();window.clearTimeout(timeout);
        try { await complete(id,job,event.data.code); }
        catch (error) { feedback.textContent = error.message; }
        render();
      };
      popup.location.replace(url.href);
      feedback.textContent = 'Finish sign-in in the new window.';
    } catch (error) {
      if (popup) popup.close();
      channel?.close();
      throw error;
    }
  }
  async function spotifyAPI(path, token) {
    const r = await fetch('https://api.spotify.com/v1/' + path, {headers:{Authorization:'Bearer ' + token}, cache:'no-store'});
    if (!r.ok) throw Error('Spotify returned HTTP ' + r.status + '. Reconnect or check account access.');
    return r.json();
  }
  async function exchange(id, values) {
    const r = await fetch(browserServices[id].token, {method:'POST',cache:'no-store',
      body:new URLSearchParams({client_id:browserServices[id].client,...values})});
    if (!r.ok) throw Error(entries[id].name+' could not authorize this session (HTTP ' + r.status + ').');
    const data = await r.json();
    if (!data.access_token) throw Error(entries[id].name+' did not issue an access token.');
    return data;
  }
  async function identity(id,token) {
    if (id === 'spotify') {
      const user = await spotifyAPI('me',token);
      if (!user.account_id && !user.id) throw Error('Spotify could not confirm the account.');
      return {name:user.display_name || user.id,id:user.account_id || user.id};
    }
    const query = new URLSearchParams({query:'{me { externalId displayName }}'});
    const r = await fetch('https://kit.snapchat.com/v1/me?'+query,{headers:{Authorization:'Bearer '+token},cache:'no-store'});
    if (!r.ok) throw Error('Snapchat returned HTTP '+r.status+'.');
    const user = (await r.json()).data?.me;
    if (!user?.externalId) throw Error('Snapchat could not confirm the account.');
    return {name:user.displayName || 'Snapchat user',id:user.externalId};
  }
  async function receive() {
    const url = new URL(location.href);
    if (!url.searchParams.has('state') || !(url.searchParams.has('code') || url.searchParams.has('error'))) return;
    const state = url.searchParams.get('state'), code = url.searchParams.get('code');
    const removeCallback = () => {
      for (const key of ['state','code','error','error_description']) url.searchParams.delete(key);
      history.replaceState(null,'',url.href);
    };
    if (sessionStorage.getItem('mariana.consent.popup') === state && window.BroadcastChannel) {
      sessionStorage.removeItem('mariana.consent.popup');
      removeCallback();
      const channel = new window.BroadcastChannel('mariana.consent.'+state);
      channel.postMessage({state,code});
      channel.close();window.close();
      feedback.textContent = 'Return to the Mariana window where you started sign-in.';
      return;
    }
    const jobs = Object.keys(browserServices).map(id=>[id,sessionStorage.getItem(pendingKey(id))])
      .filter(([,saved])=>saved).map(([id,saved])=>[id,JSON.parse(saved)]);
    if (!jobs.length) return;
    removeCallback();
    const match = jobs.find(([,job])=>job.state === state);
    if (!match) throw Error('Provider returned an unmatched sign-in request.');
    await complete(...match,code);
  }
  async function complete(id,job,code) {
    const stored = JSON.parse(sessionStorage.getItem(pendingKey(id)) || 'null');
    if (!stored || stored.state !== job.state) throw Error('This sign-in request is no longer active.');
    sessionStorage.removeItem(pendingKey(id));
    if (!code || Date.now() - job.time > 300000 || job.redirect !== redirect()) throw Error('Sign-in was declined or expired.');
    finishing.set(id,job);
    const tokens = await exchange(id,{grant_type:'authorization_code',code,redirect_uri:job.redirect,code_verifier:job.verifier});
    const user = await identity(id,tokens.access_token);
    if (finishing.get(id) !== job) throw Error('Sign-in cancelled.');
    finishing.delete(id);
    sessions.set(id,{...user,token:tokens.access_token,refresh:tokens.refresh_token,
      expires:Date.now()+Number(tokens.expires_in || 3600)*1000});
    choose.value = id;
    feedback.textContent = 'Signed in to '+entries[id].name+' for this browser session.';
  }
  function sameSession(id,original,user) {
    if (sessions.get(id) !== original) throw Error('The account session changed. Connect again.');
    if (user && user.id !== original.id) {
      sessions.delete(id);
      render();
      throw Error('The provider returned a different account. Connect again.');
    }
  }
  async function browserToken(id) {
    const account = sessions.get(id);
    if (!account) throw Error('Connect to '+entries[id].name+' first.');
    if (Date.now()+60000 >= account.expires) {
      if (!account.refresh) throw Error('This session expired. Connect again.');
      const data = await exchange(id,{grant_type:'refresh_token',refresh_token:account.refresh});
      sameSession(id,account);
      const user = await identity(id,data.access_token);
      sameSession(id,account,user);
      account.token = data.access_token;
      account.refresh = data.refresh_token || account.refresh;
      account.expires = Date.now()+Number(data.expires_in || 3600)*1000;
    }
    return account.token;
  }
  async function reload() {
    if (native) {
      services = (await remote(['list'])).services;
      if (pendingLink && !services.some(s=>s.id === pendingLink.id && s.pending)) pendingLink = null;
    }
    render();
  }
  async function action(id, op, ...values) {
    const useNative = native && (['link','unlink'].includes(op) || !(!services?.find(i=>i.id === id)?.available && webGrant(id) && !services?.find(i=>i.id === id)?.identity));
    if (useNative) {
      const result = await remote([op,id,...values]);
      if (result.authorize) pendingLink = {id,url:result.authorize};
      if (op === 'cancel' || op === 'finish' || op === 'disconnect') pendingLink = null;
      feedback.textContent = result.message || (result.items || []).join('\n') || 'No entries.';
      await reload();
      return;
    }
    if (op === 'link') {
      profileURL(id,values[0]); localStorage.setItem(linkedKey(id),values[0].trim()); feedback.textContent = 'Saved public profile link.';
    } else if (op === 'unlink') { localStorage.removeItem(linkedKey(id)); feedback.textContent = 'Removed public profile link.'; }
    else if (op === 'activity' && id === 'listenbrainz') {
      const saved = getLink(id);
      if (!saved) throw Error('Save a ListenBrainz profile link first.');
      const user = new URL(saved).pathname.split('/').pop();
      const r = await fetch('https://api.listenbrainz.org/1/user/'+user+'/listens?count=10',{credentials:'omit'});
      if (!r.ok) throw Error('ListenBrainz returned HTTP '+r.status+'.');
      const data = await r.json();
      feedback.textContent = (data.payload?.listens || []).map(item=>[item.track_metadata?.track_name,item.track_metadata?.artist_name].filter(Boolean).join(' · ')).join('\n') || 'No listens.';
    }
    else if (webGrant(id)) {
      if (op === 'connect') return authorizeService(id);
      if (op === 'disconnect') { finishing.delete(id); sessionStorage.removeItem(pendingKey(id)); sessions.delete(id); feedback.textContent = 'Removed the browser session.'; }
      else if (op === 'verify') {
        const account = sessions.get(id);
        const user = await identity(id,await browserToken(id));
        sameSession(id,account,user);
        account.name = user.name;
        feedback.textContent = 'Verified as ' + user.name;
      }
      else if (op === 'activity' && id === 'spotify') {
        const account = sessions.get(id);
        const data = await spotifyAPI('me/playlists?limit=20',await browserToken(id));
        sameSession(id,account);
        feedback.textContent = data.items.map(p=>p.name).join('\n') || 'No playlists.';
      } else throw Error('This operation requires the desktop account service.');
    } else throw Error('Provider sign-in is unavailable in this build. Save or open a public profile.');
    render();
  }
  function render() {
    const id = choose.value, definition = entries[id];
    const row = services?.find(item => item.id === id);
    const verified = row?.identity?.name || sessions.get(id)?.name;
    const online = row?.available || webGrant(id);
    const pg = row?.link || getLink(id);
    detail.replaceChildren();
    const status = element('p', verified ? 'Signed in as ' + verified : online ? 'Sign in through ' + definition.name + '.' : 'Public profile links available.');
    status.className = 'account-state'; detail.append(status);
    const actions = element('div'); actions.className = 'account-actions'; detail.append(actions);
    if (row?.pending) {
      if (pendingLink?.id === id) actions.append(link('Continue on ' + definition.name, pendingLink.url));
      if (id === 'lastfm') actions.append(button('Finish sign-in',()=>action(id,'finish')));
      actions.append(button('Check sign-in',reload),button('Cancel sign-in',()=>action(id,'cancel')));
    } else if (verified) {
      actions.append(button('Verify',()=>action(id,'verify')));
      if (['lastfm','spotify','youtube'].includes(id)) actions.append(button(id === 'lastfm' ? 'Recent listens' : 'My playlists',()=>action(id,'activity')));
      actions.append(button('Disconnect',()=>action(id,'disconnect')));
    } else if (online) actions.append(button('Connect ' + definition.name,()=>action(id,'connect')));
    if (id === 'listenbrainz' && pg) actions.append(button('Recent public listens',()=>action(id,'activity')));
    if (row?.notice) detail.append(element('p',row.notice));
    const input = element('input'); input.placeholder = definition.hint; input.maxLength = 80;
    const label = element('label',definition.hint); label.append(input);
    const field = element('div'); field.className = 'account-actions';
    field.append(label,button('Save profile link',()=>action(id,'link',input.value)));
    detail.append(field);
    const destinations = element('div'); destinations.className = 'account-actions';
    destinations.append(link(pg ? 'Open saved profile' : 'Open ' + definition.name,pg || row?.identity?.url || definition.site));
    if (pg) destinations.append(button('Remove link',()=>action(id,'unlink')));
    detail.append(destinations);
  }
  async function command(args=[]) {
    const [op,id,...values] = args;
    if (op === 'setup') return guided(id);
    if (id && !entries[id]) throw Error('Choose a service from Connections.');
    title.focus(); title.scrollIntoView({block:'start'});
    if (id) { choose.value=id; render(); }
    if (!op || op === 'list' || op === 'help') { await reload(); return 'Connections opened. Select a service to sign in or save a public profile.'; }
    if (!id) throw Error('Include a service, for example accounts connect spotify.');
    if (op === 'open') { detail.querySelector('.account-actions:last-child a')?.focus(); return 'Choose Open in Connections.'; }
    await action(id,op,...values); return feedback.textContent;
  }
  for (const [id,def] of Object.entries(entries)) { const option = element('option',def.name); option.value=id; choose.append(option); }
  function guided(target) {
    const selector = document.getElementById('setup-feature');
    if (!target) { selector.focus(); selector.scrollIntoView({block:'center'}); return 'Choose a service, then Continue setup.'; }
    if (target === 'karaoke') {
      const demo = document.getElementById('karaoke-demo'); demo.focus(); demo.scrollIntoView({block:'center'});
      return 'Choose Try a duet to play the included example. For your own recording, import a timing sheet.';
    }
    if (target === 'podcasts' || target === 'audiobooks') {
      const form = document.getElementById('catalog-search');
      form.elements.catalog.value = target === 'podcasts' ? 'podcast' : 'book';
      form.elements.term.focus(); form.scrollIntoView({block:'center'});
      return 'Enter a title in the public catalog search. No account is required.';
    }
    if (!Object.prototype.hasOwnProperty.call(entries, target)) throw Error('Choose a service from Guided setup.');
    choose.value = target; render(); detail.scrollIntoView({block:'center'});
    (detail.querySelector('button') || detail.querySelector('input'))?.focus();
    return 'Follow the available steps for ' + entries[target].name + '.';
  }
  const guidedChoice = document.getElementById('setup-feature');
  if (guidedChoice) {
    for (const [id, def] of Object.entries(entries)) {
      const opt = element('option', def.name); opt.value = id; guidedChoice.append(opt);
    }
    const go = document.getElementById('setup-feature-open');
    if (go) go.onclick = () => { feedback.textContent = guided(guidedChoice.value); };
  }
  choose.onchange=()=>{ feedback.textContent=''; render(); };
  async function boot() {
    const stamp = ++generation;
    try { await receive(); } catch (err) { feedback.textContent = err.message; }
    if (localAddress && (!window.MarianaProfiles || window.MarianaProfiles.current === 'default')) {
      try { const response = await remote(['list']); if (stamp === generation) {services=response.services;native=Array.isArray(services);} }
      catch { /* The standalone shell also works without the account service. */ }
    }
    render();
  }
  window.MarianaAccounts = {command};
  render(); boot();
})();

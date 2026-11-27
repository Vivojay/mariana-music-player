'use strict';
(() => {
  const get = id => document.getElementById('jam-' + id);
  const hostProfile = !window.MarianaProfiles || window.MarianaProfiles.current === 'default';
  const local = hostProfile && location.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(location.hostname);
  const unavailable = !hostProfile ? 'Local jam accounts belong to the native launcher. Use the Default browser profile to access them.' : 'Listening rooms use the local Mariana web launcher. On a computer run python tools/build_web_player.py --serve, or use jam in the native terminal.';
  const help = 'jam login https://homeserver · jam status | rooms | invites | logout · jam create NAME · jam join ROOM · jam members ROOM · jam invite ROOM @USER · jam suggest ROOM TITLE · jam timeline ROOM · jam cue ROOM play|pause|seek SECONDS TITLE · jam send ROOM · jam current ROOM · jam apply ROOM · jam sync ROOM · jam leave ROOM';
  if (!local) {
    get('availability').textContent = unavailable;
    get('actions').hidden = true;
  }
  async function command(args) {
    const [raw, ...rest] = args;
    const action = (raw || 'help').toLowerCase();
    if (action === 'help') return help;
    if (!local) throw Error(unavailable);
    let call = [action, ...rest];
    if (action === 'send') {
      const state = window.MarianaJamTransport.state();
      if (!state || !state.title || !Number.isFinite(state.seconds)) throw Error('Load a track first.');
      call = ['cue', rest[0], state.paused ? 'pause' : 'play', String(state.seconds), state.title];
    } else if (action === 'apply') call = ['current', ...rest];
    const response = await fetch('/api/jam', {method:'POST', credentials:'same-origin', cache:'no-store',
      headers:{'Content-Type':'application/json','X-Mariana-Jam':'1'}, body:JSON.stringify(call)});
    if (!response.headers.get('Content-Type')?.includes('application/json')) throw Error(unavailable);
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Room request failed.');
    if (result.room_id) get('room').value = result.room_id;
    if (['apply', 'sync'].includes(action) && result.cue) {
      await window.MarianaJamTransport.apply(result.cue);
      return 'Applied ' + result.message;
    }
    return result.message;
  }
  get('actions').addEventListener('click', async event => {
    const action = event.target.closest('[data-jam]')?.dataset.jam;
    if (!action) return;
    const room = get('room').value.trim();
    const extra = {login:[get('server').value.trim()], create:[get('name').value.trim()],
      invite:[room, get('user').value.trim()], suggest:[room, get('track').value.trim()],
      logout:[], status:[], rooms:[], invites:[]};
    const buttons = [...get('actions').querySelectorAll('button')];
    buttons.forEach(button => { button.disabled = true; });
    get('feedback').textContent = action === 'login' ? 'Complete sign-in in your browser.' : 'Contacting your homeserver…';
    try { get('feedback').textContent = await command([action, ...(extra[action] || [room])]); }
    catch (error) { get('feedback').textContent = error.message; }
    finally { buttons.forEach(button => { button.disabled = false; }); }
  });
  window.MarianaJams = {command};
})();

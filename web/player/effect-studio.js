(() => {
  'use strict';
  const moduleURL = new URL('effect-worklet.js',document.currentScript.src).href;
  const presets = {'dry':{}, 'vocal-booth':{deess:65,room:13}, 'choir':{chorus:62,room:33},
    'cassette':{drive:38,chorus:15}, 'bit-sampler':{bitcrush:75}, 'cavern':{room:85,delay:28}, 'robot':{robot:75,drive:10},
    'subvoice':{pitch:-5,room:12}, 'bright-voice':{pitch:3,chorus:20},
    'chromatic':{tune:100,room:10}, 'synth-voice':{vocoder:95,chorus:15}};
  const effects = ['chorus','delay','room','drive','tremolo','robot','deess','pitch','tune','vocoder','tapestop','bitcrush'];
  const storageKey = name => window.MarianaProfiles?.key('mariana.fx.'+name) ?? 'mariana.fx.'+name;
  const validName = name => /^[a-z0-9][a-z0-9-]{0,39}$/.test(name || '');
  const validValue = (key,v) => effects.includes(key) && Number.isFinite(v)
    && (key === 'pitch' ? v >= -12 && v <= 12 : v >= 0 && v <= 100);

  function mount(el, audio, active) {
    let rack = {}, mic = null, ticket = 0, pending = false, enabled = false;
    let changes = Promise.resolve();
    const message = el('fx-note');
    const status = () => {
      const levels = Object.entries(rack).filter(([,v])=>v).map(([k,v])=>k+' '+v).join(', ') || 'dry';
      return 'Local file FX: '+levels+' · microphone: '+(mic ? 'monitoring' : pending ? 'awaiting permission' : 'off')
        +(active()?.url ? ' · remote media uses the original audio' : '');
    };
    const show = text => { if (message) message.textContent=text; return text; };
    const refresh = () => show(status());

    function stopMic() {
      ticket++; pending=false;
      if (mic) {
        mic.stream.getTracks().forEach(track=>track.stop());
        mic.context.close().catch(()=>{});
        mic=null;
      }
    }
    async function startMic() {
      if (mic || pending) return;
      if (!navigator.mediaDevices?.getUserMedia) throw Error('Microphone access requires localhost or HTTPS and browser permission.');
      const Audio=window.AudioContext || window.webkitAudioContext;
      if (!Audio || !window.AudioWorkletNode) throw Error('This browser needs Web Audio worklet support for live effects.');
      const serial=++ticket;
      let stream,context;
      pending=true;
      try {
        context=new Audio(); await context.resume(); await context.audioWorklet.addModule(moduleURL);
        if (serial!==ticket) return;
        stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true}, video:false});
        if (serial!==ticket) return;
        const node=new AudioWorkletNode(context,'mariana-effects',{outputChannelCount:[2]});
        const source=context.createMediaStreamSource(stream), gain=context.createGain();
        gain.gain.value=.35;
        node.port.postMessage(rack);
        source.connect(node); node.connect(gain); gain.connect(context.destination);
        mic={context,node,stream};
        node.onprocessorerror=()=>{stopMic();show('Microphone effect stopped.');};
        stream.getAudioTracks().forEach(track=>track.addEventListener('ended',()=>{if(mic?.stream===stream){stopMic();refresh();}}));
      } finally {
        if (serial===ticket) pending=false;
        if (!mic || mic.stream!==stream) {
          stream?.getTracks().forEach(track=>track.stop());
          await context?.close().catch(()=>{});
        }
      }
    }
    function apply(change) {
      const pending = changes.then(() => applyNow(typeof change==='function' ? change(rack) : change));
      changes = pending.catch(()=>{});
      return pending;
    }
    async function applyNow(next) {
      // Local media and the mic keep separate clock and filter memories.
      if (Object.values(next).some(Boolean) || enabled) {
        const ok = await window.MarianaSpeech.setRack(audio,next,moduleURL);
        if (!ok) throw Error('This browser could not start local-file effects. Audio is playing dry.');
      }
      enabled=Object.values(next).some(Boolean); rack=next;
      mic?.node.port.postMessage(rack);
      return refresh();
    }
    async function command(args) {
      const [op,...rest]=args;
      if (!op || (op==='status' && !rest.length)) return refresh();
      if (op==='help') return 'fx presets · fx preset NAME · fx set EFFECT VALUE · fx save/load NAME · fx mic on/off · fx off. Use speed RATE for media speed.';
      if (op==='presets' && !rest.length) {
        const saved=[], prefix=storageKey('');
        try {
          for (let i=0;i<localStorage.length;i++) {
            const key=localStorage.key(i);
            if (key?.startsWith(prefix) && validName(key.slice(prefix.length))) saved.push(key.slice(prefix.length));
          }
        } catch {}
        return 'Factory: '+Object.keys(presets).join(', ')+(saved.length ? '\nSaved: '+saved.sort().join(', ') : '');
      }
      if (op==='off' && !rest.length) return apply({});
      if (op==='preset' && rest.length===1 && Object.prototype.hasOwnProperty.call(presets, rest[0])) return apply({...presets[rest[0]]});
      if (op==='set' && rest.length===2 && rest[1].trim() && validValue(rest[0],Number(rest[1])))
        return apply(previous=>({...previous,[rest[0]]:Number(rest[1])}));
      if (op==='mic' && rest.join(' ')==='on') {await startMic(); return refresh();}
      if (op==='mic' && rest.join(' ')==='off') {stopMic(); return refresh();}
      if (['load','save'].includes(op) && rest.length===1 && validName(rest[0])) {
        if (op==='save') {await changes;localStorage.setItem(storageKey(rest[0]),JSON.stringify(rack));return show('Saved '+rest[0]);}
        const value=JSON.parse(localStorage.getItem(storageKey(rest[0])) || 'null');
        if (!value || Array.isArray(value) || typeof value!=='object' || Object.entries(value).some(([k,v])=>!validValue(k,v)))
          throw Error('Saved rack unavailable.');
        return apply(value);
      }
      throw Error('Use fx help. Effects: '+effects.join(', ')+'. Amount 0–100, pitch −12 to +12.');
    }
    const select=el('fx-preset');
    if (select) {
      for (const k of Object.keys(presets)) select.add(new Option(k,k));
      select.onchange=()=>command(['preset',select.value]).catch(e=>show(e.message));
      el('fx-mic').onclick=()=>command(['mic',mic || pending ? 'off':'on']).catch(e=>show(e.message));
    }
    window.addEventListener('pagehide',stopMic);
    audio.addEventListener('mariana-fx-bypass',()=>show('Local effects stopped. The file continues playing dry.'));
    return {command};
  }
  window.MarianaEffects = Object.freeze({mount});
})();

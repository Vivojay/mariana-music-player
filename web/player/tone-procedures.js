/* The bank is generated from the same score and wavetable definitions used by Python. */
(() => {
  "use strict";
  const bank = globalThis.MarianaToneBank;
  const rate = 32000, size = 2048;
  const help = [
    'tone procedure play twinkle [--bpm 100] [--chorus 38] [--level 32]',
    'tone procedure list | tone voices | tone sfx list',
    'tone procedure save my-theme 96 @felt-keys C5 G5 E5:2 @choir C4+E4+G4:4 --chorus 32',
    'tone keys glass | tone synth glass C4+E4+G4:2 R A4 | tone sfx footstep',
    'Durations are in beats. R is a rest. Start a simultaneous part with @voice.'
  ].join('\n');
  const families = ['procedure', 'synth', 'sfx', 'voices', 'keys'];
  function number(value, low, high, label) {
    if (!/^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(String(value)) || +value < low || +value > high)
      throw Error('Choose ' + label + ' between ' + low + ' and ' + high + '.');
    return +value;
  }
  function own(object, key) { return Object.prototype.hasOwnProperty.call(object, key); }
  function compile(score, options) {
    const bpm = number(options['--bpm'] ?? score.bpm, 30, 300, 'tempo');
    const chorus = number(options['--chorus'] ?? score.chorus ?? 0, 0, 100, 'chorus');
    const level = number(options['--level'] ?? 32, 0, 100, 'level');
    if (!score.tracks.length || score.tracks.length > 4) throw Error('Use one to four @voice parts.');
    let frames = 0;
    const parts = score.tracks.map(track => {
      const tokens = track.score.trim().split(/\s+/).filter(Boolean);
      if (!own(bank.voices, track.voice) || !tokens.length || tokens.length > 128)
        throw Error("Choose a voice from 'tone voices' and 1 to 128 steps per part.");
      let beat = 0;
      const notes = tokens.map(token => {
        const [chord, length = 1, ...extra] = token.split(':');
        if (extra.length) throw Error('Invalid duration: '+token);
        const start = Math.round(beat * 60 * rate / bpm);
        beat += number(length, .0625, 16, 'step length');
        const end = Math.round(beat * 60 * rate / bpm);
        if (end > 90 * rate) throw Error('A procedure may last up to 90 seconds.');
        const pitches = chord.toUpperCase() === 'R' ? [] : chord.split('+').map((key,i) => {
          const m = /^([A-G])([#b]?)([0-8])$/i.exec(key);
          if (!m || i >= 6) throw Error('Invalid note or chord: ' + token + '. Try C4+Eb4+G4:2 or R.');
          return 12*(+m[3]+1) + {C:0,D:2,E:4,F:5,G:7,A:9,B:11}[m[1].toUpperCase()] +
            (m[2] === '#' ? 1 : m[2] ? -1 : 0);
        });
        frames = Math.max(frames,end);
        return {start, length:end-start, pitches};
      });
      return {voice:track.voice, gain:track.gain ?? .7, notes};
    });
    return {title:score.title, parts, frames, chorus, level};
  }
  function score(title, bpm, words) {
    const tracks = [];
    for (const word of words) {
      if (word.startsWith('@')) tracks.push({voice:word.slice(1).toLowerCase(), notes:[]});
      else {
        if (!tracks.length) tracks.push({voice:'felt-keys',notes:[]});
        tracks[tracks.length-1].notes.push(word);
      }
    }
    return {title,bpm,tracks:tracks.map(track=>({voice:track.voice,score:track.notes.join(' '),gain:.72}))};
  }

  // One database per profile. IndexedDB add() atomically refuses simultaneous saves of the same name.
  async function library(operation, key, value) {
    const dbName = window.MarianaProfiles?.key('mariana-tone-procedures') ?? 'mariana-tone-procedures';
    return new Promise((resolve,reject) => {
      const req = indexedDB.open(dbName, 1);
      req.onupgradeneeded = () => req.result.createObjectStore('scores');
      req.onerror = () => reject(Error('Saved procedures require browser storage.'));
      req.onsuccess = () => {
        const db = req.result;
        const tx = db.transaction('scores', operation === 'save' ? 'readwrite' : 'readonly');
        const store = tx.objectStore('scores');
        const result = operation === 'save' ? store.add(value,key) :
          operation === 'list' ? store.getAllKeys() : store.get(key);
        tx.oncomplete = () => { db.close(); resolve(result.result); };
        tx.onabort = () => {
          db.close();
          reject(Error(result.error?.name === 'ConstraintError' ? 'This procedure name already exists.' : 'Browser storage could not complete the request.'));
        };
      };
    });
  }
  function slug(value) {
    if (!/^[a-z0-9][a-z0-9-]{0,39}$/.test(value)) throw Error('Use 1–40 lower-case letters, digits and hyphens for a procedure name.');
    return value;
  }
  let completionDb, completionNames=[], refreshing=false;
  function completionRows() {
    const name=window.MarianaProfiles?.key('mariana-tone-procedures') ?? 'mariana-tone-procedures';
    if(name!==completionDb) { completionDb=name; completionNames=[]; }
    if(!refreshing) {
      refreshing=true;
      library('list').then(names=>{ if(name===completionDb) completionNames=names; }).catch(()=>{}).finally(()=>{refreshing=false;});
    }
    return [...Object.keys(bank.procedures),...completionNames].map(value=>({value,description:'Stored tone procedure'}));
  }
  async function plan(args, store=library) {
    const words=[], options={};
    for (let i=0;i<args.length;i++) {
      const word=args[i];
      if (!word.startsWith('--')) { words.push(word); continue; }
      const split=word.indexOf('=');
      const key=split < 0 ? word : word.slice(0,split);
      if (!['--bpm','--chorus','--level'].includes(key) || own(options,key)) throw Error('Unsupported or repeated tone option: '+key);
      options[key]=split < 0 ? args[++i] ?? '' : word.slice(split+1);
    }
    const family=words.shift()?.toLowerCase(), simple=!Object.keys(options).length;
    if (family === 'voices' && !words.length && simple) return Object.keys(bank.voices).join(', ');
    if (family === 'keys' && words.length <= 1 && simple) return keyboard(words[0] || 'felt-keys');
    if (family === 'synth' && words.length>=2) return compile(score(words[0],100,['@'+words[0],...words.slice(1)]),options);
    if (family === 'sfx') {
      if ((!words.length || (words.length===1 && words[0]==='list')) && simple) return Object.keys(bank.sfx).join(', ');
      if (words.length===1 && own(bank.sfx,words[0])) return compile(score(words[0],100,['@'+words[0],bank.sfx[words[0]]]),options);
    }
    if (family !== 'procedure') throw Error(help);
    const action = (words.shift() || 'list').toLowerCase();
    if (action==='list' && !words.length && simple) {
      let saved;
      try { saved=await store('list'); } catch { return Object.keys(bank.procedures).join(', ') + ' (browser storage unavailable)'; }
      return [...Object.keys(bank.procedures),...saved].join(', ');
    }
    if (action==='play' && words.length===1) {
      const key=slug(words[0]);
      const saved=own(bank.procedures,key) ? bank.procedures[key] : await store('get',key);
      if (!saved) throw Error("Unknown procedure. Use 'tone procedure list'.");
      return compile(saved,options);
    }
    if (action==='save' && words.length>=3) {
      const key=slug(words[0]);
      if (own(bank.procedures,key) || own(options,'--bpm') || own(options,'--level'))
        throw Error('Use a new name, a positional tempo, and optional --chorus when saving.');
      const saved=score(key,words[1],words.slice(2));
      saved.chorus=number(options['--chorus'] ?? 0,0,100,'chorus');
      compile(saved,{});
      await store('save',key,saved);
      if (store===library && !completionNames.includes(key)) completionNames.push(key);
      return 'Saved '+key+'. Play it with tone procedure play '+key+'.';
    }
    throw Error(help);
  }

  function wav(frames) {
    const data=new DataView(new ArrayBuffer(44+frames*4));
    const label=(at,s)=>Array.from(s).forEach((c,i)=>data.setUint8(at+i,c.charCodeAt(0)));
    label(0,'RIFF'); data.setUint32(4,36+frames*4,true); label(8,'WAVE'); label(12,'fmt ');
    data.setUint32(16,16,true); data.setUint16(20,1,true); data.setUint16(22,2,true);
    data.setUint32(24,rate,true); data.setUint32(28,4*rate,true); data.setUint16(32,4,true);
    data.setUint16(34,16,true); label(36,'data'); data.setUint32(40,4*frames,true);
    return data;
  }
  function wavetable(partials) {
    const table=new Float32Array(size+1);
    const sum=partials.reduce((a,b)=>a+b,0);
    for (let j=0;j<=size;j++) {
      for (let i=0;i<partials.length;i++) table[j] += partials[i]*Math.sin((i+1)*j*2*Math.PI/size)/sum;
    }
    return table;
  }
  async function render(procedure, current=()=>true) {
    const mix=new Float32Array(procedure.frames);
    const tables=new Map();
    let lastYield=performance.now();
    async function giveTime() {
      if (performance.now()-lastYield>12) {
        await new Promise(done=>setTimeout(done,0));
        if (!current()) throw Error('A newer selection took precedence.');
        lastYield=performance.now();
      }
    }
    for (const part of procedure.parts) {
      const voice=bank.voices[part.voice];
      for (const step of part.notes) {
        if (!step.pitches.length) continue;
        const tones=step.pitches.map(midi=>{
          const hz=440*2**((midi-69)/12);
          const count=Math.min(voice.partials.length,Math.floor(.48*rate/(hz*Math.max(1,2**(voice.bend/12)))));
          const key=part.voice+':'+count;
          if (count && !tables.has(key)) tables.set(key,wavetable(voice.partials.slice(0,count)));
          return {hz,table:tables.get(key)};
        });
        let seed=step.start+step.pitches[0]+1;
        const bend=voice.bend*Math.LN2/(12*step.length/rate);
        for (let start=0; start<step.length; start+=8192) {
          await giveTime();
          const end=Math.min(step.length,start+8192);
          for (let i=start; i<end; i++) {
            const t=i/rate;
            const phase=bend ? Math.expm1(t*bend)/bend : t;
            let s=0;
            for (const {hz,table} of tones) {
              if (!table) continue;
              const x=((phase*hz)%1)*size, j=Math.floor(x);
              s+=table[j]+(table[j+1]-table[j])*(x-j);
            }
            s/=tones.length;
            if (voice.noise) {
              seed=(Math.imul(seed,1664525)+1013904223)>>>0;
              s=s*(1-voice.noise)+(seed/2147483648-1)*voice.noise;
            }
            const a=Math.min(1,t/voice.attack);
            const d=voice.sustain+(1-voice.sustain)*Math.exp(-Math.max(0,t-voice.attack)/voice.decay);
            const r=Math.min(1,(step.length-1-i)/(rate*Math.min(voice.release,step.length/rate*.35)));
            mix[step.start+i]+=s*a*d*r*part.gain;
          }
        }
      }
    }
    let peak=1;
    for(let i=0;i<mix.length;i++) peak=Math.max(peak,Math.abs(mix[i]));
    const data=wav(procedure.frames);
    const gain=32767*procedure.level/(100*peak), amount=procedure.chorus/200;
    for(let start=0;start<mix.length;start+=8192) {
      await giveTime();
      for(let i=start;i<Math.min(mix.length,start+8192);i++) {
        for(let c=0;c<2;c++) {
          const pos=i-rate*(.016+.003*Math.sin(2*Math.PI*.8*i/rate+c*Math.PI*.65)), lo=Math.floor(pos);
          const delay=lo<0 ? 0 : mix[lo]+(mix[lo+1]-mix[lo])*(pos-lo);
          data.setInt16(44+4*i+c*2,Math.round(gain*((1-amount)*mix[i]+amount*delay)),true);
        }
      }
    }
    return {title:procedure.title,file:new File([data.buffer],'Mariana-procedure.wav',{type:'audio/wav'})};
  }
  function keyboard(voiceName) {
    if (!own(bank.voices,voiceName) || bank.voices[voiceName].noise) throw Error("Choose a melodic voice from 'tone voices'. Audition percussion with 'tone sfx'.");
    const old=document.getElementById('tone-keys');
    if(old?.open) old.close();
    const Audio=globalThis.AudioContext || globalThis.webkitAudioContext;
    if(!Audio) throw Error('This browser cannot open a Web Audio instrument.');
    const ctx=new Audio();
    const dialog=document.createElement('dialog');
    dialog.id='tone-keys'; dialog.setAttribute('aria-label','Playable synthesizer');
    const title=document.createElement('h2'); title.textContent='Play '+voiceName;
    const hint=document.createElement('p'); hint.textContent='Hold keys A–K or play the notes on screen. W, E, T, Y and U play sharps.';
    const keys=document.createElement('div'); keys.className='tone-keyboard';
    const close=document.createElement('button'); close.type='button'; close.textContent='Close keyboard';
    const notes=['C4','C♯4','D4','D♯4','E4','F4','F♯4','G4','G♯4','A4','A♯4','B4','C5'];
    const keymap='awsedftgyhujk';
    const active=new Map();
    const voice=bank.voices[voiceName];
    const imag=Float32Array.from([0,...voice.partials]);
    const waveform=ctx.createPeriodicWave(new Float32Array(imag.length),imag);
    const output=ctx.createDynamicsCompressor(); output.connect(ctx.destination);
    let closed=false;
    function off(i) {
      const playing=active.get(i);
      if(!playing) return;
      active.delete(i);
      keys.children[i].setAttribute('aria-pressed','false');
      const now=ctx.currentTime;
      playing.gain.gain.cancelScheduledValues(now);
      playing.gain.gain.setTargetAtTime(0,now,Math.max(.012,voice.release/4));
      playing.osc.stop(now+voice.release+.06);
    }
    function on(i) {
      if(closed || active.has(i)) return;
      ctx.resume().catch(()=>{ hint.textContent='Audio output was blocked. Reopen the keyboard to try again.'; });
      const gain=ctx.createGain(), osc=ctx.createOscillator(), now=ctx.currentTime;
      osc.setPeriodicWave(waveform); osc.frequency.value=440*2**((60+i-69)/12);
      gain.gain.setValueAtTime(0,now); gain.gain.linearRampToValueAtTime(.14,now+voice.attack);
      gain.gain.setTargetAtTime(.14*voice.sustain,now+voice.attack,voice.decay);
      osc.connect(gain); gain.connect(output); osc.start(now);
      osc.onended=()=>{ osc.disconnect(); gain.disconnect(); };
      active.set(i,{osc,gain}); keys.children[i].setAttribute('aria-pressed','true');
    }
    const held=new Set();
    const press=(i,id)=>{ if(!held.has(id)) { held.add(id); on(i); } };
    const release=(i,id)=>{
      held.delete(id);
      if(![...held].some(v=>v.startsWith(i+'-'))) off(i);
    };
    notes.forEach((note,i)=>{
      const key=document.createElement('button'); key.type='button'; key.textContent=note;
      key.setAttribute('aria-label',note+', key '+keymap[i]); key.setAttribute('aria-pressed','false');
      if(note.includes('♯')) key.className='accidental';
      key.onpointerdown=e=>{ e.preventDefault(); key.setPointerCapture(e.pointerId); press(i,i+'-p'+e.pointerId); };
      key.onpointerup=key.onpointercancel=key.onlostpointercapture=e=>release(i,i+'-p'+e.pointerId);
      key.onkeydown=e=>{ if(e.key===' ' || e.key==='Enter'){e.preventDefault();press(i,i+'-enter');} };
      key.onkeyup=e=>{ if(e.key===' ' || e.key==='Enter'){e.preventDefault();release(i,i+'-enter');} };
      keys.append(key);
    });
    dialog.onkeydown=e=>{
      const i=keymap.indexOf(e.key.toLowerCase());
      if(i>=0 && e.key.length===1 && !e.ctrlKey && !e.altKey && !e.metaKey) {e.preventDefault();press(i,i+'-key');}
    };
    dialog.onkeyup=e=>{const i=keymap.indexOf(e.key.toLowerCase());if(i>=0) release(i,i+'-key');};
    const silence=()=>{ held.clear(); for(const i of [...active.keys()]) off(i); };
    window.addEventListener('blur',silence);
    close.onclick=()=>dialog.close();
    dialog.onclose=()=>{ closed=true;silence();window.removeEventListener('blur',silence);ctx.close().catch(()=>{});dialog.remove(); };
    dialog.append(title,hint,keys,close); document.body.append(dialog);
    dialog.showModal(); keys.children[0].focus();
    return 'Synth keyboard open.';
  }
  globalThis.MarianaToneProcedures=Object.freeze({families,help,plan,render,compile,completionRows});
})();

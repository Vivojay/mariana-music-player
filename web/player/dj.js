(() => {
  'use strict';
  const {Mixer, DiskCapture, clock, SHARE_LIMIT, MAX_BYTES, waveformPeaks, sampleWaveform, stereoMeter} = globalThis.MarianaDJEngine;
  const help = [
    'dj · dj status · dj load A|B [current] · dj play|pause|stop A|B · dj stop all',
    'dj seek A|B SECONDS · dj cue A|B set|go|clear 1–8 · dj loop A|B START END|off',
    'dj gain A|B 0–200 · dj rate A|B 0.25–4 · dj eq A|B low|mid|high −24..12',
    'dj crossfade 0–100 · dj headphones choose|off · dj pfl A|B on|off · dj record start|disk|stop · dj export · dj share'
  ].join('\n');
  const deckColors = {A:'#a9a5ff',B:'#efa678'};
  function scopeWindow(position, rate, span) {
    const half = span * rate / 2;
    return [position - half, position + half];
  }
  function paintWave(canvas, drawing, row, deck, position, start, end, overview) {
    const ratio = Math.min(2, globalThis.devicePixelRatio || 1);
    const width = Math.min(1800, Math.round(canvas.clientWidth * ratio));
    const height = Math.round(canvas.clientHeight * ratio);
    if (!width || !height || end <= start) return;
    const stamp = [
      width,height,position,start,end,Boolean(deck?.buffer),deck?.loop?.start,deck?.loop?.end,
      row.loopIn,...Array.from(deck?.cues || []).flat()
    ].join('/');
    if (drawing.stamp === stamp && drawing.peaks === row.peaks) return;
    const context = canvas.getContext('2d');
    if (!context) return;
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    if (drawing.columns?.length !== width * 2) drawing.columns = new Float32Array(width * 2);
    if (!overview || drawing.peaks !== row.peaks || drawing.sampleWidth !== width) {
      sampleWaveform(row.peaks,start,end,drawing.columns);
      drawing.sampleWidth = width;
    }
    drawing.stamp = stamp;
    drawing.peaks = row.peaks;
    const x = second => (second - start) / (end - start) * width;
    const mid = height / 2;
    context.clearRect(0,0,width,height);
    if (deck?.loop) {
      context.fillStyle = '#675a373b';
      const left = Math.max(0,x(deck.loop.start));
      const right = Math.min(width,x(deck.loop.end));
      if (right > left) context.fillRect(left,0,right-left,height);
    }
    context.fillStyle = '#494a59';
    context.fillRect(0,mid,width,1);
    if (!overview) {
      for (const fraction of [.125,.25,.375,.625,.75,.875])
        context.fillRect(Math.round(width*fraction),0,1,height);
    }
    if (!deck?.buffer) return;
    context.fillStyle = deckColors[deck.name];
    const density = overview ? .43 : .41;
    for (let column = 0; column < width; column++) {
      const low = drawing.columns[column*2], high = drawing.columns[column*2+1];
      if (high !== low) context.fillRect(column,mid-high*height*density,1,Math.max(1,(high-low)*height*density));
    }
    if (row.loopIn != null && !deck.loop) {
      const left = x(row.loopIn);
      context.fillStyle = '#ecc66f';
      if (left >= 0 && left <= width) context.fillRect(left,0,ratio,height);
    }
    context.fillStyle = '#f9c875';
    context.font = (10 * ratio) + 'px monospace';
    for (const [slot, second] of deck.cues) {
      const left = x(second);
      if (left < 0 || left > width) continue;
      context.fillRect(left,0,ratio,height);
      if (!overview) context.fillText(String(slot),Math.min(left + ratio * 3,width-ratio*8),ratio * 11);
    }
    context.fillStyle = '#f6f5ff';
    context.fillRect(Math.min(width - ratio,x(position)),0,ratio,height);
  }
  function mount(el, getCurrent, takeTransport, source = {}) {
    let mixer, result, resultURL = '', ticking, sharing = false;
    let headphones = null, choosingHeadphones = false, preparingTake = false;
    let readMeter, animation, lastPaint = -Infinity;
    const phone = () => !!globalThis.MarianaClipShare?.host() || globalThis.MarianaNativeShell === 'ios' || globalThis.location?.origin === 'https://app.mariana.invalid';
    const supportMonitor = !!(globalThis.navigator?.mediaDevices?.selectAudioOutput && globalThis.HTMLMediaElement?.prototype?.setSinkId);
    const rows = {}, panel = el('dj-studio');
    const message = text => { el('dj-status').textContent = text; };
    function engine() {
      if (!mixer) {
        const Context = globalThis.AudioContext || globalThis.webkitAudioContext;
        if (!Context) throw Error('This browser does not provide Web Audio.');
        mixer = new Mixer(new Context());
        readMeter = stereoMeter(mixer.ctx,mixer.master);
      }
      return mixer;
    }
    async function ready() {
      const mix = engine();
      if (mix.ctx.state !== 'running') await mix.ctx.resume();
      return mix;
    }
    function refresh() {
      for (const [name, row] of Object.entries(rows)) {
        const deck = mixer?.decks[name], u = row.ui, loaded = !!deck?.buffer;
        const pos = deck?.position() || 0, duration = deck?.duration || 0;
        u.title.textContent = deck?.title || 'No track loaded';
        u.play.textContent = deck?.source ? 'Pause' : 'Play';
        for (const key of ['play','stop','seek','in']) u[key].disabled = !loaded;
        u.pfl.disabled = !loaded || !headphones;
        u.pfl.setAttribute('aria-pressed', String(!!deck?.monitorBus));
        for (const [slot, pad] of row.pads) {
          const cue = deck?.cues.get(slot);
          pad.button.disabled = !loaded;
          pad.button.dataset.cued = String(cue !== undefined);
          pad.button.setAttribute('aria-pressed',String(cue !== undefined && row.selectedCue === slot));
          pad.button.setAttribute('aria-label', cue === undefined ? 'Set cue ' + slot :
            'Jump to cue ' + slot + ' at ' + clock(cue));
          pad.time.textContent = cue === undefined ? '—' : clock(cue);
        }
        const selected = deck?.cues.has(row.selectedCue);
        u.clear.disabled = !selected;
        u.clear.textContent = selected ? 'Clear cue ' + row.selectedCue : 'Clear selected';
        u.out.disabled = !loaded || row.loopIn == null;
        u.off.disabled = !deck?.loop && row.loopIn == null;
        u['loop-info'].textContent = deck?.loop ? clock(deck.loop.start) + ' – ' + clock(deck.loop.end) :
          row.loopIn != null ? 'In at ' + clock(row.loopIn) : 'Off';
        u.clock.textContent = clock(pos) + ' / ' + clock(loaded ? duration : NaN);
        row.wave.position.textContent = clock(loaded ? pos : NaN);
        row.wave.detail.dataset.loaded = String(loaded);
        u.overview.dataset.loaded = String(loaded);
        u.seek.max = String(duration || 1);
        if (!row.scrubbing) u.seek.value = String(pos);
        for (const [key, val, label] of [['gain',deck?.gain ?? 100,'%'],['rate',deck?.rate ?? 1,'×']]) {
          u[key].value = String(val);
          u[key+'-value'].textContent = (key === 'rate' ? val.toFixed(2) : val) + label;
        }
      }
      const b = mixer?.balance ?? 0; el('dj-cross').value = String(b);
      el('dj-balance').textContent = b === 50 ? 'Center' : 'A ' + (100-b) + ' / B ' + b;
      el('dj-headphones').disabled = !supportMonitor || choosingHeadphones;
      el('dj-headphones-off').hidden = !headphones;
      el('dj-monitor-status').textContent = headphones ? 'Headphone cue routes to ' + headphones.label + '. Master uses the system output.' :
        supportMonitor ? 'Use a separate hardware output to audition a deck before the crossfade. Master uses the system output.' :
        'This browser has one master output. Separate headphone routing is unavailable.';
      const record = mixer?.recording;
      el('dj-record').textContent = record ? 'Stop recording' : 'Record master';
      el('dj-record').disabled = preparingTake || Boolean(record?.stopping);
      el('dj-record-disk').hidden = typeof globalThis.showSaveFilePicker !== 'function' || phone();
      el('dj-record-disk').disabled = preparingTake || !!record;
      el('dj-record-time').textContent = record ? 'Recording · ' + clock(record.size / (mixer.ctx.sampleRate * 4)) :
        result ? 'Last mix · ' + clock(result.seconds) : '';
      el('dj-save').hidden = !result;
      const bridge = globalThis.MarianaClipShare;
      const canShare = !!result && bridge?.available(result.file) && (!bridge.host() || result.file.size <= SHARE_LIMIT);
      el('dj-share').hidden = !canShare; el('dj-share').disabled = sharing;
    }
    function paint(time) {
      animation = undefined;
      if (panel.hidden) return;
      if (time - lastPaint >= 32) {
        lastPaint = time;
        const span = Number(el('dj-span').value);
        for (const [name, row] of Object.entries(rows)) {
          const deck = mixer?.decks[name], position = deck?.position() || 0;
          const [start,end] = scopeWindow(position,deck?.rate || 1,span);
          paintWave(row.wave.detail,row.detailDrawing,row,deck,position,start,end,false);
          paintWave(row.ui.overview,row.overviewDrawing,row,deck,position,0,deck?.duration || 1,true);
        }
        if (readMeter && mixer.ctx.state === 'running') {
          const [left,right] = readMeter();
          el('dj-meter-l').value = left;
          el('dj-meter-r').value = right;
        }
      }
      animation = requestAnimationFrame(paint);
    }
    function toggle(open, focus) {
      panel.hidden = !open;
      const btn = el('dj-open'); btn.textContent = open ? 'Close mixer' : 'Open mixer';
      btn.setAttribute('aria-expanded',String(open));
      clearInterval(ticking);
      cancelAnimationFrame(animation);
      if (open) {
        refresh();
        renderCrate();
        ticking = setInterval(refresh,175);
        animation = requestAnimationFrame(paint);
      }
      if (focus) el('dj-title').focus();
    }
    function show() { if (panel.hidden) toggle(true,false); }
    function safe(fn) {
      return async () => {
        try { const response = await fn(); if (response) message(response); }
        catch (error) { message(error.message || String(error)); }
        refresh();
      };
    }
    function renderCrate() {
      const query = el('dj-crate-search').value.trim().toLowerCase();
      const tracks = source.listLocal?.() || [];
      const matching = tracks.filter(item => (item.title + ' ' + (item.by || '')).toLowerCase().includes(query));
      const list = el('dj-crate-list');
      list.replaceChildren();
      for (const track of matching.slice(0, 60)) {
        const row = document.createElement('li'), label = document.createElement('div');
        const title = document.createElement('b');
        title.textContent = track.title; label.append(title);
        if (track.by) {
          const artist = document.createElement('span');
          artist.textContent = track.by; label.append(artist);
        }
        row.append(label);
        for (const name of ['A','B']) {
          const button = document.createElement('button');
          button.type = 'button';
          button.dataset.deck = name;
          button.textContent = 'Load ' + name;
          button.setAttribute('aria-label', 'Load ' + track.title + ' into deck ' + name);
          button.onclick = safe(() => load(name, () => source.getLocal(track.id)));
          row.append(button);
        }
        list.append(row);
      }
      const note = el('dj-crate-empty');
      note.hidden = matching.length > 0 && matching.length <= 60;
      note.textContent = !tracks.length ? 'Import tracks in Local library, or choose a file on either deck.' :
        !matching.length ? 'No tracks match this filter.' : 'Showing 60 of ' + matching.length + ' matches. Narrow the filter to find more.';
    }
    async function load(name, file) {
      const deck = engine().decks[name];
      message('Loading deck ' + name + '…');
      if (!await deck.load(file)) return '';
      const row = rows[name];
      row.loopIn = null; row.selectedCue = null; row.peaks = null;
      const activeBuffer = deck.buffer;
      void waveformPeaks(activeBuffer, () => deck.buffer === activeBuffer).then(peaks => {
        if (deck.buffer === activeBuffer) row.peaks = peaks;
      }).catch(() => {
        if (deck.buffer === activeBuffer) message('Deck ' + name + ' loaded. The waveform could not be displayed.');
      });
      return 'Deck ' + name + ' loaded ' + deck.title + '.';
    }
    async function transport(name, action) {
      const deck = engine().decks[name];
      if (action === 'play') { deck.requireFile(); await ready(); takeTransport(); deck.play(); }
      else { deck.pause(); if (action === 'stop') { deck.offset = 0; deck.loop = null; rows[name].loopIn = null; } }
      return 'Deck ' + name + (action === 'play' ? ' playing.' : action === 'pause' ? ' paused.' : ' stopped.');
    }
    function disconnectHeadphones() {
      if (!headphones) return;
      for (const name of ['A','B']) mixer.monitor(name,false);
      headphones.audio.pause(); headphones.audio.srcObject = null; headphones.bus.disconnect();
      headphones.destination.stream.getTracks().forEach(track => track.stop());
      headphones = null; refresh();
    }
    async function chooseHeadphones() {
      if (!supportMonitor) throw Error('Output selection is unavailable in this browser.');
      if (choosingHeadphones) throw Error('The output chooser is open.');
      choosingHeadphones = true; refresh();
      let destination, audio, bus;
      try {
        const device = await navigator.mediaDevices.selectAudioOutput();
        const available = await navigator.mediaDevices.enumerateDevices();
        const normal = available.find(entry => entry.kind === 'audiooutput' && entry.deviceId === 'default');
        if (!device.deviceId || device.deviceId === 'default' || (device.groupId && device.groupId === normal?.groupId))
          throw Error('Choose headphones connected to a different output from the system speakers.');
        const mix = await ready(); destination = mix.ctx.createMediaStreamDestination();
        bus = mix.ctx.createGain(); bus.gain.value = 0.5; bus.connect(destination);
        audio = new Audio(); await audio.setSinkId(device.deviceId); audio.srcObject = destination.stream; await audio.play();
        disconnectHeadphones();
        headphones = {audio,bus,destination,label:device.label || 'selected output'}; return 'Choose Headphone cue on the deck to audition.';
      } catch (error) {
        if (audio) { audio.pause(); audio.srcObject = null; }
        bus?.disconnect(); destination?.stream.getTracks().forEach(track => track.stop());
        throw error;
      } finally { choosingHeadphones = false; refresh(); }
    }
    function pfl(name, on) {
      const mix = engine();
      if (!headphones) throw Error('Choose a separate headphone output first.');
      mix.decks[name].requireFile(); mix.monitor(name,on,headphones.bus);
      return 'Deck ' + name + ' headphone cue ' + (on ? 'on.' : 'off.');
    }
    async function record(action) {
      if (action === 'stop') { engine().stopRecording(); return 'Finishing master WAV…'; }
      const toDisk = action === 'disk';
      if (action !== 'start' && !toDisk) throw Error('Use dj record start, dj record disk or dj record stop.');
      const mix = engine();
      if (preparingTake || mix.recording) throw Error('A recording is already being prepared or captured.');
      if (!Object.values(mix.decks).some(deck => deck.buffer)) throw Error('Load at least one deck before recording.');
      const limit = toDisk ? 0xffffffd0 : phone() ? SHARE_LIMIT : MAX_BYTES;
      preparingTake = true; refresh();
      try {
        let handle = null;
        if (toDisk) {
          if (typeof globalThis.showSaveFilePicker !== 'function' || phone())
            throw Error('Direct-to-disk recording is unavailable here. Use Record master for a bounded WAV.');
          handle = await globalThis.showSaveFilePicker({suggestedName:'Mariana DJ set.wav',
            types:[{description:'Stereo WAV',accept:{'audio/wav':['.wav']}}]});
        }
        await ready();
        const disk = handle ? await DiskCapture.open(handle,mix.ctx.sampleRate) : null;
        await mix.record((file, seconds, reason) => {
          if (file) {
            if (resultURL) URL.revokeObjectURL(resultURL);
            result = {file, seconds}; resultURL = URL.createObjectURL(file);
            el('dj-save').href = resultURL; el('dj-save').download = file.name;
          }
          const outcome = file ? (disk ? 'Saved the master WAV to ' + file.name + '.' : 'Master WAV ready to save.') :
            reason ? '' : 'No audio was captured.';
          message([reason,outcome].filter(Boolean).join(' ')); refresh();
        },limit,disk);
        return toDisk ? 'Recording directly to ' + handle.name + '. Stop to finish the WAV.' :
          'Recording both decks. This take can hold ' + clock(Math.floor((limit-44) / (4*mix.ctx.sampleRate))) + ' at this sample rate.';
      } finally { preparingTake = false; refresh(); }
    }
    async function share() {
      if (!result) throw Error('Stop a recording to prepare a WAV.');
      const bridge = globalThis.MarianaClipShare;
      if (!bridge?.available(result.file) || (bridge.host() && result.file.size > SHARE_LIMIT))
        throw Error('Download the WAV and open it in your chosen app.');
      if (sharing) throw Error('The share sheet is already open.');
      sharing = true; refresh();
      try { await bridge.share(result.file,'system',result.seconds); return 'Share sheet closed.'; }
      finally { sharing = false; refresh(); }
    }
    function bindDeck(name) {
      const fragment = el('dj-deck').content.cloneNode(true);
      const ui = Object.fromEntries(Array.from(fragment.querySelectorAll('[data-ui]'), node => [node.dataset.ui,node]));
      const waveFragment = el('dj-wave-row').content.cloneNode(true);
      const wave = Object.fromEntries(Array.from(waveFragment.querySelectorAll('[data-wave]'), node => [node.dataset.wave,node]));
      wave.name.textContent = name;
      wave.detail.title = 'Click or tap to seek deck ' + name;
      waveFragment.firstElementChild.dataset.deck = name;
      el('dj-waveforms').append(waveFragment);
      const row = rows[name] = {ui,wave,detailDrawing:{},overviewDrawing:{},pads:new Map(),loopIn:null,scrubbing:false};
      const deck = () => engine().decks[name];
      ui.name.textContent = name;
      fragment.firstElementChild.dataset.deck = name;
      for (const key of ['seek','rate']) {
        ui[key].id = 'dj-' + name.toLowerCase() + '-' + key;
        ui[key].closest('label').htmlFor = ui[key].id;
        ui[key].setAttribute('aria-label','Deck ' + name + ' ' + (key === 'seek' ? 'position' : 'playback rate'));
      }
      for (let slot = 1; slot <= 8; slot++) {
        const pad = document.createElement('button'), time = document.createElement('span');
        pad.type = 'button'; pad.dataset.slot = String(slot);
        pad.append(String(slot),time);
        ui.pads.append(pad); row.pads.set(slot,{button:pad,time});
        pad.onclick = safe(() => {
          const d = deck(), action = d.cues.has(slot) ? 'go' : 'set';
          d.cue(action,slot); row.selectedCue = slot;
          return 'Deck ' + name + ' · cue ' + slot + ' at ' + clock(d.position()) + '.';
        });
      }
      ui.clear.onclick = safe(() => {
        const slot = row.selectedCue;
        if (slot == null) return '';
        deck().cue('clear',slot); row.selectedCue = null;
        return 'Cleared cue ' + slot + ' on deck ' + name + '.';
      });
      ui.file.onchange = safe(() => { const file = ui.file.files[0]; ui.file.value = ''; return file ? load(name,() => file) : ''; });
      ui.queue.onclick = safe(() => load(name,getCurrent));
      ui.play.onclick = safe(() => transport(name,deck().source ? 'pause' : 'play'));
      ui.stop.onclick = safe(() => transport(name,'stop'));
      ui.pfl.onclick = safe(() => pfl(name,!deck().monitorBus));
      ui.seek.onpointerdown = () => { row.scrubbing = true; };
      ui.seek.onpointerup = ui.seek.onpointercancel = ui.seek.onblur = () => { row.scrubbing = false; };
      ui.seek.onchange = safe(() => { row.scrubbing = false; deck().seek(ui.seek.value); });
      for (const canvas of [ui.overview,wave.detail]) canvas.onclick = event => {
        const d = mixer?.decks[name], bounds = canvas.getBoundingClientRect();
        if (!d?.buffer || !bounds.width) return;
        const [start,end] = canvas === ui.overview ? [0,d.duration] :
          scopeWindow(d.position(),d.rate,Number(el('dj-span').value));
        const fraction = (event.clientX-bounds.left) / bounds.width;
        d.seek(Math.max(0,Math.min(d.duration,start+fraction*(end-start))));
        refresh();
      };
      ui.rate.oninput = safe(() => { deck().setRate(ui.rate.value); });
      ui.in.onclick = safe(() => { row.loopIn = deck().position(); return 'Loop in marked.'; });
      ui.out.onclick = safe(() => { deck().setLoop(row.loopIn,deck().position()); row.loopIn = null; return 'Loop enabled.'; });
      ui.off.onclick = safe(() => { deck().setLoop('off'); row.loopIn = null; return 'Loop cleared.'; });
      bindStrip(name,ui,deck);
      const grid = el('dj-decks');
      if (name === 'A') grid.insertBefore(fragment,el('dj-master'));
      else grid.append(fragment);
    }
    function bindStrip(name,ui,deck) {
      const strip = document.createElement('div'), heading = document.createElement('h4');
      strip.className = 'dj-channel'; strip.dataset.deck = name;
      heading.textContent = 'Deck ' + name;
      strip.append(heading);
      function fader(key, caption, min, max, value, unit) {
        const label = document.createElement('label'), input = document.createElement('input'), out = document.createElement('output');
        input.type = 'range'; input.min = String(min); input.max = String(max);
        input.step = '1'; input.value = String(value);
        input.id = 'dj-' + name.toLowerCase() + '-' + key;
        input.setAttribute('aria-label','Deck ' + name + ' ' + caption.toLowerCase());
        out.textContent = value + unit;
        label.htmlFor = input.id; ui[key] = input; ui[key+'-value'] = out;
        label.append(caption,out,input); strip.append(label);
        return input;
      }
      fader('gain','Gain',0,200,100,'%').oninput = safe(() => { deck().setGain(ui.gain.value); });
      for (const band of ['low','mid','high']) {
        const input = fader(band,band[0].toUpperCase() + band.slice(1),-24,12,0,' dB');
        input.oninput = safe(() => { deck().setEQ(band,input.value); ui[band+'-value'].textContent = input.value + ' dB'; });
      }
      el('dj-channels').append(strip);
    }
    async function command(args) {
      const [action, rawDeck, option, value] = args;
      const name = rawDeck?.toUpperCase();
      if (action === 'help') return help;
      show();
      if (!action) { el('dj-title').focus(); el('dj-title').scrollIntoView({block:'start'}); return 'DJ studio opened.'; }
      try {
        if (action === 'status') return ['A','B'].map(id => {
          const deck = mixer?.decks[id];
          return id + ' · ' + (deck?.title || 'empty') + (deck?.buffer ? ' · ' + (deck.source ? 'playing ' : 'paused ') + clock(deck.position()) : '');
        }).concat('Crossfader ' + (mixer?.balance ?? 0) + '% · ' + (mixer?.recording ? 'recording' : 'recorder idle')).join('\n');
        if (action === 'record') return await record(rawDeck);
        if (action === 'share') return await share();
        if (action === 'headphones') {
          if (rawDeck === 'choose') return await chooseHeadphones();
          if (rawDeck === 'off') { disconnectHeadphones(); return 'Headphone output disconnected.'; }
          throw Error('Use dj headphones choose or dj headphones off.');
        }
        if (action === 'export') { if (!result) throw Error('Stop a recording to prepare a WAV.'); el('dj-save').click(); return 'Downloading the master WAV.'; }
        if (action === 'crossfade') {
          if (args.length !== 2) throw Error('Use dj crossfade 0–100 in this player.');
          engine().crossfade(rawDeck); return 'Crossfader ' + rawDeck + '%.';
        }
        if (action === 'stop' && name === 'ALL') {
          for (const id of ['A','B']) await transport(id,'stop');
          return 'Both decks stopped.';
        }
        if (!rows[name]) throw Error('Choose deck A or B. Type dj help for commands.');
        if (action === 'load') {
          if (option === 'current') return await load(name,getCurrent);
          if (option) throw Error('Use dj load ' + name + ' or dj load ' + name + ' current.');
          rows[name].ui.file.click(); return 'Choose a local audio file for deck ' + name + '.';
        }
        if (action === 'pfl') {
          if (!['on','off'].includes(option)) throw Error('Use dj pfl A|B on|off.');
          return pfl(name,option === 'on');
        }
        if (['play','pause','stop'].includes(action)) return await transport(name,action);
        const deck = engine().decks[name];
        if (action === 'seek') deck.seek(option);
        else if (action === 'gain') deck.setGain(option);
        else if (action === 'rate') deck.setRate(option);
        else if (action === 'cue') {
          deck.cue(option,value);
          rows[name].selectedCue = option === 'clear' ? null : Number(value);
        }
        else if (action === 'loop') { deck.setLoop(option,value); rows[name].loopIn = null; }
        else if (action === 'eq') {
          deck.setEQ(option, value);
          rows[name].ui[option].value = value; rows[name].ui[option+'-value'].textContent = value + ' dB';
        } else throw Error('Unknown DJ command. Type dj help.');
        return 'Updated deck ' + name + '.';
      } finally { refresh(); }
    }
    bindDeck('A'); bindDeck('B');
    el('dj-crate-search').oninput = renderCrate;
    el('dj-open').onclick = () => toggle(panel.hidden,false);
    el('dj-cross').oninput = safe(() => { engine().crossfade(el('dj-cross').value); });
    el('dj-record').onclick = safe(() => record(mixer?.recording ? 'stop' : 'start'));
    el('dj-record-disk').onclick = safe(() => record('disk'));
    el('dj-share').onclick = safe(share);
    el('dj-headphones').onclick = safe(chooseHeadphones);
    el('dj-headphones-off').onclick = safe(() => { disconnectHeadphones(); return 'Headphone output disconnected.'; });
    navigator.mediaDevices?.addEventListener?.('devicechange', disconnectHeadphones);
    window.addEventListener('mariana-clip-share-ready',refresh);
    window.addEventListener('pagehide',() => {
      clearInterval(ticking); cancelAnimationFrame(animation);
      disconnectHeadphones(); mixer?.pause(); if (mixer?.recording) mixer.stopRecording();
    });
    window.addEventListener('pageshow',() => { if (!panel.hidden) toggle(true,false); });
    return {command, pause() { mixer?.pause(); refresh(); }, refreshLibrary() { if (!panel.hidden) renderCrate(); }};
  }
  globalThis.MarianaDJ = {mount};
})();

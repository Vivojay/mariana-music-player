/* Audio graph, deck transports and PCM master recorder shared by Console and Flow. */
(() => {
  'use strict';
  const MIB = 1024 * 1024;
  const MAX_BYTES = 128 * MIB;
  const SHARE_LIMIT = 32 * MIB;
  function number(value, min, max, label) {
    const n = Number(value);
    if (value == null || String(value).trim() === '' || !Number.isFinite(n) || n < min || n > max)
      throw Error(label + ' must be between ' + min + ' and ' + max + '.');
    return n;
  }
  function weights(percent) {
    const position = number(percent, 0, 100, 'Crossfader');
    if (position === 0) return [1, 0];
    if (position === 100) return [0, 1];
    const angle = position * Math.PI / 200;
    return [Math.cos(angle), Math.sin(angle)];
  }
  function clock(seconds) {
    if (!Number.isFinite(seconds)) return '–:––';
    const whole = Math.max(0, Math.floor(seconds));
    return Math.floor(whole / 60) + ':' + String(whole % 60).padStart(2, '0');
  }
  // Keep a signed peak for each side of every 128-frame bucket. The minimum
  // and maximum are across channels, so out-of-phase stereo stays visible.
  async function waveformPeaks(buffer, current = () => true) {
    const stride = 128;
    const count = Math.ceil(buffer.length / stride);
    const points = new Float32Array(count * 2);
    const channels = Array.from({length:buffer.numberOfChannels}, (_, i) => buffer.getChannelData(i));
    for (let bucket = 0; bucket < count; bucket++) {
      if (bucket > 0 && bucket % 1024 === 0) {
        await new Promise(resolve => setTimeout(resolve, 0));
        if (!current()) return null;
      }
      const start = bucket * stride;
      const end = Math.min(start + stride, buffer.length);
      let low = 0, high = 0;
      for (const samples of channels) {
        for (let i = start; i < end; i++) {
          const value = samples[i];
          if (value < low) low = value;
          if (value > high) high = value;
        }
      }
      points[bucket * 2] = low;
      points[bucket * 2 + 1] = high;
    }
    return {points,bucketsPerSecond:buffer.sampleRate / stride};
  }
  function sampleWaveform(peaks, start, end, columns) {
    columns.fill(0);
    if (!peaks) return columns;
    const count = columns.length / 2;
    const step = (end - start) * peaks.bucketsPerSecond / count;
    const origin = start * peaks.bucketsPerSecond;
    const available = peaks.points.length / 2;
    for (let i = 0; i < count; i++) {
      const from = Math.max(0, Math.floor(origin + i * step));
      const to = Math.min(available, Math.ceil(origin + (i + 1) * step));
      let low = 0, high = 0;
      for (let bucket = from; bucket < to; bucket++) {
        low = Math.min(low, peaks.points[bucket * 2]);
        high = Math.max(high, peaks.points[bucket * 2 + 1]);
      }
      columns[i * 2] = low;
      columns[i * 2 + 1] = high;
    }
    return columns;
  }
  function stereoMeter(context, node) {
    if (!context.createChannelSplitter || !context.createAnalyser) return null;
    const splitter = context.createChannelSplitter(2);
    node.connect(splitter);
    const channels = ['L','R'].map((_, i) => {
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      splitter.connect(analyser, i, 0);
      return {analyser,samples:new Float32Array(analyser.fftSize)};
    });
    return () => channels.map(({analyser,samples}) => {
      analyser.getFloatTimeDomainData(samples);
      let amplitude = 0;
      for (const sample of samples) amplitude = Math.max(amplitude, Math.abs(sample));
      return amplitude > 0 ? Math.max(-60, 20 * Math.log10(amplitude)) : -60;
    });
  }
  function wavHeader(size, rate) {
    const data = new DataView(new ArrayBuffer(44));
    for (const [offset, name] of [[0,'RIFF'],[8,'WAVEfmt '],[36,'data']])
      Array.from(name).forEach((c, i) => data.setUint8(offset + i, c.charCodeAt(0)));
    for (const [offset, value] of [[4,size+36],[16,16],[24,rate],[28,rate*4],[40,size]]) data.setUint32(offset,value,true);
    for (const [offset, value] of [[20,1],[22,2],[32,4],[34,16]]) data.setUint16(offset,value,true);
    return data.buffer;
  }
  // A picked file is committed after the RIFF header and all queued sample blocks are written.
  class DiskCapture {
    static async open(handle, rate) {
      const output = await handle.createWritable();
      try {
        await output.write(wavHeader(0,rate));
        return new DiskCapture(handle,output);
      } catch (error) { await output.abort().catch(() => {}); throw error; }
    }
    constructor(handle, output) {
      this.handle = handle; this.output = output; this.queued = 0; this.tail = Promise.resolve();
    }
    push(block) {
      if (this.error || this.queued + block.byteLength > 8 * MIB) return false;
      this.queued += block.byteLength;
      this.tail = this.tail.then(async () => {
        try { if (!this.error) await this.output.write(block); }
        catch (error) { this.error = error; this.onError?.(); }
        finally { this.queued -= block.byteLength; }
      });
      return true;
    }
    async finish(size, rate) {
      await this.tail;
      if (this.error) throw this.error;
      await this.output.seek(0); await this.output.write(wavHeader(size,rate));
      await this.output.close();
      return this.handle.getFile();
    }
    async abort() { await this.tail; await this.output.abort().catch(() => {}); }
  }
  class Deck {
    constructor(name, ctx, bus) {
      this.name = name;
      this.ctx = ctx;
      this.title = '';
      this.buffer = null;
      this.source = null;
      this.offset = 0;
      this.rate = 1;
      this.gain = 100;
      this.generation = 0;
      this.loop = null;
      this.cues = new Map();
      this.eq = Object.fromEntries([['low','lowshelf',250], ['mid','peaking',1200], ['high','highshelf',4000]].map(([band,type,hz]) => {
        const filter = ctx.createBiquadFilter(); filter.type = type; filter.frequency.value = hz;
        if (band === 'mid') filter.Q.value = 0.8;
        return [band,filter];
      }));
      this.trim = ctx.createGain();
      this.fader = ctx.createGain();
      this.eq.low.connect(this.eq.mid).connect(this.eq.high).connect(this.trim).connect(this.fader).connect(bus);
    }
    get duration() { return this.buffer?.duration || 0; }
    position() {
      let pos = this.offset;
      if (this.source) pos += (this.ctx.currentTime - this.started) * this.rate;
      if (this.loop && pos >= this.loop.end) pos = this.loop.start + (pos - this.loop.start) % (this.loop.end - this.loop.start);
      return Math.min(this.duration, pos);
    }
    requireFile() { if (!this.buffer) throw Error('Load a local file on deck ' + this.name + ' first.'); }
    async load(getFile) {
      const version = ++this.generation;
      const file = await getFile();
      if (!file) throw Error('Select a local track in the queue or choose a file.');
      if (file.size > 96 * MIB) throw Error('Choose a file under 96 MiB for this browser deck.');
      const bytes = await file.arrayBuffer();
      if (version !== this.generation) return false;
      let buffer;
      try { buffer = await this.ctx.decodeAudioData(bytes); }
      catch { throw Error('This browser could not decode that audio file. Try a WAV or MP3 file.'); }
      if (version !== this.generation) return false;
      if (!buffer.length || buffer.numberOfChannels * buffer.length * 4 > 192 * MIB)
        throw Error('This track exceeds the 192 MiB decoded limit for one browser deck.');
      this.pause(); this.buffer = buffer; this.title = file.name || 'Queue track';
      this.offset = 0; this.cues.clear(); this.loop = null;
      return true;
    }
    play() {
      this.requireFile();
      if (this.source) return;
      if (this.offset >= this.duration) this.offset = this.loop?.start || 0;
      const source = this.ctx.createBufferSource(); source.buffer = this.buffer;
      source.playbackRate.value = this.rate;
      if (this.loop) { source.loopStart = this.loop.start; source.loopEnd = this.loop.end; source.loop = true; }
      source.connect(this.eq.low); this.started = this.ctx.currentTime; this.source = source;
      source.onended = () => {
        source.disconnect();
        if (this.source === source) { this.source = null; this.offset = this.duration; }
      };
      try { source.start(0, this.offset); }
      catch (error) { this.source = null; source.disconnect(); throw error; }
    }
    pause() {
      if (!this.source) return;
      this.offset = this.position(); const source = this.source; this.source = null;
      source.stop(); source.disconnect();
    }
    seek(value) {
      this.requireFile(); const pos = number(value, 0, this.duration, 'Position');
      const playing = !!this.source; this.pause();
      if (this.loop && (pos < this.loop.start || pos >= this.loop.end)) this.loop = null;
      this.offset = pos; if (playing && pos < this.duration) this.play();
    }
    setRate(value) {
      const next = number(value, 0.25, 4, 'Rate');
      this.offset = this.position(); this.started = this.ctx.currentTime; this.rate = next;
      if (this.source) this.source.playbackRate.value = next;
    }
    setGain(value) {
      this.gain = number(value, 0, 200, 'Gain');
      this.trim.gain.setTargetAtTime(this.gain / 100, this.ctx.currentTime, 0.008);
    }
    setEQ(band, value) {
      if (!Object.prototype.hasOwnProperty.call(this.eq, band)) throw Error('Choose low, mid or high.');
      this.eq[band].gain.setTargetAtTime(number(value, -24, 12, 'EQ'), this.ctx.currentTime, 0.008);
    }
    setLoop(start, end) {
      this.requireFile();
      let region = null;
      if (start !== 'off') {
        const a = number(start, 0, this.duration, 'Loop in'), b = number(end, 0, this.duration, 'Loop out');
        if (b - a < 0.05) throw Error('Choose a loop at least 0.05 seconds long.');
        region = {start:a, end:b};
      }
      const playing = !!this.source; this.pause(); this.loop = region;
      if (region && (this.offset < region.start || this.offset >= region.end)) this.offset = region.start;
      if (playing) this.play();
    }
    cue(action, value) {
      this.requireFile(); const slot = number(value, 1, 8, 'Cue slot');
      if (!Number.isInteger(slot)) throw Error('Choose a whole-number cue slot.');
      if (action === 'set') this.cues.set(slot, this.position());
      else if (action === 'clear') this.cues.delete(slot);
      else if (action === 'go' && this.cues.has(slot)) this.seek(this.cues.get(slot));
      else throw Error('Set this cue before jumping to it.');
    }
  }
  class Mixer {
    constructor(ctx) {
      this.ctx = ctx; this.bus = ctx.createGain();
      // Leave room at center for two correlated full-scale tracks.
      this.bus.gain.value = Math.SQRT1_2;
      this.bus.channelCount = 2; this.bus.channelCountMode = 'explicit';
      this.master = ctx.createDynamicsCompressor(); this.master.threshold.value = -1;
      this.master.knee.value = 0; this.master.ratio.value = 20;
      this.master.attack.value = 0.003; this.master.release.value = 0.12;
      this.bus.connect(this.master).connect(ctx.destination);
      this.decks = Object.fromEntries(['A','B'].map(name => [name,new Deck(name,ctx,this.bus)]));
      this.crossfade(0);
    }
    crossfade(value) {
      const [a,b] = weights(value);
      this.decks.A.fader.gain.setTargetAtTime(a,this.ctx.currentTime,0.008);
      this.decks.B.fader.gain.setTargetAtTime(b,this.ctx.currentTime,0.008);
      this.balance = Number(value);
    }
    pause() { Object.values(this.decks).forEach(deck => deck.pause()); }
    monitor(deckName, enabled, destination) {
      const deck = this.decks[deckName];
      if (!deck || (enabled && !destination)) throw Error('Choose a headphone output first.');
      if (deck.monitorBus) { deck.trim.disconnect(deck.monitorBus); deck.monitorBus = null; }
      if (enabled) { deck.trim.connect(destination); deck.monitorBus = destination; }
    }
    async record(onFinish, limit = MAX_BYTES, disk = null) {
      if (this.recording) throw Error('A master recording is already in progress.');
      const record = {size:0, chunks:[], stopping:false};
      this.recording = record;
      let node;
      const finish = error => {
        if (this.recording !== record || record.finishing) return;
        record.finishing = record.stopping = true;
        this.master.disconnect(node); node.disconnect();
        if (node.port) node.port.close(); else node.onaudioprocess = null;
        const done = (file, reason) => {
          this.recording = null; record.chunks.length = 0;
          onFinish(file, file ? record.size / (4 * this.ctx.sampleRate) : 0,
            reason || error || record.warning || (record.limited ? 'Recording reached the WAV size limit.' : ''));
        };
        if (disk) {
          if (!record.size) { disk.abort().then(() => done(null)); return; }
          disk.finish(record.size,this.ctx.sampleRate).then(file => done(file), async cause => {
            await disk.abort(); done(null,'Could not save the master to disk: ' + cause.message);
          });
        } else {
          const file = record.size ? new File([wavHeader(record.size,this.ctx.sampleRate),...record.chunks],
            'Mariana-DJ-' + new Date().toISOString().replace(/[:.]/g,'-') + '.wav',{type:'audio/wav'}) : null;
          done(file);
        }
      };
      const append = block => {
        if (record.finishing || record.warning) return;
        const length = Math.min(block.byteLength, Math.floor((limit - 44 - record.size) / 4) * 4);
        if (length > 0) {
          const data = length === block.byteLength ? block : block.slice(0,length);
          if (disk && !disk.push(data)) {
            record.warning = 'Disk writing fell behind. Recording stopped at the last captured block.';
            this.stopRecording(); return;
          }
          if (!disk) record.chunks.push(data);
          record.size += length;
        }
        if (record.size >= limit - 44 && !record.stopping) { record.limited = true; this.stopRecording(); }
      };
      if (disk) disk.onError = () => { if (!record.stopping) this.stopRecording(); };
      try {
        if (this.ctx.audioWorklet) {
          try {
            if (this.module == null) this.module = this.ctx.audioWorklet.addModule('dj-recorder.js').catch(error => { this.module = null; throw error; });
            await this.module;
            node = new AudioWorkletNode(this.ctx,'mariana-mix-recorder',{channelCount:2,channelCountMode:'explicit',outputChannelCount:[1]});
          } catch { /* A bundled file URL can reject worklet modules. */ }
        }
        if (node) {
          record.stop = () => node.port.postMessage('stop');
          node.port.onmessage = ({data}) => data === 'stopped' ? finish() : append(data);
          node.onprocessorerror = () => finish('Audio capture was interrupted.');
        } else {
          if (!this.ctx.createScriptProcessor) throw Error('This browser cannot record the master. Try a current browser on localhost or HTTPS.');
          node = this.ctx.createScriptProcessor(4096,2,1);
          record.stop = () => queueMicrotask(() => finish());
          node.onaudioprocess = event => {
            if (record.stopping) return;
            const left = event.inputBuffer.getChannelData(0), right = event.inputBuffer.getChannelData(1);
            const view = new DataView(new ArrayBuffer(left.length * 4));
            for (let i=0; i<left.length; i++) {
              const a = Math.min(1, Math.max(-1,left[i])), b = Math.min(1, Math.max(-1,right[i]));
              view.setInt16(i*4,Math.round(a * (a < 0 ? 32768 : 32767)),true);
              view.setInt16(i*4+2,Math.round(b * (b < 0 ? 32768 : 32767)),true);
            }
            append(view.buffer);
          };
        }
        this.master.connect(node); node.connect(this.ctx.destination); // The capture branch emits silence.
        if (record.stopping) record.stop();
      } catch (error) { this.recording = null; if (disk) await disk.abort(); throw error; }
    }
    stopRecording() {
      if (!this.recording) throw Error('No master recording is running.');
      if (this.recording.stopping) return;
      this.recording.stopping = true; this.recording.stop?.();
    }
  }
  globalThis.MarianaDJEngine = {
    Mixer, DiskCapture, weights, clock, wavHeader, number, MAX_BYTES, SHARE_LIMIT,
    waveformPeaks, sampleWaveform, stereoMeter
  };
})();

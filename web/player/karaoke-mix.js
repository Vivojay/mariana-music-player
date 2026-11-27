'use strict';
(() => {
  // Subtract a listener-supplied isolated vocal from corresponding PCM samples.
  // No second player or independent clock is involved during playback.
  const rate = 44100, maxFrames = rate * 300, maxFile = 64 * 1024 * 1024;
  function metadata(file) {
    return new Promise((resolve, reject) => {
      const audio = new Audio(), url = URL.createObjectURL(file);
      const finish = (fn, value) => {
        clearTimeout(timer); audio.onloadedmetadata = audio.onerror = null;
        audio.removeAttribute('src'); audio.load(); URL.revokeObjectURL(url); fn(value);
      };
      const timer = setTimeout(() => finish(reject, Error('Timed out reading the vocal stem.')), 12000);
      audio.preload = 'metadata';
      audio.onloadedmetadata = () => finish(resolve, audio.duration);
      audio.onerror = () => finish(reject, Error('Could not read the supplied vocal stem.'));
      audio.src = url;
    });
  }
  function checkPair(master, vocal) {
    if (master.sampleRate !== vocal.sampleRate || master.length !== vocal.length)
      throw Error('The isolated vocal must have the same sample-aligned duration as this recording.');
    if (![1,2].includes(master.numberOfChannels) || ![1,master.numberOfChannels].includes(vocal.numberOfChannels))
      throw Error('Use a mono or stereo vocal compatible with the original recording.');
    if (master.length > maxFrames) throw Error('Use the desktop stem mixer for recordings longer than five minutes.');
    // Check positive zero-lag correlation across the material. This is a basic
    // mismatch check; an aligned vocal derived from this exact mix is required.
    let mv = 0, vv = 0, mm = 0;
    for (let c = 0; c < master.numberOfChannels; c++) {
      const mix = master.getChannelData(c), source = vocal.getChannelData(Math.min(c, vocal.numberOfChannels - 1));
      const step = Math.max(1, Math.floor(mix.length / 160000));
      for (let i = 0; i < mix.length; i += step) {
        if (Math.abs(source[i]) < .003) continue;
        mv += mix[i] * source[i]; vv += source[i] ** 2; mm += mix[i] ** 2;
      }
    }
    if (!vv || !mm || mv / Math.sqrt(vv * mm) < .25)
      throw Error('The vocal did not match the original mix. Use a sample-aligned isolated vocal from this recording.');
  }
  async function prepare(original, supplied, duration, signal) {
    if (!original || !Number.isFinite(duration) || duration <= 0 || duration > 300 || original.size > maxFile || supplied.size > maxFile)
      throw Error('The browser stem mixer supports local tracks up to five minutes and files up to 64 MiB.');
    const stemDuration = await metadata(supplied);
    if (!Number.isFinite(stemDuration) || Math.abs(stemDuration-duration) > .02)
      throw Error('The vocal stem duration does not match this recording.');
    const Offline = globalThis.OfflineAudioContext || globalThis.webkitOfflineAudioContext;
    if (!Offline) throw Error('Audio decoding is unavailable here. Use the desktop stem mixer.');
    const ctx = new Offline(1, 1, rate);
    const decode = async (file) => {
      if (signal.aborted) throw Error('Cancelled.');
      return ctx.decodeAudioData(await file.arrayBuffer());
    };
    const master = await decode(original), vocal = await decode(supplied);
    if (signal.aborted) throw Error('Cancelled.');
    checkPair(master, vocal);
    return {master,vocal};
  }

  async function render({master,vocal}, level, signal) {
    if (![0,.25,.5,.75,1].includes(level)) throw Error('Unknown vocal level.');
    const channels = master.numberOfChannels;
    const bytes = master.length * channels * 2, header = new DataView(new ArrayBuffer(44));
    function tag(offset, text) { for (let i=0; i<text.length; i++) header.setUint8(offset+i, text.charCodeAt(i)); }
    tag(0,'RIFF'); header.setUint32(4, bytes+36, true); tag(8,'WAVE'); tag(12,'fmt ');
    header.setUint32(16,16,true); header.setUint16(20,1,true); header.setUint16(22,channels,true);
    header.setUint32(24,master.sampleRate,true); header.setUint32(28,master.sampleRate*channels*2,true);
    header.setUint16(32,channels*2,true); header.setUint16(34,16,true); tag(36,'data'); header.setUint32(40,bytes,true);
    const original = [], stems = [], pieces = [header.buffer];
    for (let c=0; c<channels; c++) {
      original.push(master.getChannelData(c)); stems.push(vocal.getChannelData(Math.min(c,vocal.numberOfChannels-1)));
    }
    for (let start=0; start<master.length; start+=131072) {
      if (signal.aborted) throw Error('Cancelled.');
      const stop = Math.min(start+131072,master.length);
      const out = new DataView(new ArrayBuffer((stop-start)*channels*2));
      for (let i=start; i<stop; i++) for (let c=0; c<channels; c++) {
        const sample = Math.max(-1, Math.min(1, original[c][i] - (1-level)*stems[c][i]));
        out.setInt16(((i-start)*channels+c)*2, Math.round(sample*(sample<0?32768:32767)), true);
      }
      pieces.push(out.buffer); await new Promise(resolve => setTimeout(resolve, 0));
    }
    return new Blob(pieces, {type:'audio/wav'});
  }
  window.MarianaKaraokeMix = Object.freeze({prepare, render, checkPair});
})();

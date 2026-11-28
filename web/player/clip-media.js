/* Browser clip processing. Local PCM WAVE files can be cut without decoding the entire track. */
(() => {
  'use strict';
  const MAX_FILE = 32 * 1024 * 1024;
  const MAX_INPUT = 96 * 1024 * 1024;
  const DECODE_SECONDS = 30 * 60;

  function seconds(value) {
    if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return value;
    const parts = String(value).trim().split(':');
    if (!parts.length || parts.length > 3 || !parts.every((p, i) =>
      (i === parts.length - 1 ? /^\d+(?:\.\d+)?$/ : /^\d+$/).test(p) && (i === 0 || Number(p) < 60)))
      throw Error('Enter seconds or a time such as 1:23.450.');
    const result = parts.reduce((n, p) => n * 60 + Number(p), 0);
    if (!Number.isFinite(result)) throw Error('That time is too large.');
    return result;
  }

  function range(start, end, duration) {
    const from = seconds(start), to = seconds(end);
    if (!Number.isFinite(duration) || duration <= 0) throw Error('Load a finite recording to select a clip.');
    if (to <= from || to > duration + .001) throw Error('Choose an end after the start and within this recording.');
    return {from, to:Math.min(to, duration)};
  }

  function checkSignal(signal) {
    if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError');
  }

  const fourCC = (view, index) => String.fromCharCode(...new Uint8Array(view.buffer, view.byteOffset + index, 4));
  const put = (view, index, value) => [...value].forEach((char, i) => view.setUint8(index + i, char.charCodeAt(0)));

  function header(channels, rate, bits, size) {
    const view = new DataView(new ArrayBuffer(44));
    put(view, 0, 'RIFF'); view.setUint32(4, 36 + size + size % 2, true); put(view, 8, 'WAVE');
    put(view, 12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
    view.setUint16(22, channels, true); view.setUint32(24, rate, true);
    view.setUint32(28, rate * channels * bits / 8, true); view.setUint16(32, channels * bits / 8, true);
    view.setUint16(34, bits, true); put(view, 36, 'data'); view.setUint32(40, size, true);
    return view.buffer;
  }

  function frameRange(from, to, rate, length, bytesPerFrame) {
    const start = Math.round(from * rate), end = Math.min(length, Math.round(to * rate));
    if (start >= end || Math.round(to * rate) > length + Math.max(1, Math.round(.05 * rate)))
      throw Error('The decoded audio is shorter than this selection. Move the end earlier.');
    if (44 + (end - start) * bytesPerFrame > MAX_FILE) throw Error('Choose a shorter selection. Clip files can be up to 32 MiB.');
    return {start, end};
  }

  async function cutWave(blob, from, to, signal) {
    const prefix = new DataView(await blob.slice(0, 12).arrayBuffer());
    if (prefix.byteLength < 12 || fourCC(prefix, 0) !== 'RIFF' || fourCC(prefix, 8) !== 'WAVE') return null;
    let fmt;
    for (let pos = 12, count = 0; pos + 8 <= blob.size && count < 256; count++) {
      checkSignal(signal);
      const v = new DataView(await blob.slice(pos, pos + 48).arrayBuffer());
      const name = fourCC(v, 0), size = v.getUint32(4, true), data = pos + 8;
      if (data + size > blob.size) return null;
      // WAVE_FORMAT_EXTENSIBLE can represent integer PCM using its subtype GUID.
      const subtype = [1,0,0,0,0,0,16,0,128,0,0,170,0,56,155,113];
      const pcm = name === 'fmt ' && size >= 16 && (v.getUint16(8, true) === 1 ||
        (size >= 40 && v.getUint16(8, true) === 65534 && v.getUint16(24, true) >= 22 &&
        v.getUint16(26, true) === v.getUint16(22, true) && subtype.every((b, i) => v.getUint8(32 + i) === b)));
      if (pcm) {
        const channels = v.getUint16(10, true), rate = v.getUint32(12, true), bits = v.getUint16(22, true);
        if ([1, 2].includes(channels) && [8, 16, 24, 32].includes(bits) && rate && rate <= 384000 &&
            v.getUint16(20, true) === channels * bits / 8) fmt = {channels, rate, bits};
      }
      if (name === 'data' && fmt) {
        const {channels, rate, bits} = fmt, stride = channels * bits / 8;
        const {start, end} = frameRange(from, to, rate, Math.floor(size / stride), stride);
        const bytes = (end - start) * stride;
        const slices = [header(channels, rate, bits, bytes), blob.slice(data + start * stride, data + end * stride)];
        if (bytes % 2) slices.push(new Uint8Array(1));
        return new Blob(slices, {type:'audio/wav'});
      }
      pos = data + size + size % 2;
    }
    return null;
  }

  function cutBuffer(buffer, from, to) {
    const channels = buffer.numberOfChannels, rate = buffer.sampleRate;
    if (channels > 2) throw Error('For multichannel surround audio, export the clip from the desktop player.');
    const {start, end} = frameRange(from, to, rate, buffer.length, channels * 2);
    const pcm = new DataView(new ArrayBuffer((end - start) * channels * 2));
    for (let c = 0; c < channels; c++) {
      const data = buffer.getChannelData(c);
      for (let i = start; i < end; i++) {
        const sample = Math.max(-1, Math.min(1, data[i]));
        pcm.setInt16(((i - start) * channels + c) * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
      }
    }
    return new Blob([header(channels, rate, 16, pcm.byteLength), pcm.buffer], {type:'audio/wav'});
  }

  async function decode(blob) {
    const Offline = globalThis.OfflineAudioContext || globalThis.webkitOfflineAudioContext;
    if (!Offline) throw Error('This browser cannot decode this format for clipping. Use a PCM WAV or the desktop player.');
    try { return await new Offline(1, 1, 48000).decodeAudioData(await blob.arrayBuffer()); }
    catch { throw Error('The browser could not decode this recording. Try a local PCM WAV or export with the desktop player.'); }
  }

  async function retrieve(url, signal) {
    let response;
    try { response = await fetch(url, {signal, credentials:'omit', referrerPolicy:'no-referrer'}); }
    catch (error) {
      if (signal.aborted) throw error;
      throw Error('The media host could not be read. Import the recording as a local file if you have it.');
    }
    if (!response.ok) throw Error('The media host returned HTTP ' + response.status + '. Import a local copy to clip it.');
    if (!response.body || Number(response.headers.get('Content-Length')) > MAX_INPUT)
      throw Error('Import the recording as a local file to clip this source.');
    const reader = response.body.getReader(), parts = [];
    let size = 0;
    try {
      for (;;) {
        const {value, done} = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_INPUT) throw Error('The remote file exceeds 96 MiB. Import it locally or use the desktop player.');
        parts.push(value);
      }
    } finally { try { await reader.cancel(); } catch { /* Already closed. */ } }
    return new Blob(parts, {type:response.headers.get('Content-Type') || ''});
  }

  async function render(blob, from, to, duration, signal) {
    const r = range(from, to, duration);
    if (!blob) throw Error('The source file is unavailable. Add it to the library again.');
    const sliced = await cutWave(blob, r.from, r.to, signal);
    checkSignal(signal);
    if (sliced) return sliced;
    if (blob.size > MAX_INPUT || duration > DECODE_SECONDS)
      throw Error('Use a PCM WAV or the desktop player for this recording. Browser decoding supports up to 96 MiB and 30 minutes.');
    const audio = await decode(blob);
    checkSignal(signal);
    return cutBuffer(audio, r.from, r.to);
  }
  function youtubeLink(value, position) {
    if (!value) return '';
    try {
      const u = new URL(value);
      if (u.protocol !== 'https:' || u.port || u.username || u.password) return '';
      let id = '';
      if (u.hostname === 'youtu.be') id = u.pathname.slice(1);
      if (['www.youtube.com','youtube.com','m.youtube.com','music.youtube.com'].includes(u.hostname))
        id = u.pathname === '/watch' ? u.searchParams.get('v') : /^\/(?:shorts|embed)\/([a-zA-Z0-9_-]{11})\/?$/.exec(u.pathname)?.[1];
      if (!id || !/^[a-zA-Z0-9_-]{11}$/.test(id)) return '';
      const time = Math.floor(seconds(position));
      return 'https://www.youtube.com/watch?v=' + id + (time > 0 ? '&t=' + time + 's' : '');
    } catch { return ''; }
  }
  globalThis.MarianaClipMedia = {seconds, range, youtubeLink, cutWave, cutBuffer, retrieve, render, decode, maxFile:MAX_FILE};
})();

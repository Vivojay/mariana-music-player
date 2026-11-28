/* Local portrait video with a themed title card and the selected recording. */
(() => {
  'use strict';
  function codec() {
    if (!globalThis.MediaRecorder?.isTypeSupported || !globalThis.HTMLCanvasElement?.prototype.captureStream ||
        !(globalThis.AudioContext || globalThis.webkitAudioContext)) return '';
    return ['video/mp4;codecs=avc1.42E01E,mp4a.40.2', 'video/mp4', 'video/webm;codecs=vp9,opus',
      'video/webm;codecs=vp8,opus'].find(type => MediaRecorder.isTypeSupported(type)) || '';
  }
  function titleLines(ctx, title, maxWidth) {
    const chars = [...title], lines = [];
    let line = '';
    for (let i = 0; i < chars.length; i++) {
      if (ctx.measureText(line + chars[i]).width <= maxWidth) { line += chars[i]; continue; }
      const split = line.lastIndexOf(' ');
      lines.push(split > 0 ? line.slice(0, split) : line);
      line = (split > 0 ? line.slice(split + 1) : '') + chars[i];
      if (lines.length === 2) {
        let last = line + chars.slice(i + 1).join('');
        if (ctx.measureText(last).width > maxWidth) {
          while (last.length && ctx.measureText(last + '…').width > maxWidth) last = last.slice(0, -1);
          last += '…';
        }
        return [...lines, last];
      }
    }
    return [...lines, line].filter(Boolean);
  }

  function paint(canvas, audio, title, colors, progress) {
    const c = canvas.getContext('2d'), w = canvas.width, h = canvas.height;
    const {background, panel, text, muted, accent} = colors;
    const gradient = c.createLinearGradient(0, 0, w, h);
    gradient.addColorStop(0, panel); gradient.addColorStop(.65, background);
    c.fillStyle = gradient; c.fillRect(0, 0, w, h);
    const cx = w * .65, cy = h * .32, radius = w * .54;
    c.strokeStyle = accent;
    for (let i = 0; i < 20; i++) {
      c.globalAlpha = i % 5 === 0 ? .4 : .12;
      c.lineWidth = i % 5 === 0 ? 5 : 2;
      c.beginPath(); c.arc(cx, cy, radius * (i + 1) / 20, 0, Math.PI * 2); c.stroke();
    }
    c.globalAlpha = 1;
    c.fillStyle = accent; c.beginPath(); c.arc(cx, cy, 38, 0, Math.PI * 2); c.fill();
    c.fillStyle = background; c.beginPath(); c.arc(cx, cy, 7, 0, Math.PI * 2); c.fill();
    c.fillStyle = text; c.font = 'bold 54px system-ui, sans-serif';
    titleLines(c, title, w - 104).forEach((line, i) => c.fillText(line, 52, h * .67 + i * 62));
    const samples = audio.getChannelData(0), bars = 80, step = (w - 104) / bars;
    for (let i = 0; i < bars; i++) {
      let peak = 0;
      for (let j = 0; j < 40; j++) peak = Math.max(peak, Math.abs(samples[Math.min(samples.length - 1, Math.floor((i + j/40) * samples.length / bars))]));
      c.fillStyle = i / bars <= progress ? accent : muted;
      const height = 4 + Math.min(1, peak) * 54;
      c.fillRect(52 + i * step, h * .88 - height/2, Math.max(2, step - 3), height);
    }
    c.fillStyle = muted; c.font = '25px system-ui, sans-serif'; c.fillText('Mariana', 52, h - 50);
  }

  async function record(wav, title, colors, context, signal) {
    const type = codec();
    if (!type) throw Error('This browser cannot record a portrait video. Choose Audio clip.');
    const audio = await context.decodeAudioData(await wav.arrayBuffer());
    if (audio.duration > 90.001) throw Error('Choose up to 90 seconds for a portrait video.');
    if (signal.aborted) throw new DOMException('Cancelled', 'AbortError');
    const canvas = document.createElement('canvas');
    canvas.width = 720; canvas.height = 1280;
    paint(canvas, audio, title, colors, 0);
    const stream = canvas.captureStream(12), destination = context.createMediaStreamDestination();
    for (const track of destination.stream.getAudioTracks()) stream.addTrack(track);
    const source = context.createBufferSource(); source.buffer = audio; source.connect(destination);
    let recorder, frame, deadline, onAbort;
    try {
      recorder = new MediaRecorder(stream, {mimeType:type, videoBitsPerSecond:1600000, audioBitsPerSecond:128000});
      const chunks = [];
      return await new Promise((resolve, reject) => {
        let size = 0;
        const fail = message => reject(Error(message));
        recorder.ondataavailable = event => {
          size += event.data.size;
          if (size > globalThis.MarianaClipMedia.maxFile) fail('This video exceeded 32 MiB. Choose a shorter selection.');
          else if (event.data.size) chunks.push(event.data);
        };
        recorder.onerror = () => fail('Video recording failed. Try Audio clip.');
        recorder.onstop = () => {
          const mediaType = recorder.mimeType.startsWith('video/mp4') ? 'video/mp4' : 'video/webm';
          if (!chunks.length) fail('The recorder produced an empty clip.');
          else resolve(new Blob(chunks, {type:mediaType}));
        };
        onAbort = () => reject(new DOMException('Cancelled', 'AbortError'));
        signal.addEventListener('abort', onAbort, {once:true});
        recorder.start(500);
        const start = context.currentTime;
        frame = setInterval(() => paint(canvas, audio, title, colors, Math.min(1, (context.currentTime - start)/audio.duration)), 100);
        source.onended = () => { if (recorder.state !== 'inactive') recorder.stop(); };
        source.start();
        deadline = setTimeout(() => fail('Recording was interrupted. Keep the player in the foreground, or choose Audio clip.'), (audio.duration + 8) * 1000);
      });
    } finally {
      clearInterval(frame); clearTimeout(deadline);
      if (onAbort) signal.removeEventListener('abort', onAbort);
      source.onended = null; try { source.stop(); } catch { /* Already ended. */ }
      if (recorder && recorder.state !== 'inactive') recorder.stop();
      for (const track of stream.getTracks()) track.stop();
      source.disconnect(); destination.disconnect();
    }
  }
  function eventUntil(element, eventName, signal) {
    return new Promise((resolve, reject) => {
      function done(error) {
        element.removeEventListener(eventName, ok); element.removeEventListener('error', bad);
        signal.removeEventListener('abort', abort);
        if (error) reject(error); else resolve();
      }
      const ok = () => done(), bad = () => done(Error('This browser could not read the original video.'));
      const abort = () => done(new DOMException('Cancelled', 'AbortError'));
      if (signal.aborted) { abort(); return; }
      element.addEventListener(eventName, ok, {once:true}); element.addEventListener('error', bad, {once:true});
      signal.addEventListener('abort', abort, {once:true});
    });
  }

  async function original(blob, from, to, context, signal) {
    const type = codec();
    if (!type || to - from > 90.001) throw Error('Choose up to 90 seconds and a browser with video encoding.');
    const video = document.createElement('video'), url = URL.createObjectURL(blob);
    video.playsInline = true; video.preload = 'auto';
    // The offscreen decoder has its own transport and never changes the main player's position.
    let stream, recorder, source, output, frameTimer, frameID, onAbort, onError;
    try {
      const loaded = eventUntil(video, 'loadeddata', signal);
      video.src = url; video.load();
      await loaded;
      if (!video.videoWidth || !video.videoHeight) throw Error('This recording has no readable video track. Choose Audio clip or Portrait video.');
      if (!Number.isFinite(video.duration) || to > video.duration + .05) throw Error('The selected end is outside the source video.');
      if (from > 0) {
        const seeked = eventUntil(video, 'seeked', signal);
        video.currentTime = from; await seeked;
      }
      const canvas = document.createElement('canvas'), scale = Math.min(1, 1280 / Math.max(video.videoWidth,video.videoHeight));
      canvas.width = Math.max(2, Math.round(video.videoWidth * scale / 2) * 2);
      canvas.height = Math.max(2, Math.round(video.videoHeight * scale / 2) * 2);
      const paintFrame = () => canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
      paintFrame(); stream = canvas.captureStream(30);
      source = context.createMediaElementSource(video); output = context.createMediaStreamDestination(); source.connect(output);
      for (const track of output.stream.getAudioTracks()) stream.addTrack(track);
      recorder = new MediaRecorder(stream, {mimeType:type, videoBitsPerSecond:2100000, audioBitsPerSecond:128000});
      const chunks = [];
      return await new Promise((resolve, reject) => {
        let size = 0;
        const stop = () => { video.pause(); if (recorder.state !== 'inactive') recorder.stop(); };
        const next = (_now, metadata) => {
          if (recorder.state === 'inactive') return;
          if (metadata.mediaTime >= to) { stop(); return; }
          paintFrame(); frameID = video.requestVideoFrameCallback(next);
        };
        onAbort = () => reject(new DOMException('Cancelled', 'AbortError'));
        signal.addEventListener('abort', onAbort, {once:true});
        onError = () => reject(Error('Original video playback was interrupted. Try a local file or desktop export.'));
        video.addEventListener('error', onError); video.onended = stop;
        recorder.onerror = () => reject(Error('Original video recording failed in this browser.'));
        recorder.ondataavailable = e => {
          size += e.data.size;
          if (size > globalThis.MarianaClipMedia.maxFile) reject(Error('The clip exceeded 32 MiB. Choose a shorter range.'));
          else if (e.data.size) chunks.push(e.data);
        };
        recorder.onstop = () => chunks.length ? resolve(new Blob(chunks, {
          type:recorder.mimeType.startsWith('video/mp4') ? 'video/mp4' : 'video/webm',
        })) : reject(Error('No video was recorded.'));
        recorder.start(500);
        if (video.requestVideoFrameCallback) frameID = video.requestVideoFrameCallback(next);
        frameTimer = setInterval(() => {
          if (video.currentTime >= to) stop(); else if (!video.requestVideoFrameCallback) paintFrame();
        }, 25);
        video.play().catch(() => reject(Error('Tap Prepare clip again to allow the original video to play.')));
      });
    } finally {
      clearInterval(frameTimer); if (frameID != null) video.cancelVideoFrameCallback(frameID);
      if (onAbort) signal.removeEventListener('abort', onAbort);
      if (onError) video.removeEventListener('error', onError);
      if (recorder && recorder.state !== 'inactive') recorder.stop();
      video.onended = null; video.pause(); video.removeAttribute('src'); video.load();
      if (stream) for (const track of stream.getTracks()) track.stop();
      source?.disconnect(); output?.disconnect(); URL.revokeObjectURL(url);
    }
  }
  globalThis.MarianaClipStory = {codec, paint, record, original};
})();

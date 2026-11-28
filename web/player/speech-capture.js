'use strict';
(() => {
  const formats = {'audio/webm':'webm', 'audio/mp4':'m4a', 'audio/ogg':'ogg', 'audio/wav':'wav'};
  const help = 'speech record · speech jam (shared-tab audio + mic) · speech start (enable browser captions first) · speech status · speech text · speech speaker NAME · speech stop · speech export audio|vtt|txt · speech share audio|vtt|txt';
  const timestamp = ms => {
    const value = Math.max(0, Math.round(ms)), pad = n => String(n).padStart(2, '0');
    return pad(Math.floor(value / 3600000)) + ':' + pad(Math.floor(value / 60000) % 60) + ':' +
      pad(Math.floor(value / 1000) % 60) + '.' + String(value % 1000).padStart(3, '0');
  };
  const clean = text => String(text || '').replace(/\s+/g, ' ').trim();
  const escape = text => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  function transcript(cues, format) {
    if (format === 'txt') return cues.map(c => c.who + ': ' + c.text).join('\n') + '\n';
    return 'WEBVTT\n\n' + cues.map(c => timestamp(c.start) + ' --> ' + timestamp(c.end) + '\n<v ' +
      escape(c.who) + '>' + escape(c.text) + '</v>').join('\n\n') + '\n';
  }

  function mount(el, env = globalThis) {
    const node = key => el('mic-' + key), Recognition = env.SpeechRecognition || env.webkitSpeechRecognition;
    const canRecord = !!(env.navigator.mediaDevices?.getUserMedia && env.MediaRecorder);
    const AudioContext = env.AudioContext || env.webkitAudioContext;
    const tabCapture = !!(canRecord && AudioContext && env.navigator.mediaDevices.getDisplayMedia && !env.MarianaNativeShell);
    let take, last, recordingURL, phase = 'idle', message = 'Microphone off.';
    const describe = () => take?.error || message;
    function paint() {
      node('status').textContent = describe();
      node('record').disabled = !canRecord || phase !== 'idle';
      node('jam').disabled = !tabCapture || !node('participants').checked || phase !== 'idle';
      node('participants').disabled = !tabCapture || phase !== 'idle';
      node('start').disabled = !canRecord || !Recognition || !node('consent').checked || phase !== 'idle';
      node('stop').disabled = phase === 'idle' || phase === 'stopping';
      node('consent').disabled = !Recognition || phase !== 'idle';
      node('lang').disabled = !Recognition || phase !== 'idle';
      node('text').textContent = (take || last)?.cues.slice(-12).map(c => c.who + ': ' + c.text).join('\n') || '';
      node('partial').textContent = take?.partial || '';
      node('result').hidden = !last || phase !== 'idle';
      const format = node('format').value || 'audio';
      const ready = !!last?.files[format];
      node('save').disabled = !ready;
      node('share').disabled = !ready || !env.MarianaClipShare?.available(last.files[format]);
    }

    function release(stream) {
      for (const track of stream?.getTracks() || []) track.stop();
    }
    function releaseInputs(session) {
      for (const stream of session.streams.splice(0)) release(stream);
      for (const node of session.nodes.splice(0)) node.disconnect();
      if (session.context) {
        session.context.close().catch(() => {});
        session.context = null;
      }
    }
    function ownStream(session, stream) {
      if (take !== session) {
        release(stream);
        throw Error('Capture request cancelled.');
      }
      session.streams.push(stream);
      for (const track of stream.getTracks()) track.addEventListener('ended', () => {
        if (take === session && phase !== 'stopping') {
          session.error = 'An input ended. Recording stopped.';
          stop();
        }
      });
      return stream;
    }
    async function jamInput(session) {
      const context = new AudioContext();
      session.context = context;
      // Both permission-sensitive calls start in the same user gesture.
      const resumed = context.resume().then(() => null, error => error);
      const shared = ownStream(session, await env.navigator.mediaDevices.getDisplayMedia({
        video:{displaySurface:'browser'}, audio:true, systemAudio:'exclude', surfaceSwitching:'exclude'
      }));
      const screen = shared.getVideoTracks()[0];
      if (screen?.getSettings().displaySurface !== 'browser')
        throw Error('Select a browser tab. This mode requires a browser that identifies the selected tab.');
      screen.enabled = false;
      if (!shared.getAudioTracks().length)
        throw Error('The selected tab supplied no audio. Select the jam tab and enable Share tab audio.');
      const mic = ownStream(session, await env.navigator.mediaDevices.getUserMedia({audio:true,video:false}));
      const resumeError = await resumed;
      if (resumeError) throw resumeError;
      if (take !== session) throw Error('Capture request cancelled.');
      const bus = context.createMediaStreamDestination();
      session.nodes.push(bus);
      for (const stream of [shared, mic]) {
        const source = context.createMediaStreamSource(stream), gain = context.createGain();
        gain.gain.value = 0.5;
        source.connect(gain);
        gain.connect(bus);
        session.nodes.push(source, gain);
      }
      // Only the stereo audio destination reaches the encoder. No monitor output.
      return ownStream(session, bus.stream);
    }
    function finish(session) {
      if (take !== session || !session.audioDone || !session.captionsDone) return;
      releaseInputs(session);
      if (recordingURL) env.URL.revokeObjectURL(recordingURL);
      recordingURL = null;
      const type = (session.recorder.mimeType || session.chunks[0]?.type || '').split(';')[0];
      session.files = {};
      if (session.bytes && formats[type]) {
        session.files.audio = new env.File(session.chunks, session.name + '.' + formats[type], {type});
        recordingURL = env.URL.createObjectURL(session.files.audio);
        node('preview').src = recordingURL;
        node('preview').hidden = false;
      } else {
        node('preview').removeAttribute('src');
        node('preview').hidden = true;
        if (!session.error) session.error = session.bytes ? 'The recorder produced an unsupported audio format.' : 'No microphone audio was recorded.';
      }
      for (const format of ['txt', 'vtt']) {
        if (session.cues.length) session.files[format] = new env.File([transcript(session.cues,format)],
          session.name + '.' + format, {type:format === 'vtt' ? 'text/vtt' : 'text/plain'});
      }
      session.chunks = [];
      session.recorder = null;
      session.recognition = null;
      session.finalized.clear();
      message = (session.error ? session.error + ' ' : '') + 'Microphone off. ' +
        (session.files.audio ? 'Save this take before starting another or closing the player.' : 'Start a new take to try again.');
      last = session;
      take = null;
      phase = 'idle';
      paint();
    }

    function stop() {
      const session = take;
      if (!session || phase === 'stopping') return describe();
      if (!session.recorder) {
        releaseInputs(session);
        take = null;
        phase = 'idle';
        message = session.error || 'Microphone request cancelled.';
        paint();
        return message;
      }
      if (session.end == null) session.end = env.performance.now();
      phase = 'stopping';
      message = 'Finishing recording…';
      if (session.recorder.state !== 'inactive') session.recorder.stop();
      releaseInputs(session);
      if (session.recognition && !session.captionsDone) {
        try { session.recognition.stop(); } catch { /* The recognizer may already be stopping. */ }
        // Some browsers omit the end event when a service disconnects.
        if (!session.captionsDone) session.timer = env.setTimeout(() => {
          if (take !== session || session.captionsDone) return;
          session.captionsDone = true;
          try { session.recognition.abort(); } catch { /* Already stopped. */ }
          session.partial = '';
          finish(session);
        }, 1800);
      }
      finish(session);
      paint();
      return describe();
    }

    function startCaptions(session) {
      const engine = new Recognition();
      session.recognition = engine;
      session.captionsDone = false;
      engine.continuous = true;
      engine.interimResults = true;
      engine.lang = node('lang').value.trim() || env.navigator.language || 'en';
      const elapsed = () => Math.max(0, (session.end ?? env.performance.now()) - session.origin);
      engine.onspeechstart = () => {
        session.utteranceStart = elapsed();
        session.speaker = clean(node('speaker').value) || 'Speaker';
      };
      engine.onresult = event => {
        if (take !== session || session.captionsDone) return;
        const partial = [];
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i], text = clean(result[0]?.transcript);
          if (!text) continue;
          if (!result.isFinal) { partial.push(text); continue; }
          if (session.finalized.has(i)) continue;
          session.finalized.add(i);
          const end = Math.max(1, elapsed());
          const start = Math.min(end - 1, Math.max(session.cues[session.cues.length - 1]?.end || 0, session.utteranceStart || 0));
          session.cues.push({start, end, text, who:session.speaker || clean(node('speaker').value) || 'Speaker'});
          session.utteranceStart = end;
        }
        session.partial = partial.join(' ');
        paint();
      };
      engine.onerror = event => {
        if (take !== session || session.captionsDone) return;
        session.error = 'Browser captions interrupted (' + (event.error || 'recognition error') + '). Microphone recording is independent.';
        paint();
      };
      engine.onend = () => {
        if (take !== session) return;
        session.captionsDone = true;
        env.clearTimeout(session.timer);
        session.partial = '';
        if (phase === 'recording') message = 'Captions ended. Microphone recording continues until Stop.';
        finish(session);
        paint();
      };
      engine.start();
    }

    async function start(captions, jam = false) {
      if (!canRecord) return 'This surface has no microphone recorder. Use localhost or HTTPS in a browser with MediaRecorder.';
      if (phase !== 'idle') return 'A microphone request or recording is already active.';
      if (jam && !tabCapture) return 'This surface cannot capture a shared browser tab with microphone audio.';
      if (jam && !node('participants').checked) return 'Confirm participant permission in Microphone studio first.';
      if (captions && (!Recognition || !node('consent').checked))
        return 'To record with captions, review browser speech processing and enable the checkbox in Microphone studio.';
      const session = {name:(jam ? 'Mariana-jam-' : 'Mariana-speech-') + new Date().toISOString().replace(/[:.]/g,'-'), chunks:[], bytes:0,
        cues:[], partial:'', finalized:new Set(), captionsDone:true, streams:[], nodes:[]};
      take = session;
      phase = 'requesting';
      if (jam) node('participants').checked = false;
      message = jam ? 'Select the jam tab and enable Share tab audio, then allow your microphone.' : 'Waiting for microphone permission…';
      node('preview').pause?.();
      paint();
      try {
        const stream = jam ? await jamInput(session) :
          ownStream(session, await env.navigator.mediaDevices.getUserMedia({audio:true, video:false}));
        if (take !== session) throw Error('Capture request cancelled.');
        const mimeType = ['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus','audio/webm'].find(
          type => env.MediaRecorder.isTypeSupported?.(type));
        const recorder = new env.MediaRecorder(stream, mimeType ? {mimeType} : undefined);
        session.recorder = recorder;
        recorder.ondataavailable = event => {
          if (event.data.size) { session.chunks.push(event.data); session.bytes += event.data.size; }
          if (phase === 'recording' && session.bytes >= 24 * 1024 * 1024) {
            session.error = 'Recording stopped at the in-memory size limit.';
            stop();
          }
        };
        recorder.onerror = () => { session.error = 'The browser microphone recorder reported an error.'; stop(); };
        recorder.onstop = () => {
          session.audioDone = true;
          if (phase !== 'stopping') stop();
          finish(session);
        };
        recorder.start(1000);
        session.origin = env.performance.now();
        phase = 'recording';
        if (jam) message = 'Recording shared tab audio and microphone in a local stereo mix.';
        else message = captions ? 'Recording microphone with browser captions.' : 'Recording microphone locally.';
        if (captions) {
          node('consent').checked = false;
          try { startCaptions(session); }
          catch (error) { session.captionsDone = true; session.error = 'Captions unavailable. Recording continues. ' + error.message; }
        }
      } catch (error) {
        releaseInputs(session);
        if (take !== session) return 'Microphone request cancelled.';
        take = null;
        phase = 'idle';
        message = 'Microphone unavailable: ' + error.message;
      }
      paint();
      return describe();
    }

    function fileAction(action, format) {
      if (phase !== 'idle') return 'Stop the microphone before exporting.';
      const file = last?.files[format];
      if (!file) return 'No completed ' + format + ' output for this take.';
      if (action === 'share') {
        if (!env.MarianaClipShare?.available(file)) return 'File sharing is unavailable here. Use Save to attach the file.';
        return env.MarianaClipShare.share(file).then(() => 'Share completed.');
      }
      const link = env.document.createElement('a'), href = env.URL.createObjectURL(file);
      link.href = href; link.download = file.name; link.click();
      env.setTimeout(() => env.URL.revokeObjectURL(href), 60_000);
      return 'Download requested: ' + file.name;
    }
    async function command(args) {
      const [action = 'status', ...rest] = args;
      if (action === 'help') return help;
      if (action === 'record') return start(false);
      if (action === 'jam') return start(false,true);
      if (action === 'start') return start(true);
      if (action === 'stop') return stop();
      if (action === 'status') return describe() + (take?.origin != null ?
        ' ' + (((take.end ?? env.performance.now()) - take.origin) / 1000).toFixed(1) + 's.' : '');
      if (action === 'text' || action === 'live') {
        node('title').focus();
        const session = take || last;
        return session ? transcript(session.cues, 'txt').trim() || session.partial || 'No captions.' : 'No captions.';
      }
      if (action === 'speaker' && rest.length) { node('speaker').value = clean(rest.join(' ')).slice(0,80); return 'Speaker label updated.'; }
      if (['export','share'].includes(action)) return fileAction(action, rest[0] || 'audio');
      return help;
    }
    for (const [key, fn] of Object.entries({record:() => start(false), jam:() => start(false,true), start:() => start(true), stop,
      save:() => fileAction('export',node('format').value), share:() => fileAction('share',node('format').value)})) {
      node(key).onclick = async () => {
        try { const result = await fn(); if (['save','share'].includes(key)) node('status').textContent = result; }
        catch (error) { node('status').textContent = error.name === 'AbortError' ? 'Sharing cancelled.' : error.message; }
      };
    }
    node('lang').value = env.navigator.language || 'en';
    node('consent').onchange = node('format').onchange = node('participants').onchange = paint;
    node('jam-note').textContent = tabCapture ?
      'Choose the browser tab carrying the other participants. Enable Share tab audio. The export contains tab audio and your microphone. Headphones reduce echo.' :
      'Shared-tab jam recording requires a desktop browser with tab-audio capture.';
    node('availability').textContent = !canRecord ? 'Microphone recording is unavailable on this surface.' :
      Recognition ? 'Your browser offers speech recognition.' : 'This browser supports recording. Live speech recognition is unavailable.';
    env.addEventListener('mariana-clip-share-ready', paint);
    env.addEventListener('pagehide', stop);
    paint();
    return {command};
  }
  globalThis.MarianaMic = {mount, transcript};
})();

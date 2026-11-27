/* Live control strip for the terminal-owned player. */
(() => {
  'use strict';

  function positionAt(state, elapsedSeconds) {
    if (!Number.isFinite(state.position_seconds)) return 0;
    const rate = Number.isFinite(state.playback_rate) && state.playback_rate > 0 ? state.playback_rate : 1;
    const active = ['playing', 'crossfading'].includes(state.state);
    const elapsed = active ? Math.min(1.35, Math.max(0, elapsedSeconds)) * rate : 0;
    const bound = state.region?.active ? state.region.end_seconds : state.duration_seconds;
    return Math.max(0, Math.min(Number.isFinite(bound) ? bound : Infinity, state.position_seconds + elapsed));
  }

  function mount({byId, send, clock}) {
    const seek = byId('native-progress'), time = byId('native-clock'), name = byId('native-play-pause');
    const like = byId('native-like'), rate = byId('native-rating'), shuffle = byId('native-shuffle');
    const repeat = byId('native-repeat'), availability = byId('native-control-note');
    const volume = byId('native-volume'), mute = byId('native-mute'), speed = byId('native-speed');
    let latest = {}, received = 0, enabled = false, locked = false, working = false;
    let dragOccurrence, target, frame, keyTimer;

    function canSeek() {
      return enabled && latest.occurrence && latest.seekable && !latest.live &&
        ['paused','playing'].includes(latest.state) && Number.isFinite(latest.duration_seconds) && latest.duration_seconds > 0;
    }
    function controls() {
      seek.disabled = !canSeek() || locked || working;
      const playing = ['playing','crossfading'].includes(latest.state);
      name.textContent = playing ? 'Pause' : 'Play';
      name.disabled = enabled && (locked || working || !latest.occurrence || !(playing || latest.state === 'paused'));
      like.disabled = locked || working || !enabled || !latest.occurrence || !latest.favorite?.toggle_enabled;
      rate.disabled = like.disabled;
      shuffle.disabled = locked || working || !enabled;
      repeat.disabled = shuffle.disabled;
      volume.disabled = mute.disabled = shuffle.disabled;
      speed.disabled = !canSeek() || locked || working;
      mute.setAttribute('aria-pressed', String(Boolean(latest.muted)));
      mute.textContent = latest.muted ? 'Unmute' : 'Mute';
      if (document.activeElement !== volume || !Number.isFinite(Number(volume.value)))
        volume.value = String(latest.volume ?? 100);
      const currentSpeed = String(latest.playback_rate || 1);
      if (![...speed.options].some(option => option.value === currentSpeed))
        speed.add(new Option(currentSpeed, currentSpeed));
      speed.value = currentSpeed;
      like.setAttribute('aria-pressed', String(Boolean(latest.favorite?.is_favorite)));
      like.textContent = latest.favorite?.is_favorite ? '♥ Liked' : '♡ Like';
      rate.value = String(latest.favorite?.rating || 0);
      shuffle.setAttribute('aria-pressed', String(latest.queue_order === 'shuffle'));
      repeat.value = latest.queue_repeat || 'off';
    }
    function draw() {
      if (!enabled && !latest.duration_seconds) return;
      const value = target ?? positionAt(latest, (performance.now()-received)/1000);
      if (canSeek() && (dragOccurrence === undefined || target !== undefined)) seek.value = String(value);
      const start = enabled && latest.live ? 'Live · ' : '';
      const playtime = clock(value);
      const label = start + playtime + (Number.isFinite(latest.duration_seconds) ? ' / ' + clock(latest.duration_seconds) : '');
      if (time.textContent !== label) time.textContent = label;
      if (seek.getAttribute('aria-valuetext') !== playtime) seek.setAttribute('aria-valuetext', playtime);
    }
    function animate() { draw(); if (enabled) frame = requestAnimationFrame(animate); }
    function abortDrag() {
      dragOccurrence = undefined; target = undefined; clearTimeout(keyTimer);
    }
    function update(state) {
      if (latest.occurrence !== state.occurrence) abortDrag();
      latest = state;
      received = performance.now();
      seek.max = String(Number.isFinite(state.duration_seconds) ? state.duration_seconds : 0);
      controls(); draw();
    }

    async function action(type, value, occurrence = latest.occurrence) {
      if (!enabled || locked || working) return false;
      const fields = ['shuffle','repeat','volume','mute'].includes(type) ? {} : {occurrence};
      working = true;
      availability.textContent = '';
      controls();
      try { await send({action:type, value, ...fields}); return true; }
      catch (error) { availability.textContent = error.message; return false; }
      finally { working = false; controls(); }
    }

    async function commit() {
      clearTimeout(keyTimer);
      if (target === undefined || dragOccurrence !== latest.occurrence) { abortDrag(); draw(); return; }
      const value = target, occurrence = dragOccurrence;
      dragOccurrence = undefined;
      await action('seek', value, occurrence);
      target = undefined;
      draw();
    }

    seek.addEventListener('pointerdown', () => { if (canSeek()) dragOccurrence = latest.occurrence; });
    seek.addEventListener('input', () => {
      if (!canSeek()) return;
      if (dragOccurrence === undefined) dragOccurrence = latest.occurrence;
      target = Number(seek.value);
      draw();
    });
    seek.addEventListener('pointercancel', () => { abortDrag(); draw(); });
    seek.addEventListener('change', () => {
      if (target === undefined && canSeek()) {
        dragOccurrence = latest.occurrence;
        target = Number(seek.value);
      }
      clearTimeout(keyTimer);
      keyTimer = setTimeout(() => void commit(), 110);
    });
    like.onclick = () => void action('favorite');
    rate.onchange = () => void action('rating', Number(rate.value));
    shuffle.onclick = () => void action('shuffle', latest.queue_order !== 'shuffle');
    repeat.onchange = () => void action('repeat', repeat.value);
    volume.onchange = () => void action('volume', Number(volume.value));
    mute.onclick = () => void action('mute', !latest.muted);
    speed.onchange = () => void action('speed', Number(speed.value));
    return {
      update,
      setEnabled(value) {
        enabled = value;
        byId('native-player').dataset.fullControls = String(value);
        cancelAnimationFrame(frame);
        if (value) frame = requestAnimationFrame(animate);
        else abortDrag();
        controls(); draw();
      },
      setBusy(value) { locked = value; controls(); },
      transport(which) {
        if (!enabled) return false;
        if (which === 'p') void action(['playing','crossfading'].includes(latest.state) ? 'pause' : 'play');
        else if (which === '.prev' || which === '.next') void action(which === '.prev' ? 'previous' : 'next');
        else if (canSeek()) {
          const delta = which === 'seek +10s' ? 10 : -10;
          void action('seek', Math.min(latest.duration_seconds, Math.max(0, positionAt(latest, 0) + delta)));
        }
        return true;
      },
    };
  }

  globalThis.MarianaPairedFlow = {mount, positionAt};
})();

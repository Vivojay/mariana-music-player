'use strict';
(() => {
  const schema = 'mariana.duet-invite.v1', hex = /^[0-9a-f]{64}$/;
  const fields = ['schema','media_sha256','timing_sha256','duration_ms','part','start_ms'];
  function validate(invite) {
    const valid = invite && typeof invite === 'object' && Object.keys(invite).length === fields.length &&
      fields.every(f => Object.prototype.hasOwnProperty.call(invite,f)) && invite.schema === schema &&
      typeof invite.media_sha256 === 'string' && hex.test(invite.media_sha256) &&
      typeof invite.timing_sha256 === 'string' && hex.test(invite.timing_sha256) &&
      Number.isSafeInteger(invite.duration_ms) && invite.duration_ms > 0 && invite.duration_ms <= 86400000 &&
      Number.isSafeInteger(invite.start_ms) && invite.start_ms >= 0 && invite.start_ms < invite.duration_ms &&
      (invite.part === null || (typeof invite.part === 'string' && Boolean(invite.part.trim()) &&
        invite.part.trim() === invite.part && [...invite.part].length <= 80 && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(invite.part)));
    if (!valid) throw Error('Choose a valid Mariana duet invite.');
    return invite;
  }
  function timing(sheet) {
    return JSON.stringify([sheet.duration_ms, sheet.segments.map(s => [s.start_ms, s.end_ms,
      s.voices.map(v => [v.singer.trim(), v.words.map(w => [w.text.trim(),w.start_ms,w.end_ms])])])]);
  }
  function matches(invite, verified, hash) {
    if (invite.media_sha256 !== verified.sheet.media_sha256 || invite.duration_ms !== verified.sheet.duration_ms)
      return 'Load the exact recording named by this invite.';
    if (invite.timing_sha256 !== hash) return 'The lyric timing or singer assignments differ from this invite.';
    if (invite.part !== null && !verified.singers.includes(invite.part)) return 'The invited singer is missing from this score.';
    return '';
  }
  function mount({el, context, hash, apply, notify}) {
    const resolver = new WeakMap(), picker = el('karaoke-invite-file'), accept = el('karaoke-invite-accept');
    const info = el('karaoke-invite-info'), target = el('karaoke-invite-download'), share = el('karaoke-invite-share');
    let pending, seq = 0, draft, draftURL, lastState;
    function discard() {
      if (draftURL) URL.revokeObjectURL(draftURL);
      draftURL = null; draft = null; target.removeAttribute('href'); target.hidden = share.hidden = true;
    }
    function invalidate() {
      seq++; lastState = undefined; info.textContent = ''; accept.hidden = true; discard();
    }
    function state() {
      const current = context();
      if (!current.ready) throw Error('A verified score with at least 90% timing confidence is required for this recording.');
      return current;
    }
    async function digest(verified) {
      let result = resolver.get(verified);
      if (!result) {
        result = hash(new Blob([timing(verified.sheet)], {type:'application/json'}), new AbortController().signal);
        resolver.set(verified, result);
        result.catch(() => resolver.delete(verified));
      }
      return result;
    }
    async function create(requested) {
      const before = state(), part = requested === undefined ? before.part : requested; el('karaoke-invite').open = true;
      if (part !== null && !before.verified.singers.includes(part)) throw Error('Choose a singer from the current score.');
      const version = ++seq; discard();
      const timingHash = await digest(before.verified);
      if (version !== seq || !context().ready || context().verified !== before.verified) throw Error('The recording or score changed.');
      const sheet = before.verified.sheet;
      const invite = validate({schema, media_sha256:sheet.media_sha256, timing_sha256:timingHash, duration_ms:sheet.duration_ms,
        part, start_ms:Math.max(0,Math.min(before.ms,sheet.duration_ms-1))});
      const content = JSON.stringify(invite);
      draft = new Blob([content], {type:'application/json'}); draftURL = URL.createObjectURL(draft); target.href = draftURL; target.hidden = false;
      if (typeof File === 'function' && navigator.canShare && navigator.share) {
        try { share.hidden = !navigator.canShare({files:[new File([draft],'mariana-duet.json',{type:draft.type})]}); } catch { share.hidden = true; }
      }
      return 'Invite prepared for ' + describe(invite) + '. Use Save invite or Share invite.';
    }
    function describe(invite) {
      const ms = invite.start_ms, stamp = Math.floor(ms/60000)+':'+String(Math.floor(ms/1000)%60).padStart(2,'0')+'.'+String(ms%1000).padStart(3,'0');
      return (invite.part ?? 'all singers') + ' at ' + stamp;
    }
    async function open(file) {
      const version = ++seq;
      pending = null; accept.hidden = true; info.textContent = '';
      if (!file || file.size > 8192) throw Error('Choose a duet invite up to 8 KiB.');
      let data; try { data = JSON.parse((await file.text()).replace(/^\uFEFF/,'')); } catch { throw Error('This file is not a valid duet invite.'); }
      validate(data); if (version !== seq) return;
      pending = data; el('karaoke-invite').open = true; lastState = undefined; refresh();
    }
    function refresh() {
      const current = context();
      el('karaoke-invite-create').disabled = !current.ready;
      if (!pending || lastState?.ready === current.ready && lastState?.verified === current.verified) return;
      lastState = {ready:current.ready, verified:current.verified}; accept.hidden = true;
      info.textContent = 'Invite for '+describe(pending)+'. '+(current.ready ? 'Checking the recording and score…' : 'Load its recording and a verified score to apply.');
      if (!current.ready) return;
      const check = pending, reference = current.verified;
      digest(reference).then(value => {
        if (pending !== check || context().verified !== reference || !context().ready) return;
        const reason = matches(check,reference,value);
        info.textContent = 'Invite for '+describe(check)+'. '+(reason || 'Apply to select the part and seek.');
        accept.hidden = Boolean(reason);
      }).catch(() => { if (pending === check) info.textContent = 'Could not verify invite timing.'; });
    }
    async function applyInvite() {
      if (!pending) throw Error('Open a duet invite first.');
      const invite = pending, current = state(), digestValue = await digest(current.verified);
      if (pending !== invite || !context().ready || context().verified !== current.verified) throw Error('The recording or score changed.');
      const reason = matches(invite,current.verified,digestValue);
      if (reason) throw Error(reason);
      apply(invite.part, invite.start_ms); pending = null; accept.hidden = true;
      return info.textContent = 'Applied · '+describe(invite)+'.';
    }
    picker.onchange = async () => { const f = picker.files?.[0]; picker.value = ''; if (f) try { await open(f); } catch (e) { notify(e.message); } };
    accept.onclick = async () => { try { await applyInvite(); } catch (e) { notify(e.message); } };
    el('karaoke-invite-create').onclick = async () => { try { notify(await create()); } catch (e) { notify(e.message); } };
    share.onclick = async () => {
      if (!draft) return;
      try { await navigator.share({files:[new File([draft],'mariana-duet.json',{type:draft.type})]}); }
      catch (err) { if (err.name !== 'AbortError') notify('This app could not share the invite. Use Save invite.'); }
    };
    return {invalidate, refresh, create, openPicker:() => { el('karaoke-invite').open = true; picker.click(); }, apply:applyInvite};
  }
  window.MarianaKaraokeInvite = Object.freeze({timing,validate,matches,mount});
})();

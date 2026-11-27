(() => {
  'use strict';
  function publicLink(raw) {
    let u;
    try { u = new URL(raw); } catch { return null; }
    if (u.protocol !== 'https:' || u.username || u.password || u.port) return null;
    const path = u.pathname, host = u.hostname;
    const youtube = ['www.youtube.com','youtube.com','music.youtube.com','m.youtube.com'].includes(host);
    if (youtube || host === 'youtu.be') {
      const id = youtube && path === '/watch' ? u.searchParams.get('v') : host === 'youtu.be' ? path.slice(1) : '';
      if (!/^[A-Za-z0-9_-]{11}$/.test(id || '')) return null;
      const t = u.searchParams.get('t') || '';
      return 'https://www.youtube.com/watch?v=' + id + (/^\d{1,8}s?$/.test(t) ? '&t=' + parseInt(t,10) + 's' : '');
    }
    const patterns = {
      'open.spotify.com': /^\/(track|album|artist|episode|show)\/[a-zA-Z0-9]{22}\/?$/,
      'music.apple.com': /^\/[a-z]{2}\/(album|artist|song)\/[\w%.~-]+\/[0-9]+\/?$/i,
      'tidal.com': /^\/(?:browse\/)?(?:track|album|artist)\/[0-9]+\/?$/,
      'musicbrainz.org': /^\/(artist|recording|release|release-group)\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\/?$/i,
      'soundcloud.com': /^\/[a-z0-9_-]+\/(?:sets\/)?[a-z0-9_-]+\/?$/i,
    };
    const bandcamp = /^[a-z0-9]+(?:-[a-z0-9]+)*\.bandcamp\.com$/.test(host) && /^\/(album|track)\/[a-z0-9-]+\/?$/.test(path);
    if (!bandcamp && !(Object.prototype.hasOwnProperty.call(patterns, host) && patterns[host].test(path))) return null;
    const track = u.searchParams.get('i');
    return u.origin + path + (host === 'music.apple.com' && /^\d+$/.test(track || '') ? '?i=' + track : '');
  }
  globalThis.MarianaPublicLink = publicLink;
  if (typeof document === 'undefined') return;
  const get = id => document.getElementById(id);
  if (!get('public-form')) return;
  let current;
  const note = msg => { get('public-note').textContent = msg; };
  function use(raw) {
    current = publicLink(raw);
    get('snap-host').replaceChildren();
    get('public-url').textContent = current || '';
    get('share-actions').hidden = !current;
    if (!current) { note('Choose a public music link from YouTube, Spotify, Apple Music, TIDAL, Bandcamp, SoundCloud or MusicBrainz.'); return; }
    get('public-input').value = current;
    get('share-wa').href = 'https://wa.me/?text=' + encodeURIComponent(current);
    get('share-fb').href = 'https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(current);
    get('share-device').hidden = typeof navigator.share !== 'function';
    note('');
  }
  get('public-form').onsubmit = e => { e.preventDefault(); use(get('public-input').value); };
  get('public-input').oninput = () => { get('share-actions').hidden = true; current = null; get('snap-host').replaceChildren(); get('public-url').textContent = ''; note(''); };
  get('copy-link').onclick = async () => {
    try { await navigator.clipboard.writeText(current); note('Link copied.'); }
    catch { get('public-input').focus(); get('public-input').select(); note('Press Ctrl+C or use your device’s Copy action.'); }
  };
  get('share-device').onclick = async () => {
    try { await navigator.share({url:current}); }
    catch (e) { if (e.name !== 'AbortError') note('Use Copy link or choose a destination.'); }
  };
  get('share-snap').onclick = () => {
    if (!current) return;
    const frame = document.createElement('iframe');
    frame.title = 'Snapchat link composer';
    frame.setAttribute('sandbox','allow-scripts allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation');
    frame.referrerPolicy = 'no-referrer';
    frame.src = 'snap-share.html#' + encodeURIComponent(current);
    get('snap-host').replaceChildren(frame);
    note('Continue in Snapchat to preview the link.');
  };
  if (location.hash.length > 1) {
    try { use(decodeURIComponent(location.hash.slice(1))); } catch { note('Invalid link.'); }
  }
})();

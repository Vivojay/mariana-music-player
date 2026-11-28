/* Workspace navigation and imported media. The play queue owns its own order. */
(() => {
  'use strict';
  const areas = new Set(['library', 'discover', 'studio', 'rooms', 'settings']);
  const legacy = item => !item.url && /^(Local audio|Local video)$/.test(item.by || '');

  function makeLibrary(saved, queue) {
    const rows = Array.isArray(saved.library) ? saved.library.filter(item => item?.id && item.title) : queue
      .filter(legacy).map(({id,title,by,video}) => ({
        id,title,by,video:video ?? Boolean(globalThis.MarianaVideo?.isVideo({name:title})),
      }));
    saved.library = rows;
    const view = (query = '', kind = 'all') => {
      const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
      return rows.map((item, i) => ({item, number:i + 1})).filter(({item}) =>
        (kind === 'all' || (kind === 'video') === Boolean(item.video)) &&
        terms.every(term => (item.title + ' ' + item.by).toLowerCase().includes(term)));
    };
    return {rows, view};
  }

  function mount({list, play, queue, remove}) {
    const byId = id => document.getElementById(id);
    const nav = byId('workspace-navigation');
    const query = byId('library-query');
    const kind = byId('library-kind');
    const table = byId('local-library-rows');
    const toolbar = byId('library-pages');
    let offset = 0;
    const pageSize = 40;

    function open(area, moveFocus = false) {
      if (!areas.has(area)) return false;
      document.body.dataset.workspace = area;
      for (const button of nav.querySelectorAll('[data-area]')) {
        if (button.dataset.area === area) button.setAttribute('aria-current', 'page');
        else button.removeAttribute('aria-current');
      }
      if (moveFocus) byId('workspace-' + area)?.focus({preventScroll:true});
      if (moveFocus && document.body.dataset.mode === 'flow') window.scrollTo({top:0, behavior:'auto'});
      return true;
    }

    function action(label, context, listener) {
      const node = document.createElement('button');
      node.type = 'button';
      node.textContent = label;
      node.setAttribute('aria-label', label + ' ' + context);
      node.onclick = listener;
      return node;
    }

    function render() {
      const matches = list(query.value, kind.value);
      offset = Math.min(offset, Math.floor(Math.max(0, matches.length-1)/pageSize)*pageSize);
      table.replaceChildren();
      for (const {item, number} of matches.slice(offset, offset+pageSize)) {
        const row = document.createElement('div');
        const identity = document.createElement('div');
        const name = document.createElement('span');
        const info = document.createElement('small');
        const actions = document.createElement('div');
        row.className = 'library-row'; identity.className = 'library-identity'; actions.className = 'library-actions';
        name.textContent = item.title;
        info.textContent = '#' + number + ' · ' + (item.video ? 'Video' : 'Audio');
        identity.append(name, info);
        actions.append(action('Play', item.title, () => void play(item)),
          action('Queue', item.title, () => void queue(item)),
          action('Remove', item.title + ' from library', event => {
            if (event.currentTarget.dataset.confirm !== 'true') {
              event.currentTarget.dataset.confirm = 'true';
              event.currentTarget.textContent = 'Confirm';
              event.currentTarget.setAttribute('aria-label', 'Confirm removal of ' + item.title);
              return;
            }
            void remove(item);
          }));
        row.append(identity, actions); table.append(row);
      }
      const total = list().length;
      const count = byId('library-count');
      count.textContent = total === 0 ? 'No imported media. Choose files or a folder to begin.' :
        !matches.length ? 'No matches in your local library.' : matches.length + (matches.length === 1 ? ' item' : ' items') +
        (matches.length !== total ? ' of ' + total : '');
      toolbar.hidden = matches.length <= pageSize;
      byId('library-earlier').disabled = offset <= 0;
      byId('library-later').disabled = offset+pageSize >= matches.length;
      byId('library-page').textContent = matches.length ? (offset+1) + '–' + Math.min(offset+pageSize,matches.length) : '';
    }
    nav.addEventListener('click', event => {
      const area = event.target.closest('[data-area]')?.dataset.area;
      if (area) open(area, true);
    });
    for (const control of [query, kind]) control.addEventListener('input', () => { offset = 0; render(); });
    byId('library-earlier').onclick = () => { offset -= pageSize; render(); };
    byId('library-later').onclick = () => { offset += pageSize; render(); };
    open(new URLSearchParams(location.search).get('panel')) || open('library');
    render();
    return {open, render};
  }

  globalThis.MarianaWorkspace = {makeLibrary, mount};
})();

(() => {
  'use strict';

  const titles = {
    queue: 'Play queue', playlists: 'Playlists', albums: 'Albums',
    favorites: 'Favorites', live: 'Live radio',
  };
  const empty = {
    queue: 'The native play queue is empty.',
    playlists: 'There are no saved playlists in this profile.',
    albums: 'No tagged local albums or saved editions.',
    favorites: 'Favorite recordings will appear here.',
    live: 'No stations are available in the native radio directory.',
  };

  function mount({root, request, submit}) {
    const doc = root.ownerDocument;
    let collection = '', detail = null, offset = 0, version = 0, busy = false, loaded = false, rendered = '';

    function node(tag, className, text) {
      const element = doc.createElement(tag);
      if (className) element.className = className;
      if (text) element.textContent = text;
      return element;
    }

    function button(label, callback) {
      const control = node('button', '', label);
      control.type = 'button';
      control.onclick = callback;
      return control;
    }

    function actionButton(label, command, binding) {
      const control = button(label, () => {
        if (!busy) void submit(command, binding);
      });
      control.dataset.collectionCommand = 'true';
      control.disabled = busy;
      return control;
    }

    const title = node('h2');
    const toolbar = node('div', 'collection-toolbar');
    const heading = node('div', 'collection-heading');
    const filters = node('form', 'collection-filters');
    const query = node('input');
    query.type = 'search';
    query.maxLength = 160;
    query.setAttribute('aria-label', 'Search this collection');
    const search = node('button', '', 'Search');
    search.type = 'submit';
    filters.append(query, search);
    const count = node('p', 'collection-status');
    const error = node('p', 'collection-error');
    error.setAttribute('role', 'status');
    const rows = node('ol', 'collection-results');
    const pages = node('div', 'collection-pages');
    const back = button('Back to collection', () => {
      detail = null; query.value = ''; void load(0);
    });
    back.hidden = true;
    const previous = button('Previous page', () => void load(Math.max(0, offset - pageSize)));
    const next = button('Next page', () => void load(offset + pageSize));
    const range = node('span', 'collection-range');
    pages.append(previous, range, next);
    pages.hidden = true;
    heading.append(title, back);
    root.replaceChildren(heading, toolbar, filters, count, error, rows, pages);
    let pageSize = 30;

    function addActions(container, row) {
      if (!row.key || !Array.isArray(row.actions)) return;
      for (const action of row.actions) {
        if (typeof action.command !== 'string' || !action.label || !action.name) continue;
        const control = actionButton(action.label, action.command, {key:row.key, action:action.name});
        control.setAttribute('aria-label', action.label + ' ' + row.title);
        container.append(control);
      }
    }

    function toolset(data) {
      toolbar.replaceChildren();
      if (data.detail) {
        addActions(toolbar, data.detail);
        return;
      }
      if (collection === 'queue') {
        toolbar.append(
          actionButton('Shuffle', 'queue shuffle'), actionButton('Undo', 'queue undo'),
          actionButton('Redo', 'queue redo'), actionButton('Clear queue…', 'queue clear'),
        );
        const repeat = node('select');
        repeat.setAttribute('aria-label', 'Queue repeat');
        for (const [mode, label] of [['off', 'Repeat off'], ['one', 'Repeat one'], ['all', 'Repeat all']]) {
          const choice = node('option', '', label);
          choice.value = mode;
          repeat.append(choice);
        }
        repeat.value = data.status?.repeat || 'off';
        const current = repeat.value;
        repeat.dataset.collectionCommand = 'true';
        repeat.disabled = busy;
        repeat.onchange = () => {
          const choice = repeat.value;
          repeat.value = current;
          if (!busy && choice !== current) void submit('queue repeat ' + choice);
        };
        toolbar.append(repeat);
        for (const [setting, label] of [['consume','Remove played'], ['autofill','Auto-fill queue']]) {
          const active = Boolean(data.status?.[setting]);
          const control = actionButton(label, 'queue ' + setting + (active ? ' off' : ' on'));
          control.setAttribute('aria-pressed', String(active));
          toolbar.append(control);
        }
      } else if (collection === 'live') {
        toolbar.append(actionButton('Return to live edge', 'radio resync'));
      }
    }

    function render(data) {
      // Replacing unchanged boards would disturb keyboard focus during periodic updates.
      const signature = JSON.stringify(data);
      if (signature === rendered) return;
      rendered = signature;
      title.textContent = data.detail ? data.detail.title : titles[collection];
      back.hidden = !detail;
      root.dataset.collectionView = collection;
      toolset(data);
      rows.replaceChildren();
      for (const record of data.rows) {
        const row = node('li', 'collection-record');
        if (record.active) row.setAttribute('aria-current', 'true');
        const label = node('div', 'collection-label');
        const name = record.detail
          ? button(record.title, () => {
              detail = record.key;
              back.hidden = false;
              query.value = '';
              void load(0);
            })
          : node('strong', '', record.title);
        if (record.detail) name.className = 'collection-open';
        label.append(name);
        if (record.description) label.append(node('small', '', record.description));
        const actions = node('div', 'collection-actions');
        addActions(actions, record);
        row.append(label, actions);
        rows.append(row);
      }
      count.textContent = data.total ? data.total + (data.total === 1 ? ' item' : ' items') :
        query.value.trim() ? 'Nothing matched this search.' : detail ? 'No tracks in this collection.' : empty[collection];
      pages.hidden = data.total <= pageSize;
      range.textContent = data.total ? (offset + 1) + '–' + (offset + data.rows.length) : '';
      previous.disabled = offset === 0;
      next.disabled = offset + pageSize >= data.total;
    }

    async function load(start, background = false) {
      if (!collection) return;
      const turn = ++version, selected = collection, key = detail;
      const data = {collection:selected, query:query.value, offset:start};
      if (key) data.detail = key;
      if (!background) error.textContent = '';
      if (!loaded) count.textContent = 'Loading ' + titles[selected].toLowerCase() + '…';
      try {
        const response = await request(data);
        if (turn !== version || selected !== collection || key !== detail) return;
        if (!response || !Array.isArray(response.rows) || !Number.isInteger(response.total)
            || !Number.isInteger(response.pageSize) || response.pageSize < 1) {
          throw new Error('Mariana returned an invalid collection.');
        }
        offset = start;
        pageSize = response.pageSize;
        if (offset && offset >= response.total)
          return void load(Math.max(0, Math.floor((response.total - 1) / pageSize) * pageSize));
        loaded = true;
        error.textContent = '';
        render(response);
      } catch (problem) {
        if (turn !== version) return;
        count.textContent = '';
        error.textContent = problem.message || 'Could not read the native collection.';
        if (!loaded) rows.replaceChildren();
      }
    }

    filters.onsubmit = event => {
      event.preventDefault();
      void load(0);
    };

    function clear() {
      version++;
      collection = '';
      detail = null;
      query.value = '';
      offset = 0;
      loaded = false;
      rendered = '';
      rows.replaceChildren();
      toolbar.replaceChildren();
      count.textContent = '';
      error.textContent = '';
      pages.hidden = true;
      back.hidden = true;
    }

    return {
      show(name = 'queue') {
        if (!Object.prototype.hasOwnProperty.call(titles, name)) return false;
        if (collection !== name) {
          clear();
          collection = name;
          title.textContent = titles[name];
          query.placeholder = 'Search ' + titles[name].toLowerCase();
        }
        void load(offset, loaded);
        return true;
      },
      refresh() {
        if (collection && !root.hidden) void load(offset, true);
      },
      clear,
      hide() { version++; },
      setBusy(locked) {
        busy = Boolean(locked);
        for (const control of root.querySelectorAll('[data-collection-command]')) control.disabled = busy;
      },
    };
  }

  window.MarianaCollections = {mount};
})();

(() => {
  'use strict';

  const modes = {
    hybrid: 'Audio and tags',
    audio: 'Audio',
    tags: 'Tags',
    fingerprint: 'Fingerprint',
  };

  function mount({root, request, submit}) {
    const doc = root.ownerDocument;
    let target = null;
    let generation = 0;
    let busy = false;
    let shown = false;

    function node(tag, className, text) {
      const element = doc.createElement(tag);
      if (className) element.className = className;
      if (text) element.textContent = text;
      return element;
    }

    const heading = node('h2', '', 'Find similar');
    const reference = node('p', 'similar-reference');
    const label = node('label', '', 'Compare by');
    const mode = node('select');
    for (const [value, description] of Object.entries(modes)) {
      const option = node('option', '', description);
      option.value = value;
      mode.append(option);
    }
    label.append(mode);
    const form = node('form', 'similar-options');
    const search = node('button', '', 'Find matches');
    search.type = 'submit';
    const scan = node('button', '', 'Analyze next 12 tracks');
    scan.type = 'button';
    scan.onclick = () => {
      if (!busy) void submit('similar scan --limit 12');
    };
    form.append(label, search, scan);
    const status = node('p', 'similar-status');
    status.setAttribute('role', 'status');
    const rows = node('ol', 'similar-results');
    root.replaceChildren(heading, reference, form, status, rows);

    function updateControls() {
      search.disabled = busy || !target;
      mode.disabled = !target;
      scan.disabled = busy;
      for (const button of rows.querySelectorAll('button')) button.disabled = busy;
    }

    function action(label, record, command) {
      const control = node('button', '', label);
      control.type = 'button';
      control.disabled = busy;
      control.setAttribute('aria-label', label + ' ' + record.title);
      control.onclick = () => {
        if (!busy) void submit(command + ' ' + record.number, record.key);
      };
      return control;
    }

    function render(data, choice) {
      if (!data || typeof data.title !== 'string' || !Array.isArray(data.rows))
        throw Error('Mariana returned an invalid similarity result.');
      reference.textContent = data.title;
      let count = 0;
      for (const record of data.rows.slice(0, 20)) {
        if (!record || typeof record.title !== 'string' || typeof record.key !== 'string' ||
            !record.key || !Number.isSafeInteger(record.number) || record.number < 1) continue;
        const row = node('li', 'similar-record');
        const main = node('div', 'similar-record-main');
        const text = node('div', 'similar-record-label');
        text.append(node('strong', '', record.title));
        if (typeof record.artist === 'string' && record.artist) text.append(node('small', '', record.artist));
        main.append(text);
        if (Number.isFinite(record.score))
          main.append(node('span', 'similar-score', record.score.toFixed(2) + ' score'));
        row.append(main);
        const reasons = Array.isArray(record.reasons) ? record.reasons.filter(reason => typeof reason === 'string') : [];
        if (reasons.length) row.append(node('small', 'similar-reasons', reasons.join(' · ')));
        const actions = node('div', 'similar-actions');
        actions.append(action('Play', record, 'play'), action('Queue', record, 'queue add'));
        row.append(actions);
        rows.append(row);
        count++;
      }
      status.textContent = count ? count + (count === 1 ? ' match' : ' matches') :
        choice === 'audio' ? 'No audio matches. Run similar scan in Mariana to index more recordings.' :
          'No matches in the indexed library.';
    }

    async function load() {
      const turn = ++generation;
      rows.replaceChildren();
      if (!target) {
        reference.textContent = '';
        status.textContent = 'Play an indexed recording or choose Find similar next to a library item.';
        return;
      }
      const choice = mode.value;
      status.textContent = 'Finding matches…';
      try {
        const result = await request({...target, mode:choice, limit:20});
        if (shown && turn === generation) render(result, choice);
      } catch (error) {
        if (shown && turn === generation) {
          rows.replaceChildren();
          status.textContent = error?.message || 'Could not find similar recordings.';
        }
      }
    }

    form.onsubmit = event => {
      event.preventDefault();
      if (!busy) void load();
    };
    mode.onchange = () => { if (shown && !busy) void load(); };

    function hide() {
      shown = false;
      generation++;
    }

    return {
      show(selection = target) {
        shown = true;
        if (selection !== target) reference.textContent = '';
        if (selection?.number && selection.key) {
          target = {number:selection.number, key:selection.key};
        } else if (selection?.occurrence) {
          target = {occurrence:selection.occurrence};
        } else {
          target = null;
        }
        updateControls();
        return load();
      },
      hide,
      refresh() { if (shown) return load(); },
      clear() {
        hide();
        target = null;
        busy = false;
        mode.value = 'hybrid';
        reference.textContent = '';
        status.textContent = '';
        rows.replaceChildren();
        updateControls();
      },
      setBusy(locked) {
        busy = Boolean(locked);
        updateControls();
      },
    };
  }

  window.MarianaPairedSimilar = {mount};
})();

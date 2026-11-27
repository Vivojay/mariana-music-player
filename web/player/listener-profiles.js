(() => {
  'use strict';
  const registry = 'mariana.listener.name.';
  const selection = 'mariana.listener.active';
  let current = 'default';
  try { current = sessionStorage.getItem(selection) || current; } catch {}
  function name(input) {
    const text = input.trim();
    if (!/^[\p{L}\p{N}](?:[\p{L}\p{N} ._-]{0,38}[\p{L}\p{N}])?$/u.test(text)) {
      throw Error('Use 1–40 letters, numbers, spaces, dashes, periods or underscores.');
    }
    return text;
  }
  function key(original) {
    return current === 'default' ? original : 'mariana.listener.' + current + ':' + original;
  }
  function list() {
    const result = new Map([['default', 'Default']]);
    for (let i = 0; i < localStorage.length; i++) {
      const nameKey = localStorage.key(i);
      if (nameKey?.startsWith(registry)) result.set(nameKey.slice(registry.length), localStorage.getItem(nameKey));
    }
    return result;
  }
  function run(args) {
    const [op = 'list', ...words] = args;
    if ((op === 'list' || op === 'current') && !words.length) {
      return [...list()].filter(([id]) => op === 'list' || id === current)
        .map(([id, label]) => label + (id === current ? ' · this tab' : '')).join('\n');
    }
    if (op === 'help') return 'profile list · profile current · profile create NAME · profile use NAME';
    if (!['create','use'].includes(op) || !words.length) throw Error('Use profile help to see listener commands.');
    const label = name(words.join(' ')), id = label.toLowerCase();
    if (op === 'create') {
      if (list().has(id)) throw Error('A profile with this name already exists.');
      localStorage.setItem(registry + id, label);
      return 'Created ' + label + '. Select it when you are ready to switch.';
    }
    if (!list().has(id)) throw Error('Create this listener profile first.');
    if (id === current) return label + ' is already active.';
    sessionStorage.setItem(selection, id);
    location.reload();
    return 'Opening ' + label;
  }
  const api = {key, list, run, current};
  window.MarianaProfiles = api;
  const form = document.getElementById('listener-profiles');
  if (!form) return;
  const select = form.elements.listener;
  const feedback = document.getElementById('listener-feedback');
  function render() {
    select.replaceChildren(...[...list()].map(([id, label]) => new Option(label, id, false, id === current)));
  }
  try { render(); } catch { feedback.textContent = 'Browser storage is unavailable.'; }
  form.addEventListener('submit', event => {
    event.preventDefault();
    try {
      const create = event.submitter?.value === 'create';
      feedback.textContent = run(create ? ['create', form.elements.newName.value] : ['use', select.value]);
      if (create) { const added = form.elements.newName.value.trim().toLowerCase(); form.elements.newName.value = ''; render(); select.value = added; }
    } catch (error) { feedback.textContent = error.message; }
  });
  window.addEventListener('storage', event => { if (event.key?.startsWith(registry)) render(); });
})();

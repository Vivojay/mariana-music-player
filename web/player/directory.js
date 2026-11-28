'use strict';

(() => {
  const sources = window.MARIANA_SOURCES;
  const categories = {
    'press-links': 'Music press', 'culture-links': 'Arts and culture', 'performance-links': 'Live performances',
    'chart-links': 'Charts', 'show-links': 'Shows', 'discovery-links': 'Music discovery',
    'festival-links': 'Festivals and conventions',
  };
  const query = document.getElementById('directory-query');
  const group = document.getElementById('directory-group');
  const results = document.getElementById('directory-results');
  const more = document.getElementById('directory-more');
  const count = document.getElementById('directory-count');
  const message = document.getElementById('directory-status');
  const batch = 6;
  let limit = batch;
  for (const [value, name] of Object.entries(categories)) group.add(new Option(name, value));

  function normalized(value) {
    return value.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase();
  }
  function search(term, category = '') {
    const words = normalized(term.trim()).split(/\s+/).filter(Boolean);
    return sources.filter(source => {
      if (category && source.group !== category) return false;
      const fields = normalized([source.title, source.source, source.summary, source.id,
        categories[source.group], source.url].join(' '));
      return words.every(word => fields.includes(word));
    });
  }
  async function copyURL(source, row) {
    try {
      await navigator.clipboard.writeText(source.url);
      message.textContent = source.title + ' URL copied.';
    } catch {
      let input = row.querySelector('input');
      if (!input) {
        input = document.createElement('input');
        input.readOnly = true;
        input.setAttribute('aria-label', source.title + ' URL');
        input.value = source.url;
        row.append(input);
      }
      input.focus(); input.select();
      message.textContent = 'Copy the selected URL using your device’s copy command.';
    }
  }
  function draw() {
    const matches = search(query.value, group.value);
    const visible = matches.slice(0, limit);
    count.textContent = matches.length ? visible.length + ' of ' + matches.length + ' sources' : 'No sources matched.';
    results.replaceChildren();
    message.textContent = '';
    for (const source of visible) {
      const row = document.createElement('li');
      const summary = document.createElement('p');
      const title = document.createElement('a');
      title.href = source.url;
      title.textContent = source.title;
      title.target = (location.protocol === 'file:' || location.hostname === 'app.mariana.invalid' ||
        window.MarianaNativeShell === 'ios') ? '_self' : '_blank';
      title.rel = 'noopener noreferrer';
      summary.textContent = source.summary;
      const copy = document.createElement('button');
      copy.type = 'button'; copy.textContent = 'Copy URL';
      copy.setAttribute('aria-label', 'Copy URL for ' + source.title);
      copy.onclick = () => copyURL(source, row);
      row.append(title, copy, summary);
      results.append(row);
    }
    more.hidden = matches.length <= limit;
  }
  function reset() { limit = batch; draw(); }
  query.addEventListener('input', reset);
  group.addEventListener('change', reset);
  more.addEventListener('click', () => { limit += batch; draw(); });
  window.MarianaDirectory = {
    consoleSearch(term) {
      query.value = term; group.value = ''; reset();
      const rows = search(term);
      return rows.length ? rows.map(source => source.title + ' · ' + source.url).join('\n') : 'No sources matched.';
    },
  };
  draw();
})();

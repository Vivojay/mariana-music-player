'use strict';
(() => {
  const maxRows = 40;
  const row = (value, description) => ({value:String(value), description:String(description || '')});
  const clean = value => typeof value === 'string' && value.length > 0 && value.length <= 1024 &&
    !/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/u.test(value);
  function options(select, labels = false) {
    return Array.from(select?.options || []).filter(option => !option.disabled).map(option =>
      row(labels && option.value !== 'all' ? option.textContent : option.value, option.textContent));
  }
  function values(tokens, ctx) {
    const [first, second] = tokens, length = tokens.length;
    const cmd = String(first || '').toLowerCase(), op = String(second || '').toLowerCase();
    const get = id => ctx.el?.(id);
    const queue = Array.isArray(ctx.queue) ? ctx.queue : [];
    if (cmd === 'play' && length === 1) return queue.map((item, i) => row(i + 1, item.title));
    if (cmd === 'library' && length === 2 && ['play','queue'].includes(op))
      return (Array.isArray(ctx.library) ? ctx.library : []).map((item,i) => row(i+1,item.title));
    if (cmd === 'tone' && op === 'procedure' && tokens[2]?.toLowerCase() === 'play' && length === 3)
      return globalThis.MarianaToneProcedures?.completionRows() || [];
    if (cmd === 'speed' && length === 1) return options(get('rate'));
    if (cmd === 'theme' && length === 1) return Object.entries(ctx.themes || {}).map(([id, theme]) => row(id, theme.name));
    if (cmd === 'accounts' && length === 2 && ['link','unlink','open'].includes(op)) return options(get('account-provider'));
    if (cmd === 'karaoke' && length === 2 && ['invite','part'].includes(op)) {
      if (get('karaoke-controls')?.hidden) return [];
      return options(get('karaoke-part'), true);
    }
    if (cmd === 'sources' && length === 1 || cmd === 'home' && op === 'sources' && length === 2) {
      return (globalThis.MARIANA_SOURCES || []).map(source => row(source.title, source.source));
    }
    if (cmd === 'podbean' && length === 2 && ['open','follow','unfollow','play','queue','episodes'].includes(op))
      return globalThis.MarianaPodbean?.completionRows?.(op) || [];
    if (['librivox','lv','libri'].includes(cmd)) {
      if (length === 2 && ['show','chapters','play','queue','rss'].includes(op))
        return globalThis.MarianaLibrivox?.completionRows?.() || [];
      if (length === 3 && ['play','queue'].includes(op)) {
        const chapters = globalThis.MarianaLibrivox?.completionRows?.(tokens[2]) || [];
        return op === 'queue' ? [row('all','All chapters'), ...chapters] : chapters;
      }
    }
    if (cmd === 'jam') {
      if (length === 2 && ['invite','join','leave','members','suggest','cue','send','current','apply','sync','timeline'].includes(op)) {
        const visible = get('jam-room')?.value;
        return [...(ctx.rooms || []), visible].filter(room => typeof room === 'string' && /^[!#][^\s:]+:[^\s/]+$/.test(room)).map(room => row(room,'Room'));
      }
      if (length === 3 && op === 'suggest' || length === 5 && op === 'cue') {
        return [ctx.current, ...queue].filter(item => clean(item?.title)).map(item => row(item.title,'Player track'));
      }
    }
    return [];
  }
  function suggest(tokens, prefix, context = {}) {
    if (!Array.isArray(tokens) || typeof prefix !== 'string' || prefix.length > 1024) return [];
    const search = prefix.toLowerCase(), seen = new Set(), matches = [];
    for (const candidate of values(tokens, context)) {
      if (!clean(candidate.value) || seen.has(candidate.value)) continue;
      const description = clean(candidate.description) ? candidate.description : '';
      if (!candidate.value.toLowerCase().startsWith(search) && !description.toLowerCase().startsWith(search)) continue;
      matches.push({value:candidate.value, description});
      seen.add(candidate.value);
      if (matches.length === maxRows) break;
    }
    return matches;
  }
  globalThis.MarianaPortableValues = {suggest};
})();

'use strict';
(() => {
  const svg = 'http://www.w3.org/2000/svg';
  const luma = [0.2126, 0.7152, 0.0722];
  const identity = [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0];
  const aliases = {none:'off', grey:'grayscale', 'b&w':'threshold', bw:'threshold', 'black-white':'threshold'};
  const extensions = /\.(?:mp4|m4v|mkv|webm|mov|avi|ogv|mpg|mpeg|ts|mts|m2ts|wmv|flv|3gp|3g2|ivf|nut|rm)$/i;
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

  function isVideo(file) {
    const type = String(file?.type || '').toLowerCase();
    if (type.startsWith('audio/')) return false;
    return type.startsWith('video/') || extensions.test(String(file?.name || ''));
  }

  function parse(presets, name, value) {
    name = String(name || '').toLowerCase();
    name = own(aliases, name) ? aliases[name] : name;
    if (!own(presets, name)) throw Error('Choose a video filter from video filter list.');
    if (value !== undefined && (name !== 'threshold' || !/^\d{1,3}$/.test(String(value)) || Number(value) > 100))
      throw Error('Threshold must be a whole number from 0 to 100.');
    return {preset:name, threshold:value === undefined ? 50 : Number(value)};
  }

  function element(doc, name, attributes) {
    const node = doc.createElementNS(svg, name);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    return node;
  }

  function matrixRows(rows) {
    return [...rows.flatMap(row => [row[0], row[1], row[2], 0, row[3] ?? 0]), ...identity.slice(15)];
  }

  function directive(spec, threshold) {
    if (!spec || spec.kind === 'identity') return {space:'sRGB', elements:[]};
    switch (spec.kind) {
      case 'matrix':
      case 'linear-matrix':
        return {space:spec.kind === 'linear-matrix' ? 'linearRGB' : 'sRGB', elements:[
          {tag:'feColorMatrix', attributes:{type:'matrix', values:matrixRows([0, 3, 6].map(i => spec.matrix.slice(i, i + 3))).join(' ')}},
        ]};
      case 'duotone':
        return {space:'sRGB', elements:[{tag:'feColorMatrix', attributes:{type:'matrix',
          values:matrixRows(spec.low.map((low, c) => [...luma.map(weight => weight * (spec.high[c] - low)), low])).join(' ')}}]};
      case 'invert':
        return {space:'sRGB', elements:[{tag:'feColorMatrix', attributes:{type:'matrix',
          values:matrixRows([[-1,0,0,1], [0,-1,0,1], [0,0,-1,1]]).join(' ')}}]};
      case 'contrast':
        return {space:'sRGB', elements:[{tag:'feColorMatrix', attributes:{type:'matrix',
          values:matrixRows([[1.5,0,0,-.25], [0,1.5,0,-.25], [0,0,1.5,-.25]]).join(' ')}}]};
      case 'threshold': {
        const table = Array.from({length:256}, (_, i) => i / 255 >= threshold / 100 ? 1 : 0).join(' ');
        return {space:'sRGB', elements:[
          {tag:'feColorMatrix', attributes:{type:'matrix', values:matrixRows([luma, luma, luma]).join(' ')}},
          {tag:'feComponentTransfer', attributes:{}, children:['feFuncR','feFuncG','feFuncB'].map(tag => ({
            tag, attributes:{type:'discrete', tableValues:table},
          }))},
        ]};
      }
      default: return {space:'sRGB', elements:[]};
    }
  }

  function setFilterDefinition(node, spec, threshold) {
    const details = directive(spec, threshold);
    node.setAttribute('color-interpolation-filters', details.space);
    const doc = node.ownerDocument;
    node.replaceChildren(...details.elements.map(description => {
      const filter = element(doc, description.tag, description.attributes);
      for (const child of description.children || []) filter.append(element(doc, child.tag, child.attributes));
      return filter;
    }));
  }

  function mount(el, saved, remember) {
    const panel = el('local-picture-panel'), video = el('local-picture');
    const filterSelect = el('local-picture-filter'), threshold = el('local-picture-threshold');
    const presets = globalThis.MarianaVideoPresets;
    const definition = el('mariana-portable-video-filter');
    let current = {preset:'off', threshold:50};
    let visible = false;
    for (const [preset, info] of Object.entries(presets)) {
      const option = filterSelect.ownerDocument.createElement('option');
      option.value = preset;
      option.textContent = info.label;
      filterSelect.append(option);
    }
    function update(selection, persist) {
      current = selection;
      filterSelect.value = current.preset;
      threshold.value = current.threshold;
      threshold.parentElement.hidden = current.preset !== 'threshold';
      setFilterDefinition(definition, presets[current.preset], current.threshold);
      video.style.filter = current.preset === 'off' ? '' : 'url(#mariana-portable-video-filter)';
      if (persist) remember?.(current);
    }
    try { update(parse(presets, saved?.preset, saved?.preset === 'threshold' ? saved.threshold : undefined), false); }
    catch { update(current, false); }
    filterSelect.addEventListener('change', () => update(parse(presets, filterSelect.value), true));
    threshold.addEventListener('change', () => update(parse(presets, 'threshold', threshold.value), true));
    el('local-picture-fullscreen').addEventListener('click', async () => {
      try {
        if (panel.ownerDocument.fullscreenElement === panel) await panel.ownerDocument.exitFullscreen();
        else await panel.requestFullscreen();
      } catch { el('local-picture-notice').textContent = 'Fullscreen is unavailable in this window.'; }
    });
    const show = state => {
      visible = state;
      panel.hidden = !state;
      panel.closest('.player')?.classList.toggle('has-picture', state);
      if (state) el('local-picture-notice').textContent = '';
    };
    function command(args, hasVideo) {
      const action = args[0]?.toLowerCase() || 'status';
      if (action === 'filter') {
        const preset = args[1]?.toLowerCase() || 'status';
        if (preset === 'list' && args.length === 2) return Object.keys(presets).join(', ');
        if (preset !== 'status' && args.length <= 3) update(parse(presets, preset, args[2]), true);
        else if (args.length > 2) throw Error('Use video filter [list|status|preset] [threshold].');
        return 'Video filter: ' + presets[current.preset].label
          + (current.preset === 'threshold' ? ' (' + current.threshold + '%)' : '');
      }
      if (args.length > 1 || !['open','close','status'].includes(action))
        throw Error('Use video [open|close|status|filter].');
      if (action === 'open' && !hasVideo) return 'Choose a video file to display.';
      if (action === 'open' || action === 'close') show(action === 'open');
      return 'Video: ' + (hasVideo ? (visible ? 'visible' : 'hidden') : 'no local video selected');
    }
    return {show, command};
  }

  globalThis.MarianaVideo = {isVideo, parse, directive, setFilterDefinition, mount};
})();

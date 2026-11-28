/* The paired native command editor and transcript share one terminal viewport. */
(() => {
  'use strict';
  const standard = ['#191d27','#ef7886','#88c67a','#edc17b','#86acfa','#d49ced','#73cdda','#d4dbea',
    '#657089','#ff97a1','#b3e59c','#ffdc9c','#a4c4ff','#e8b1ff','#a0e8ef','#f6f8ff'];
  const safeText = text => text.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/g, '');
  // Retain styled text only. OSC, DCS and cursor-control sequences have no side effects.
  const escapes = /\x1b(?:\[([0-?]*)([ -\/]*)([@-~])|\](?:[^\x07\x1b]|\x1b(?!\\))*(?:\x07|\x1b\\|$)|[PX^_](?:[^\x1b]|\x1b(?!\\))*(?:\x1b\\|$)|\[[0-?]*[ -\/]*$|[ -\/]*[0-~])/g;

  function indexedColor(index) {
    if (!Number.isInteger(index) || index < 0 || index > 255) return '';
    if (index < standard.length) return standard[index];
    if (index >= 232) {
      const level = 8 + 10 * (index - 232);
      return 'rgb(' + [level,level,level].join(',') + ')';
    }
    const level = channel => channel ? 55 + channel*40 : 0;
    const value = index - 16;
    return 'rgb(' + [level(Math.floor(value/36)),level(Math.floor(value/6)%6),level(value%6)].join(',') + ')';
  }

  function sgr(state, raw) {
    if (raw && !/^\d*(?:;\d*)*$/.test(raw)) return state;
    const values = raw.split(';').map(Number);
    for (let i=0; i<values.length; i++) {
      const code = values[i];
      if (code === 0) state = {};
      else if (code === 1) state.fontWeight = 'bold';
      else if (code === 2) state.opacity = '.65';
      else if (code === 3) state.fontStyle = 'italic';
      else if (code === 4) state.textDecoration = 'underline';
      else if (code === 22) { delete state.fontWeight; delete state.opacity; }
      else if (code === 23) delete state.fontStyle;
      else if (code === 24) delete state.textDecoration;
      else if (code === 39) delete state.color;
      else if (code === 49) delete state.backgroundColor;
      else if (code >= 30 && code <= 37) state.color = standard[code-30];
      else if (code >= 90 && code <= 97) state.color = standard[code-82];
      else if (code >= 40 && code <= 47) state.backgroundColor = standard[code-40];
      else if (code >= 100 && code <= 107) state.backgroundColor = standard[code-92];
      else if (code === 38 || code === 48) {
        const mode = values[++i];
        let color = '';
        if (mode === 5) color = indexedColor(values[++i]);
        else if (mode === 2) {
          const channels = values.slice(i+1,i+4);
          i += 3;
          if (channels.length === 3 && channels.every(n => Number.isInteger(n) && n >= 0 && n <= 255))
            color = 'rgb(' + channels.join(',') + ')';
        }
        if (color) state[code === 38 ? 'color' : 'backgroundColor'] = color;
      }
    }
    return state;
  }

  function styledOutput(value) {
    const text = value.replace(/\r\n?/g,'\n');
    const chunks = [];
    let cursor = 0, state = {};
    escapes.lastIndex = 0;
    for (const match of text.matchAll(escapes)) {
      if (match.index > cursor) chunks.push({text:safeText(text.slice(cursor,match.index)),style:{...state}});
      if (match[3] === 'm' && match[2] === '' && chunks.length < 1024) state = sgr(state,match[1]);
      cursor = match.index + match[0].length;
    }
    if (cursor < text.length) chunks.push({text:safeText(text.slice(cursor)),style:{...state}});
    return chunks;
  }

  function mount(panel) {
    if (!panel) return null;
    const doc = panel.ownerDocument, byId = id => doc.getElementById(id);
    const output = byId('native-log'), form = byId('native-command'), editor = byId('native-text');
    const pending = byId('native-pending'), actions = byId('disconnect').parentElement;
    const notice = byId('native-browser-notice');
    const viewportElements = [output,pending,form,byId('native-suggestions'),byId('native-assist-status')];
    const elements = [...viewportElements,notice,actions];
    const origins = elements.map(node => {
      const marker = doc.createComment('paired terminal origin');
      node.parentNode.insertBefore(marker,node);
      return marker;
    });
    const viewport = doc.createElement('div');
    viewport.className = 'native-terminal-viewport';
    const context = doc.createElement('p');
    context.className = 'native-terminal-context';
    context.setAttribute('aria-hidden','true');
    const guide = doc.createElement('div');
    guide.className = 'native-terminal-guide';
    const keys = doc.createElement('p');
    keys.textContent = 'Tab complete · Ctrl+R history · Ctrl+L clear screen';
    guide.append(keys);
    panel.append(viewport,guide);
    editor.setAttribute('enterkeyhint','send');
    let size = 0, mode;

    function bottom() { viewport.scrollTop = viewport.scrollHeight; }
    function focus() {
      if (mode === 'console' && !panel.closest('[hidden]') && !editor.disabled) editor.focus();
    }
    function setMode(next) {
      if (mode === next) return;
      mode = next;
      panel.hidden = next !== 'console';
      if (next === 'console') {
        viewport.append(output,pending,notice,context,form,...viewportElements.slice(3));
        guide.append(actions);
        bottom();
        focus();
      } else {
        for (const [index,node] of elements.entries()) {
          const marker = origins[index];
          marker.parentNode.insertBefore(node,marker.nextSibling);
        }
      }
    }
    function setPlayback(state) {
      const title = typeof state?.title === 'string' ? state.title.replace(/[\r\n]/g, ' ').slice(0,240) : '';
      const playback = typeof state?.display_state === 'string' ? state.display_state : '';
      const description = title ? (playback ? '('+playback+') ' : '') + title : '(Not Playing)';
      context.textContent = '┏━ ' + description;
    }
    setPlayback(null);

    function clear() { output.replaceChildren(); size = 0; }

    function appendJob(job) {
      const follow = mode !== 'console' || viewport.scrollHeight-viewport.scrollTop-viewport.clientHeight < 40;
      // The browser keeps the newest complete blocks through view switches.
      if (!output.firstChild) size = 0;
      const block = doc.createElement('span'), command = doc.createElement('span');
      const line = safeText(String(job.command || ''));
      const heading = mode === 'console' ? context.textContent + '\n┗━ ready ❱ ' : '› ';
      command.className = 'native-terminal-command';
      command.textContent = heading + line + '\n';
      block.className = 'native-terminal-entry';
      block.append(command);
      const result = typeof job.ansiOutput === 'string' ? job.ansiOutput : String(job.output || '');
      for (const chunk of styledOutput(result.slice(-32000))) {
        if (!chunk.text) continue;
        if (Object.keys(chunk.style).length === 0 || block.childNodes.length >= 1024) {
          const previous = block.lastChild;
          if (previous?.nodeType === 3) previous.appendData(chunk.text);
          else block.append(doc.createTextNode(chunk.text));
        } else {
          const span = doc.createElement('span');
          span.textContent = chunk.text;
          for (const [name,value] of Object.entries(chunk.style)) span.style[name] = value;
          block.append(span);
        }
      }
      block.append(doc.createTextNode('\n'));
      size += block.textContent.length;
      block.dataset.characters = String(block.textContent.length);
      output.append(block);
      while (size > 64000 && output.children.length > 1) {
        const old = output.firstElementChild;
        size -= Number(old.dataset.characters);
        old.remove();
      }
      if (follow) {
        if (mode === 'console') bottom();
        else output.scrollTop = output.scrollHeight;
      }
    }

    viewport.addEventListener('click',event => {
      if (event.target === viewport && !doc.getSelection()?.toString()) focus();
    });
    panel.addEventListener('keydown',event => {
      if ((event.ctrlKey && event.key.toLowerCase() === 'l') || (event.metaKey && event.key.toLowerCase() === 'k')) {
        event.preventDefault(); clear(); focus();
      }
    });
    return {setMode,setPlayback,appendJob,clear,focus};
  }

  globalThis.MarianaPairedConsole = {mount,styledOutput};
})();

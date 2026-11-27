/* Token ranges are UTF-16 offsets, matching HTMLInputElement.selectionStart. */
(() => {
  'use strict';
  const cache = new WeakMap();
  function windowsPath(value) { return /^(?:[A-Za-z]:[\\/]|\\\\)/.test(value); }
  function scan(line) {
    const tokens = [];
    let i = 0;
    while (i < line.length) {
      if (/\s/.test(line[i])) { i++; continue; }
      const start = i;
      let value = '', quote = '', firstQuote = '', literalPath = false;
      while (i < line.length && (quote || !/\s/.test(line[i]))) {
        const c = line[i++];
        if (c === '\\' && i < line.length && !literalPath) {
          const next = line[i];
          if (quote ? (next === quote || next === '\\') : /[\s"']/.test(next)) { value += next; i++; continue; }
        }
        if (quote && c === quote) { quote = ''; continue; }
        if (!quote && (c === '"' || c === "'") && i === start + 1) {
          quote=c; firstQuote=c; literalPath=windowsPath(line.slice(i,i+3)); continue;
        }
        value += c;
      }
      tokens.push({value, start, end:i, quote:firstQuote, closed:!quote});
    }
    return tokens;
  }
  function shellValue(value, quote) {
    if (!quote && value && !/[\s"']/.test(value)) return value;
    if (windowsPath(value)) return '"' + value + '"';
    const wrap = quote || '"';
    return wrap + value.split('\\').join('\\\\').split(wrap).join('\\'+wrap) + wrap;
  }
  function split(path) { return path.trim().split(/\s+/); }
  function argName(value) { return value.replace(/^[<\[]|[>\]?]$/g,'').replace(/\.\.\.$/,''); }
  function slot(word) { return word.startsWith('<') && word.endsWith('>'); }
  function compile(grammar) {
    if (cache.has(grammar)) return cache.get(grammar);
    const routes = [], aliases = new Map();
    for (const row of grammar) {
      if (!row.path) continue;
      for (const alias of row.aliases || []) {
        const a = split(alias), canonical = split(row.path);
        if (a.length === 1 && canonical.length === 1) aliases.set(a[0].toLowerCase(),canonical[0]);
      }
      for (const path of new Set([row.path,...row.aliases || []])) routes.push({words:split(path),row});
    }
    const data = {routes, aliases}; cache.set(grammar,data); return data;
  }
  function near(a,b) {
    a = a.toLowerCase(); b = b.toLowerCase();
    if (a.length < 2 || a.length > 65 || b.length > 65) return 99;
    const longest = Math.max(a.length,b.length), max = longest >= 7 ? 2 : 1;
    if (Math.abs(a.length-b.length) > max) return 99;
    let prior = Array.from({length:b.length+1},(_,i)=>i), priorPrior;
    for (let i=1;i<=a.length;i++) {
      const row = [i];
      for (let j=1;j<=b.length;j++) {
        let distance = Math.min(row[j-1]+1, prior[j]+1, prior[j-1]+(a[i-1]===b[j-1]?0:1));
        if (i>1 && j>1 && a[i-1]===b[j-2] && a[i-2]===b[j-1]) distance = Math.min(distance,priorPrior[j-2]+1);
        row.push(distance);
      }
      priorPrior=prior; prior=row;
    }
    const distance=prior[b.length];
    return distance<=max ? distance : 99;
  }
  function inspect(grammar, before) {
    const {routes, aliases} = compile(grammar);
    const words = before.slice();
    if (words.length && aliases.has(words[0].toLowerCase())) words[0]=aliases.get(words[0].toLowerCase());
    const choices=new Map();
    let free = false, valuedFlag = false, inlineFlags = false;
    function add(value, description, kind) {
      if (typeof value !== 'string' || !value || value.length>300) return;
      const key = value.toLowerCase();
      if (!choices.has(key)) choices.set(key,{label:value,description:description || '',kind});
    }
    for (const {words:path,row} of routes) {
      let i=0, p=0, arg=0, skip=false, pending='';
      const flags = row.flags || [], used = new Set();
      while (i<words.length) {
        const word=words[i++];
        if (p===path.length && flags.includes(word)) {
          used.add(word);
          if (Object.prototype.hasOwnProperty.call(row.flagValues || {},word)) {
            if (i===words.length) { pending=word; break; }
            i++;
          }
          continue;
        }
        if (p<path.length) {
          const key = path[p++];
          if (slot(key)) {
            const vals = row.values?.[argName(key)];
            if (vals?.length && !vals.some(v=>String(v).toLowerCase()===word.toLowerCase())) { skip=true; break; }
          } else if (key.toLowerCase()!==word.toLowerCase()) { skip=true; break; }
        } else {
          const args = row.arguments || [];
          if (arg>=args.length) { skip=true; break; }
          const name=argName(args[arg]), values=row.values?.[name];
          if (values?.length && !values.some(v=>String(v).toLowerCase()===word.toLowerCase())) { skip=true; break; }
          const moreText=arg===args.length-1 && /(^|[-_])(title|surname|genre|query|words|name|text|frequencies-hz)$/.test(name);
          if (!moreText && !args[arg].endsWith('...')) arg++;
        }
      }
      if (skip) continue;
      if (pending) {
        valuedFlag=true;
        const vals=row.flagValues[pending];
        if (!vals.length) free=true;
        vals.forEach(v=>add(String(v),'Value for '+pending,'value'));
        continue;
      }
      if (p<path.length) {
        if (!slot(path[p])) add(path[p],row.description,'command');
        else {
          const name=argName(path[p]), vals=row.values?.[name];
          if (!vals?.length) free=true;
          vals?.forEach(v=>add(String(v),name,'value'));
        }
      } else {
        if (row.inlineFlags) inlineFlags=true;
        const name=argName(row.arguments?.[arg] || '');
        if (name) {
          const vals=row.values?.[name];
          if (!vals?.length) free=true;
          vals?.forEach(v=>add(String(v),name,'value'));
        }
        for (const flag of flags) if (!used.has(flag)) add(flag,row.description,'flag');
      }
    }
    return {choices, free, valuedFlag, inlineFlags, words};
  }
  function rows(token, prefix, state, options, corrections) {
    const all = new Map(state.choices), typed = prefix.toLowerCase();
    if (!corrections && !state.valuedFlag && state.words.length && !prefix.startsWith('-')) {
      for (const pick of options.dynamic?.(state.words,prefix) || []) {
        const value = pick.value;
        if (typeof value==='string' && value && value.length<=300) all.set(value.toLowerCase(),{label:value,description:String(pick.description || ''),kind:'local'});
      }
    }
    if (corrections && (state.choices.has(typed) || (state.free && !prefix.startsWith('--')))) return [];
    const candidates=[];
    for (const [key,item] of all) {
      const guardedFlag=['--force','--confirm','--yes','--overwrite','-y','-f'].includes(key);
      const confirmation=item.kind==='value' && /confirm/i.test(item.description);
      if ((guardedFlag || confirmation) && (corrections || !typed.replace(/^-+/,'') || !key.startsWith(typed))) continue;
      if (prefix.startsWith('-') !== item.label.startsWith('-') && prefix) continue;
      if (!corrections && (key.startsWith(typed) || (item.kind==='local' && String(item.description).toLowerCase().includes(typed)))) {
        candidates.push({...item,score:key===typed?0:key.startsWith(typed)?1:2});
      } else if (corrections && item.kind!=='local' && !/[:/\\@\s]/.test(prefix)) {
        const score=near(typed,key);
        if (score<99) candidates.push({...item,score});
      }
    }
    candidates.sort((a,b)=>a.score-b.score || (a.kind==='flag')-(b.kind==='flag') || a.label.localeCompare(b.label,undefined,{numeric:true}));
    return candidates.slice(0,40).map(item=>({value:shellValue(item.label,token.quote),label:item.label,
      description:corrections ? 'Did you mean '+item.label+'?' : (item.description || (item.kind==='flag' ? 'Option' : '')),
      start:token.start,end:token.end,appendSpace:!token.equalsAfter,correction:corrections}));
  }
  function suggest(line,cursor,grammar,options={}) {
    if (!Array.isArray(grammar) || typeof line!=='string' || line.length>8192) return [];
    const tokens=[];
    for (const token of scan(line)) {
      const equals=token.value.indexOf('=');
      if (token.quote || !token.value.startsWith('--') || equals<3 || !inspect(grammar,tokens.map(t=>t.value)).inlineFlags) {
        tokens.push(token);
      } else {
        // Retain separate replacement ranges on routes that accept --name=value.
        tokens.push({...token,value:token.value.slice(0,equals),end:token.start+equals,equalsAfter:true},
          {...token,value:token.value.slice(equals+1),start:token.start+equals+1});
      }
    }
    const before=[];
    if (options.correctionsOnly) {
      // Correct the first unknown closed-vocabulary token, retaining the surrounding arguments.
      for (const token of tokens) {
        const state=inspect(grammar,before), key=token.value.toLowerCase();
        if (!state.choices.has(key) && !state.free) {
          return rows(token,token.value,state,options,true);
        }
        if (state.free && key.startsWith('--') && !state.choices.has(key)) {
          const flags=rows(token,token.value,state,options,true);
          if (flags.length) return flags;
        }
        before.push(token.value);
      }
      return [];
    }
    const caret=Math.min(line.length,Math.max(0,cursor ?? line.length));
    let active={start:caret,end:caret,value:'',quote:''}, prefix='';
    for (const token of tokens) {
      if (token.start<=caret && token.end>=caret) {
        active=token; prefix=scan(line.slice(token.start,caret))[0]?.value || ''; break;
      }
      if (token.end<caret) before.push(token.value); else break;
    }
    const state=inspect(grammar,before);
    const matches=rows(active,prefix,state,options,false);
    return matches.length ? matches : rows(active,prefix,state,options,true);
  }
  function parse(line, grammar) {
    const tokens=scan(line);
    if (tokens.some(token=>!token.closed)) throw Error('Close the quoted argument before running the command.');
    if (!grammar) return tokens.map(token=>token.value);
    const words=[];
    for (const token of tokens) {
      const state=inspect(grammar,words);
      // Normalize grammar keywords while preserving user queries, paths and IDs.
      const choice=state.choices.get(token.value.toLowerCase());
      words.push(choice && (!state.free || choice.kind==='flag') ? choice.label : token.value);
    }
    return words;
  }
  globalThis.MarianaCommandMatch = {scan,parse,suggest};
})();

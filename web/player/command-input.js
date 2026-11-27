/* Accessible completion selector shared by the portable console and paired native session. */
(() => {
  'use strict';
  function mount({input,list,status,suggest,historyButton}) {
    list.classList.add('command-suggestions'); list.setAttribute('role','listbox');
    input.setAttribute('role','combobox'); input.setAttribute('aria-autocomplete','list');
    input.setAttribute('aria-controls',list.id); input.setAttribute('aria-expanded','false');
    let rows=[], selected=-1, generation=0, wanted=false, cycling=null, composing=false, focused=false;
    // History belongs only to this mounted command field; prompts and paired credentials never enter it.
    let entries=[], offset=0, draft='', historySearch=false;
    function remember(line) {
      if (!line.trim() || line.length>4096 || /[\x00-\x1f\x7f]/.test(line)) return;
      entries=entries.filter(item=>item!==line);
      entries.push(line);
      if (entries.length>100) entries.shift();
      offset=0; draft=''; dismiss();
    }
    function forget() { entries=[]; offset=0; draft=''; dismiss(); }
    function recall(delta) {
      if (!entries.length) return false;
      if (!offset) draft=input.value;
      offset=Math.max(0,Math.min(entries.length,offset+delta));
      dismiss();
      input.value=offset ? entries[entries.length-offset] : draft;
      input.setSelectionRange?.(input.value.length,input.value.length);
      return true;
    }
    function historyMatches() {
      generation++;
      const words=input.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
      const matches=entries.slice().reverse().filter(line=>words.every(w=>line.toLowerCase().includes(w)))
        .slice(0,40).map(line=>({start:0,end:input.value.length,value:line,label:line}));
      draw(matches); wanted=true;
      status.textContent=matches.length ? 'Command history: '+matches.length+'. Enter edits the selection.' : 'No matching command history.';
      if (matches.length) highlight(0);
      else {
        const message=document.createElement('li');
        message.setAttribute('role','presentation');
        message.textContent=entries.length ? 'No matching commands.' : 'Commands you run in this tab will appear here.';
        list.append(message); list.hidden=false; input.setAttribute('aria-expanded','true');
      }
    }
    function openHistory() { cycling=null; historySearch=true; input.focus(); historyMatches(); }
    historyButton?.addEventListener('click',openHistory);
    function hide() {
      rows=[]; selected=-1; list.hidden=true; list.replaceChildren();
      input.setAttribute('aria-expanded','false'); input.removeAttribute('aria-activedescendant'); status.textContent='';
    }
    function dismiss() { generation++; wanted=false; cycling=null; historySearch=false; hide(); }
    function highlight(index) {
      selected=index;
      Array.from(list.children).forEach((option,i)=>option.setAttribute('aria-selected',String(i===index)));
      const option=list.children[index];
      if (option) { input.setAttribute('aria-activedescendant',option.id); option.scrollIntoView?.({block:'nearest'}); }
      else input.removeAttribute('aria-activedescendant');
    }
    function draw(matches) {
      hide(); rows=matches;
      if (!rows.length) return;
      for (const [index,pick] of rows.entries()) {
        const option=document.createElement('li'); option.id=list.id+'-option-'+index;
        option.setAttribute('role','option'); option.setAttribute('aria-selected','false'); option.dataset.index=String(index);
        const name=document.createElement('strong'); name.textContent=pick.label || pick.value; option.append(name);
        if (pick.description) { const info=document.createElement('span'); info.textContent=pick.description; option.append(info); }
        list.append(option);
      }
      list.hidden=false; input.setAttribute('aria-expanded','true');
      status.textContent=(rows[0].correction ? 'Possible corrections: ' : 'Suggestions: ') + rows.length + '.';
    }
    async function query(correctionsOnly=false) {
      const version=++generation, line=input.value, cursor=input.selectionStart ?? line.length;
      let matches;
      try { matches=await suggest({line,cursor,correctionsOnly}); } catch { matches=[]; }
      if (version!==generation || input.value!==line) return {stale:true,matches:[]};
      const valid=Array.isArray(matches) ? matches.filter(p=>p && typeof p.value==='string' && p.value.length &&
        Number.isInteger(p.start) && Number.isInteger(p.end) && p.start>=0 && p.end>=p.start && p.end<=line.length) : [];
      return {stale:false,matches:valid.slice(0,40)};
    }
    async function refresh(force=false) {
      if (composing || (!force && !input.value.trim())) { dismiss(); return []; }
      const result=await query(false);
      if (!result.stale && !composing) { wanted=result.matches.length>0; draw(result.matches); }
      return result.matches;
    }
    async function review() {
      if (!input.value.trim()) { dismiss(); return false; }
      const result=await query(true);
      if (result.stale) return true;
      cycling=null;
      if (!result.matches.length) { dismiss(); return false; }
      wanted=true; draw(result.matches); input.focus(); return true;
    }
    function accept(index,base,keep=false) {
      const pick=rows[index]; if (!pick) return false;
      const tail=base.slice(pick.end);
      const add=pick.appendSpace && !/^\s/.test(tail) ? ' ' : '';
      input.value=base.slice(0,pick.start)+pick.value+add+tail;
      const next=pick.start+pick.value.length+add.length+(!add && pick.appendSpace && /^\s/.test(tail) ? 1 : 0);
      input.focus(); input.setSelectionRange?.(next,next);
      if (keep) highlight(index); else dismiss();
      return true;
    }
    const move=(index,dir,count)=>(index+dir+count)%count;
    async function keydown(event) {
      if (composing || event.isComposing || event.keyCode===229) return;
      if (event.key==='Escape') { if (wanted || rows.length) { event.preventDefault(); event.stopPropagation(); dismiss(); } return; }
      if (event.ctrlKey && !event.altKey && !event.metaKey && event.key.toLowerCase()==='r') {
        event.preventDefault(); openHistory(); return;
      }
      if (event.altKey && !event.ctrlKey && !event.metaKey && ['ArrowUp','ArrowDown'].includes(event.key)) {
        if (recall(event.key==='ArrowUp'?1:-1)) event.preventDefault();
        return;
      }
      if (event.key===' ' && event.ctrlKey) { event.preventDefault(); cycling=null; historySearch=false; await refresh(true); return; }
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key==='Tab') {
        if (!rows.length) return;
        event.preventDefault();
        const dir=event.shiftKey ? -1 : 1;
        if (!cycling) cycling={base:input.value,index:selected>=0 ? selected : dir===1 ? 0 : rows.length-1};
        else cycling.index=move(cycling.index,dir,rows.length);
        accept(cycling.index,cycling.base,true); return;
      }
      if (event.key==='ArrowDown' || event.key==='ArrowUp') {
        if (!rows.length && !historySearch && recall(event.key==='ArrowUp'?1:-1)) { event.preventDefault(); return; }
        if (!rows.length && (historySearch || !input.value.trim())) return;
        event.preventDefault();
        if (!rows.length) await refresh(true);
        if (!rows.length) return;
        const dir=event.key==='ArrowDown' ? 1 : -1;
        highlight(selected<0 ? (dir===1?0:rows.length-1) : move(selected,dir,rows.length)); return;
      }
      if (event.key==='Enter' && historySearch && !rows.length) { event.preventDefault(); return; }
      if (event.key==='Enter' && selected>=0 && !cycling) {
        event.preventDefault(); accept(selected,input.value); return;
      }
      if (event.key==='Enter' && cycling) { dismiss(); return; }
      if (['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
        cycling=null; setTimeout(()=>{ if (focused && !historySearch) void refresh(); },0);
      }
    }
    input.addEventListener('input',()=>{
      cycling=null; offset=0;
      if (!composing) { if (historySearch) historyMatches(); else void refresh(); }
    });
    input.addEventListener('keydown',keydown);
    input.addEventListener('focus',()=>{focused=true;});
    input.addEventListener('blur',()=>{focused=false; dismiss();});
    input.addEventListener('click',()=>{cycling=null; if (input.value.trim() && !historySearch) void refresh();});
    input.addEventListener('compositionstart',()=>{composing=true; dismiss();});
    input.addEventListener('compositionend',()=>{composing=false; void refresh();});
    list.addEventListener('pointerdown',event=>{ if (event.target.closest('[role=option]')) event.preventDefault(); });
    list.addEventListener('click',event=>{
      const option=event.target.closest('[role=option]'); if (option) accept(Number(option.dataset.index),cycling?.base ?? input.value);
    });
    return {dismiss,refresh,review,remember,forget};
  }
  globalThis.MarianaCommandInput={mount};
})();

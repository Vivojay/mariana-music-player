import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('../web/player/command-input.js',import.meta.url),'utf8');
class Node {
  attrs=new Map(); listeners=new Map(); dataset={}; children=[]; classList={add(){}};
  textContent=''; value=''; hidden=false;
  addEventListener(name,fn){this.listeners.set(name,fn);}
  setAttribute(k,v){this.attrs.set(k,v);}
  removeAttribute(k){this.attrs.delete(k);}
  append(child){this.children.push(child);}
  replaceChildren(){this.children=[];}
  closest(){return this;}
  focus(){}
  scrollIntoView(){}
  setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b;}
  async emit(name,payload={}){
    const event={target:this,preventDefault(){this.prevented=true;},stopPropagation(){},...payload};
    await this.listeners.get(name)?.(event); return event;
  }
}
function setup(suggest) {
 const ctx={document:{createElement:()=>new Node()},setTimeout}; vm.runInNewContext(source,ctx);
 const input=new Node(),list=new Node(),status=new Node();list.id='test';
 const historyButton=new Node();
 const api=ctx.MarianaCommandInput.mount({input,list,status,suggest,historyButton});
 return {input,list,status,api,historyButton};
}
const picks=(line,correction=false)=>['pause','play'].map(label=>({start:0,end:line.trim().length,label,value:label,appendSpace:true,correction}));
test('Tab and Shift+Tab cycle original span, arrows and touch accept without dispatch',async()=>{
 const {input,list,api}=setup(({line})=>picks(line));
 input.value='p';input.selectionStart=1;await api.refresh();
 assert.equal(input.attrs.get('aria-expanded'),'true');
 assert((await input.emit('keydown',{key:'Tab'})).prevented);assert.equal(input.value,'pause ');
 await input.emit('keydown',{key:'Tab'});assert.equal(input.value,'play ');
 await input.emit('keydown',{key:'Tab',shiftKey:true});assert.equal(input.value,'pause ');
 await input.emit('keydown',{key:'Escape'});assert(list.hidden);
 assert(!(await input.emit('keydown',{key:'Tab'})).prevented);
 input.value='p';await api.refresh();await input.emit('keydown',{key:'ArrowDown'});
 assert.equal(input.attrs.get('aria-activedescendant'),'test-option-0');
 assert((await input.emit('keydown',{key:'Enter'})).prevented);assert.equal(input.value,'pause ');assert(list.hidden);
 input.value='p';await api.refresh();
 await list.emit('click',{target:list.children[1]});assert.equal(input.value,'play ');
 assert.equal(list.hidden,true);
});
test('review retains the entire original line and pointer acceptance preserves its suffix',async()=>{
 const {input,list,api}=setup(({correctionsOnly})=>correctionsOnly?[{start:3,end:6,value:'cue',label:'cue',appendSpace:true,correction:true}]:[]);
 input.value='dj ceu B set 1';
 assert.equal(await api.review(),true);assert.equal(input.value,'dj ceu B set 1');
 await list.emit('click',{target:list.children[0]});assert.equal(input.value,'dj cue B set 1');assert.equal(input.selectionStart,7);
});
test('blur and IME dismiss any pending rows; older asynchronous results never replace newer ones',async()=>{
 let resolve;
 const {input,list,api}=setup(({line})=>line==='x'?new Promise(done=>{resolve=done;}):picks(line));
 input.value='x';const slow=api.refresh();
 input.value='p';await api.refresh();resolve([]);await slow;assert.equal(list.children.length,2);
 await input.emit('compositionstart');assert(list.hidden);
 assert(!(await input.emit('keydown',{key:'Tab',isComposing:true})).prevented);
 input.value='p';await input.emit('compositionend');await Promise.resolve();
 assert(!list.hidden);
 input.value='x';const stale=api.review();await input.emit('blur');resolve([]);assert.equal(await stale,true);assert(list.hidden);
});
test('submitted commands support draft recall and searchable history without sending it',async()=>{
  const {api,input,list,historyButton}=setup(()=>[]);
  api.remember('seek 10'); api.remember('play'); api.remember('seek 10');
  input.value='my draft';
  assert((await input.emit('keydown',{key:'ArrowUp'})).prevented); assert.equal(input.value,'seek 10');
  await input.emit('keydown',{key:'ArrowUp'}); assert.equal(input.value,'play');
  await input.emit('keydown',{key:'ArrowDown'}); await input.emit('keydown',{key:'ArrowDown'}); assert.equal(input.value,'my draft');
  input.value='seek';
  assert((await input.emit('keydown',{key:'r',ctrlKey:true})).prevented);
  assert.equal(list.children.length,1);
  assert((await input.emit('keydown',{key:'Enter'})).prevented); assert.equal(input.value,'seek 10');
  assert(list.hidden);
  input.value='pl';await historyButton.emit('click');assert.equal(list.children.length,1);
  await list.emit('click',{target:list.children[0]});assert.equal(input.value,'play');
  api.forget();input.value='';
  assert(!(await input.emit('keydown',{key:'ArrowUp'})).prevented);
});

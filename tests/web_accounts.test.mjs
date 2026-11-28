import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const providers=JSON.parse(readFileSync(new URL('../mariana/connection_providers.json',import.meta.url)));
const source=readFileSync(new URL('../web/player/accounts.js',import.meta.url),'utf8');
class Element {
  children=[]; value=''; textContent='';
  constructor(tag){this.tag=tag;}
  append(...items){this.children.push(...items);if(this.tag==='select'&&!this.value)this.value=items[0].value;}
  replaceChildren(){this.children=[];}
  focus(){} scrollIntoView(){}
}
function storage(){
  const map=new Map();
  return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k),map};
}
function app({href='https://player.test/music/',client='',snap='',session=storage(),windowFeatures={},fetch=()=>{throw Error('unexpected network')}}={}){
  const elements=new Map(), local=storage();
  const document={createElement:t=>new Element(t),getElementById:id=>{
    if(!elements.has(id))elements.set(id,new Element(id==='account-provider'?'select':'div'));
    return elements.get(id);
  }};
  const location=new URL(href); let redirected='';
  location.assign=target=>{redirected=target};
  const window={MarianaAccountConfig:{providers,spotifyClientId:client,snapchatClientId:snap},isSecureContext:true,...windowFeatures};
  const history={replaceState(_a,_b,url){location.href=url;}};
  vm.runInNewContext(source,{window,document,location,history,fetch,crypto:webcrypto,TextEncoder,
    URL,URLSearchParams,Uint8Array,btoa,localStorage:local,sessionStorage:session});
  return {window,session,local,elements,location,redirected:()=>redirected,run:args=>window.MarianaAccounts.command(args)};
}

test('public links work on the web without configuration and never assert ownership',async()=>{
  const player=app();
  await player.run(['link','bandcamp','summer']);
  assert.equal(player.local.getItem('mariana.profile.v1.bandcamp'),'summer');
  assert.equal(player.elements.get('account-detail').children[0].textContent,'Public profile links available.');
  await assert.rejects(player.run(['link','bandcamp','//foreign.test']),/valid/);
  await assert.rejects(player.run(['connect','bandcamp']),/unavailable/);
  await player.run(['unlink','bandcamp']);
  assert.equal(player.local.getItem('mariana.profile.v1.bandcamp'),null);
});

test('browser Spotify consent uses S256, exact redirect, validates state and verifies before showing an identity',async()=>{
  const client='public-id', first=app({client});
  await first.run(['connect','spotify']);
  const auth=new URL(first.redirected()), state=auth.searchParams.get('state');
  assert.equal(auth.origin,'https://accounts.spotify.com');
  assert.equal(auth.searchParams.get('code_challenge_method'),'S256');
  assert.equal(auth.searchParams.get('redirect_uri'),'https://player.test/music/');
  const job=JSON.parse(first.session.getItem('mariana.spotify.consent.v1'));
  const challenge=Buffer.from(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(job.verifier))).toString('base64url');
  assert.equal(auth.searchParams.get('code_challenge'),challenge);
  const calls=[];
  const second=app({client,session:first.session,href:'https://player.test/music/?code=secret-code&state='+state,
    fetch:async(url,init)=>{
      calls.push([url,init]);
      if(url.endsWith('/token')){assert.equal(init.body.get('code_verifier'),job.verifier);return Response.json({access_token:'fixture-token',expires_in:3600});}
      assert.equal(init.headers.Authorization,'Bearer fixture-token');
      if(url.endsWith('/me'))return Response.json({account_id:'id',display_name:'Verified name'});
      return Response.json({items:[{name:'Road music'}]});
    }});
  await new Promise(resolve=>setTimeout(resolve,20));
  assert.match(second.elements.get('account-detail').children[0].textContent,/Verified name/);
  assert.equal(second.location.search,'');
  assert.equal(second.session.getItem('mariana.spotify.consent.v1'),null);
  assert.equal(await second.run(['activity','spotify']),'Road music');
  assert.equal(second.local.map.size,0);
  await second.run(['disconnect','spotify']);
  assert.doesNotMatch(second.elements.get('account-detail').children[0].textContent,/Verified name/);
  const stale=storage();stale.setItem('mariana.spotify.consent.v1',JSON.stringify(job));
  const wrong=app({client,session:stale,href:'https://player.test/music/?code=ignored&state=other'});
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.match(wrong.elements.get('account-feedback').textContent,/unmatched/);
});

test('Snapchat verifies the external ID through Login Kit before displaying a signed-in profile',async()=>{
  const snap='snap-public-client', first=app({snap});
  await first.run(['connect','snapchat']);
  const url = new URL(first.redirected());
  assert.equal(url.origin,'https://accounts.snapchat.com');
  assert.match(url.searchParams.get('scope'),/user.external_id/);
  const second = app({snap,session:first.session,href:'https://player.test/music/?code=snapcode&state='+url.searchParams.get('state'),
    fetch:async(target,request)=>{
      if(target.endsWith('/token')) return Response.json({access_token:'snap-fixture',expires_in:3600});
      assert.equal(new URL(target).origin,'https://kit.snapchat.com');
      assert.equal(request.headers.Authorization,'Bearer snap-fixture');
      return Response.json({data:{me:{externalId:'stable-id',displayName:'Stage name'}}});
    }});
  await new Promise(resolve=>setTimeout(resolve,12));
  assert.match(second.elements.get('account-detail').children[0].textContent,/Stage name/);
  await second.run(['disconnect','snapchat']);
  assert.doesNotMatch(second.elements.get('account-detail').children[0].textContent,/Stage name/);
});

test('an expired Spotify grant must keep its verified subject and cannot return activity after disconnect',async()=>{
  async function connect(refreshHandler,who){
    const client='public-id',start=app({client}); await start.run(['connect','spotify']);
    const state=new URL(start.redirected()).searchParams.get('state');
    const player=app({client,session:start.session,href:'https://player.test/music/?code=test&state='+state,
      fetch:async(url,options)=>{
        if(url.endsWith('/token')){
          if(options.body.get('grant_type')==='refresh_token')return refreshHandler();
          return Response.json({access_token:'first',refresh_token:'refresh',expires_in:1});
        }
        if(url.endsWith('/me'))return Response.json({account_id:options.headers.Authorization==='Bearer first'?'original':who,id:'public'});
        throw Error('unexpected activity read');
      }});
    await new Promise(resolve=>setTimeout(resolve,12));return player;
  }
  const rotated=()=>Response.json({access_token:'second',refresh_token:'next',expires_in:3600});
  const mismatch=await connect(rotated,'different');
  await assert.rejects(mismatch.run(['activity','spotify']),/different account/);
  assert.doesNotMatch(mismatch.elements.get('account-detail').children[0].textContent,/Signed in/);
  let release;
  const pending=await connect(()=>new Promise(resolve=>{release=resolve;}),'original');
  const activity=pending.run(['activity','spotify']);
  await pending.run(['disconnect','spotify']); release(rotated());
  await assert.rejects(activity,/session changed/);
});

test('authorization in a second window completes in the playing tab without navigating it',async()=>{
  let authURL;let closed=false;
  const popupSession=storage();
  const popup={opener:true,sessionStorage:popupSession,location:{replace(url){authURL=new URL(url);}},close(){closed=true;}};
  const first=app({client:'public',windowFeatures:{open:()=>popup,BroadcastChannel,setTimeout,clearTimeout},fetch:async(url)=>{
    if(url.endsWith('/token'))return Response.json({access_token:'test',expires_in:3600});
    return Response.json({account_id:'same',display_name:'Stayed here'});
  }});
  await first.run(['connect','spotify']);
  assert.equal(first.redirected(),'');assert.equal(popup.opener,null);
  app({client:'public',session:popupSession,href:'https://player.test/music/?code=one-time&state='+authURL.searchParams.get('state'),
    windowFeatures:{BroadcastChannel,close(){closed=true;}}});
  for(let attempt=0;attempt<50 && !first.elements.get('account-detail').children[0].textContent.includes('Stayed here');attempt++){
    await new Promise(resolve=>setTimeout(resolve,10));
  }
  assert.equal(closed,true);
  assert.equal(first.location.href,'https://player.test/music/');
  assert.match(first.elements.get('account-detail').children[0].textContent,/Stayed here/);
});

test('named browser listeners keep private native sessions out of portable setup', async () => {
  let requests = 0;
  const player = app({href:'http://127.0.0.1:8767/',
    windowFeatures:{MarianaProfiles:{current:'studio', key:value=>'fixture:studio:'+value}},
    fetch:()=>{ requests++; throw Error('unexpected host request'); }});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(requests, 0);
  await player.run(['link','bandcamp','listener']);
  assert.equal(player.local.getItem('mariana.profile.v1.bandcamp'), null);
  assert.equal(player.local.getItem('fixture:studio:mariana.profile.v1.bandcamp'), 'listener');
  assert.match(await player.run(['setup']), /Choose a service/);
  player.elements.set('karaoke-demo', new Element('button'));
  assert.match(await player.run(['setup','karaoke']), /duet/);
  const form = new Element('form');
  let focused = false;
  form.elements = {catalog:{value:''},term:{focus(){focused = true;}}};
  player.elements.set('catalog-search', form);
  assert.match(await player.run(['setup','audiobooks']), /public catalog/);
  assert.equal(form.elements.catalog.value, 'book');
  assert.equal(focused,true);
});

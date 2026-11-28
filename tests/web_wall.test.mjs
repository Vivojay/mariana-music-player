import assert from 'node:assert/strict';
import test from 'node:test';
import '../web/player/wall.js';

const {post, snapshot, encode, decode} = globalThis.MarianaWall;
const owner = '50bff178-dc69-41cb-8087-a50327292bef';
const item = {id:'be0e00d8-06ee-4cf1-8d11-cd40e7648548',kind:'review',artist:'Nia',title:'Glass',body:'Shifting harmonies',stars:4,created:1700000000};
const desktop = {format:'mariana.wall.v1',id:owner,name:'Nia fan',posts:[item]};

test('snapshot interchange includes only approved posts and profile fields', () => {
  const source = {...desktop, queue:[{uri:'private'}], history:['private'], posts:[{...item, secret:'private'}]};
  assert.deepEqual(decode(encode(source)),desktop);
  assert.equal(encode(source).includes('private'),false);
  const listen = {...item,kind:'listen',body:'',stars:0};
  assert.deepEqual(post(listen),listen);
});
test('invalid snapshots are rejected as a unit', () => {
  for (const bad of [{...desktop,format:'other'}, {...desktop,id:'bad'}, {...desktop,posts:[item,item]},
    {...desktop,posts:[{...item,stars:1.5}]},{...desktop,name:'a\u202Eb'}, {...desktop,posts:[{...item,created:-1}]}]) {
    assert.throws(() => snapshot(bad));
  }
  assert.throws(() => decode(' '.repeat(8 * 1024 * 1024 + 1)));
});
test('all four public post types use canonical desktop fields', () => {
  for (const kind of ['track','album','review','take']) {
    const entry = {...item,kind,title:kind === 'take' ? '' : item.title,stars:kind === 'review' ? 5 : 0,body:['review','take'].includes(kind) ? 'Lovely' : ''};
    assert.deepEqual(decode(encode({...desktop,posts:[entry]})).posts,[entry]);
  }
});

test('PNG card text and layout retain the selected post, including long unbroken titles', () => {
  const labels = [];
  let ctx;
  const canvas = { getContext:() => ctx };
  ctx = {font:'',measureText:s => ({width:[...s].length * 22}),fillText:(value,x,y) => labels.push([value,x,y]),
    fillRect(){},save(){},beginPath(){},rect(){},clip(){},arc(){},fill(){},stroke(){},restore(){},
    createLinearGradient:() => ({addColorStop(){}})};
  const long = {...item,title:'a'.repeat(240),body:'b'.repeat(600),privateHistory:'private',stars:5};
  const colors = {background:'#101010',panel:'#151515',accent:'#aaaaaa',text:'#eeeeee',muted:'#999999',glow:'#222222'};
  const copy = MarianaWall.drawCard(canvas,long,'Listener',colors);
  assert.equal(canvas.width,1080);
  assert(canvas.height>1080);
  assert(copy.includes(long.title) && copy.includes(long.body) && copy.includes('5 / 5 stars'));
  assert(!copy.includes('private'));
  assert(labels.every(([,x,y]) => x>=0 && x<canvas.width && y>=0 && y<canvas.height));
  assert.equal(labels.map(([l]) => l).filter(l => /^a+$/.test(l)).join(''),long.title);
  assert.equal(labels.map(([l]) => l).filter(l => /^b+$/.test(l)).join(''),long.body);
});

import { expect, test } from '@playwright/test';

function tone(name:string, side:number, hz:number) {
  const rate=16000, size=rate*12*4, buffer=Buffer.alloc(44+size);
  buffer.write('RIFF'); buffer.writeUInt32LE(size+36,4); buffer.write('WAVEfmt ',8);
  buffer.writeUInt32LE(16,16); buffer.writeUInt16LE(1,20); buffer.writeUInt16LE(2,22);
  buffer.writeUInt32LE(rate,24); buffer.writeUInt32LE(rate*4,28); buffer.writeUInt16LE(4,32);
  buffer.writeUInt16LE(16,34); buffer.write('data',36); buffer.writeUInt32LE(size,40);
  for(let i=0;i<size/4;i++) buffer.writeInt16LE(Math.round(12000*Math.sin(i*2*Math.PI*hz/rate)),44+i*4+side*2);
  return {name,mimeType:'audio/wav',buffer};
}

test('Console and Flow record the same stereo master across a live crossfade', async ({page}) => {
  await page.goto('/');
  const cmd=async (line:string) => { await page.locator('#cmd').fill(line); await page.locator('#command button').click(); };
  await cmd('dj');
  const [a,b]=await page.locator('.dj-deck').all();
  await a.locator('input[type=file]').setInputFiles(tone('left.wav',0,300));
  await expect(a.locator('h3')).toHaveText('left.wav');
  await b.locator('input[type=file]').setInputFiles(tone('right.wav',1,600));
  await expect(b.locator('h3')).toHaveText('right.wav');
  await cmd('dj crossfade 0');
  await cmd('dj play A'); await expect(a.locator('[data-ui=play]')).toHaveText('Pause');
  await cmd('dj play B'); await expect(b.locator('[data-ui=play]')).toHaveText('Pause');
  await page.locator('nav [data-mode=flow]').click();
  await page.getByRole('button',{name:'Studio',exact:true}).click();
  await page.locator('#dj-record').click();
  await expect(page.locator('#dj-record-time')).toContainText('0:01');
  await page.locator('#dj-cross').focus(); await page.locator('#dj-cross').press('End');
  await expect(page.locator('#dj-record-time')).toContainText('0:03');
  await page.locator('#dj-record').click();
  await expect(page.locator('#dj-save')).toBeVisible();
  const [firstL,firstR,lastL,lastR] = await page.locator('#dj-save').evaluate(async (el:HTMLAnchorElement) => {
    const v = new DataView(await (await fetch(el.href)).arrayBuffer());
    const rate=v.getUint32(24,true), frames=v.getUint32(40,true)/4;
    const rms=(frame:number,ch:number) => {
      let sum=0; for(let i=0;i<rate/5;i++) sum+=v.getInt16(44+4*(i+frame)+ch*2,true)**2; return Math.sqrt(sum/(rate/5));
    };
    return [rms(rate/4,0),rms(rate/4,1),rms(frames-rate/2,0),rms(frames-rate/2,1)];
  });
  expect(firstL).toBeGreaterThan(1000); expect(firstR).toBeLessThan(firstL/50);
  expect(lastR).toBeGreaterThan(1000); expect(lastL).toBeLessThan(lastR/50);
});

test('Flow loads library tracks onto aligned scopes and recalls visual hot cues', async ({page}) => {
  await page.goto('/?view=flow');
  await page.locator('#files').setInputFiles([tone('Left fixture.wav',0,300),tone('Right fixture.wav',1,600)]);
  await page.getByRole('button',{name:'Studio',exact:true}).click();
  await page.locator('#dj-open').click();
  const first = page.locator('#dj-crate-list li').filter({hasText:'Left fixture'});
  await first.getByRole('button',{name:/into deck A/}).click();
  const second = page.locator('#dj-crate-list li').filter({hasText:'Right fixture'});
  await second.getByRole('button',{name:/into deck B/}).click();
  const a = page.locator('.dj-deck[data-deck=A]');
  await expect(a.locator('h3')).toHaveText('Left fixture.wav');
  await expect(page.locator('.dj-deck[data-deck=B] h3')).toHaveText('Right fixture.wav');
  const scopes = page.locator('#dj-waveforms canvas');
  await expect(scopes).toHaveCount(2);
  await expect.poll(() => scopes.evaluateAll(canvases => canvases.map(node => {
    const canvas = node as HTMLCanvasElement;
    return canvas.getContext('2d')!.getImageData(0,0,canvas.width,canvas.height).data.some((channel,index) =>
      index % 4 === 0 && (channel === 169 || channel === 239));
  }))).toEqual([true,true]);
  const overview = a.locator('canvas');
  const size = await overview.boundingBox();
  if (!size) throw new Error('The deck overview is missing');
  await overview.click({position:{x:size.width/2,y:size.height/2}});
  await a.getByRole('button',{name:'Set cue 1'}).click();
  await expect(a.getByRole('button',{name:/Jump to cue 1/})).toHaveAttribute('data-cued','true');
  await overview.click({position:{x:6,y:size.height/2}});
  await a.getByRole('button',{name:/Jump to cue 1/}).click();
  await expect.poll(async () => Math.abs(Number(await a.locator('[data-ui=seek]').inputValue()) - 6)).toBeLessThan(0.08);
  await a.getByRole('button',{name:'Clear cue 1'}).click();
  await expect(a.getByRole('button',{name:'Set cue 1'})).toBeEnabled();
});

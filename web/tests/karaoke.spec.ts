import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

test('practice duet, low confidence and persisted sheet across Console and Flow', async ({ page }) => {
  await page.goto('/');
  await page.locator('#karaoke-demo').click();
  await expect(page.locator('#karaoke-status')).toContainText('Available · 100%');
  if (await page.locator('#play').innerText() === 'Pause') await page.locator('#play').click();
  await page.locator('#cmd').fill('seek 3.6'); await page.locator('#command button').click();
  await expect(page.locator('.karaoke-lane')).toHaveCount(2);
  await expect(page.locator('.karaoke-word[data-state=singing]')).toHaveCount(2);
  await page.selectOption('#karaoke-part', {label:'Tenor'});
  await expect(page.locator('.karaoke-singer')).toHaveText('Tenor');
  await page.locator('nav [data-mode=flow]').click();
  await page.locator('#workspace-navigation [data-area=studio]').click();
  await expect(page.locator('#karaoke-stage')).toBeVisible();
  const file = JSON.parse(readFileSync(resolve('res/karaoke/practice-duet.json'), 'utf8'));
  file.confidence = .899;
  await page.locator('#karaoke-file').setInputFiles({name:'weak.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(file))});
  await expect(page.locator('#karaoke-status')).toContainText('below the required 90%');
  await expect(page.locator('#karaoke-stage')).toBeHidden();
  await page.locator('#karaoke-book summary').click();
  await expect(page.locator('#karaoke-book-lines')).toContainText('Alto');
  await page.reload();
  await expect(page.locator('#karaoke-status')).toContainText('below the required 90%');
});

test('TTML media-clock comparison accepts two differing word alignments on both voices', async ({page}) => {
  await page.goto('/'); await page.locator('#karaoke-demo').click();
  await expect(page.locator('#karaoke-status')).toContainText('Available');
  const make = (first:number) => Buffer.from(`<tt xmlns="http://www.w3.org/ns/ttml" xmlns:m="http://www.w3.org/ns/ttml#metadata"><body dur="6s"><div><p m:agent="Alto" begin="0s" end="2s"><span begin="${first}ms" end="2s">Ah</span></p><p m:agent="Tenor" begin="0s" end="2s"><span begin="1s" end="2s">Oh</span></p><p begin="2s" end="6s" m:role="x-instrumental"/></div></body></tt>`);
  await page.locator('#karaoke-ttml').setInputFiles([990,1000].map(n => ({name:n+'.ttml',mimeType:'application/ttml+xml',buffer:make(n)})));
  await expect(page.locator('#karaoke-status')).toContainText('99%');
  await expect(page.locator('#karaoke-part option')).toHaveCount(3);
});

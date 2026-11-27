import { expect, test } from '@playwright/test';

test('Flow prepares real audio from a paused track and offers the prepared file to the share sheet', async ({page}) => {
  await page.addInitScript(() => {
    Object.defineProperties(navigator, {
      canShare: { configurable:true, value:({files}: ShareData) => files?.[0]?.type === 'audio/wav' },
      share: { configurable:true, value:async ({files}: ShareData) => {
        const data = new DataView(await files![0].arrayBuffer());
        sessionStorage.setItem('clipFrames', String(data.getUint32(40,true) / data.getUint16(32,true)));
      }},
    });
  });
  await page.goto('/');
  await page.locator('#cmd').fill('tone sine 330 --seconds 6');
  await page.locator('#command button').click();
  await expect(page.locator('#duration')).toHaveText('0:06');
  await page.locator('#cmd').fill('pause'); await page.locator('#command button').click();
  await page.locator('nav [data-mode=flow]').click();
  await page.locator('#clip-open').click();
  await page.locator('#clip-start').fill('0:01.250');
  await page.locator('#clip-end').fill('0:02.000');
  await page.locator('#clip-build').click();
  await expect(page.locator('#clip-download')).toHaveAttribute('download', /1\.25-2\.wav/);
  await page.locator('#clip-share').click();
  expect(await page.evaluate(() => sessionStorage.getItem('clipFrames'))).toBe('36000');
  await expect(page.locator('#play')).toHaveText('Play');
  await page.locator('#clip-end').fill('0:03'); await expect(page.locator('#clip-result')).toBeHidden();
});

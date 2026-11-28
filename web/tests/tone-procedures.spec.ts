import { expect, test } from '@playwright/test';

test('factory score enters the transport, saved work survives reload and FLOW opens playable keys', async ({page}) => {
  await page.goto('/');
  const command = async (line: string) => {
    await page.locator('#cmd').fill(line);
    await page.locator('#command button').click();
  };
  await command('tone procedure play twinkle');
  await expect(page.locator('#queue')).toContainText('Twinkle, Twinkle, Little Star');
  await expect(page.locator('#duration')).toHaveText('0:28');
  await command('tone procedure save pwa-score 120 @glass C4+E4+G4:2 R @choir A3:3 --chorus 25');
  await expect(page.locator('#transcript')).toContainText('Saved pwa-score.');
  await page.reload();
  await command('tone procedure play pwa-score');
  await expect(page.locator('#queue')).toContainText('pwa-score');
  await expect(page.locator('#duration')).toHaveText('0:01');
  await page.locator('nav [data-mode=flow]').click();
  await page.locator('#flow-command').click();
  await command('tone keys glass');
  const keys = page.getByRole('dialog', {name:'Playable synthesizer'});
  await expect(keys).toBeVisible();
  await page.keyboard.down('a');
  await page.keyboard.down('d');
  await expect(keys.getByRole('button', {pressed:true})).toHaveCount(2);
  await page.keyboard.up('d');
  await page.keyboard.up('a');
  await expect(keys.getByRole('button', {pressed:true})).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(keys).toHaveCount(0);
});

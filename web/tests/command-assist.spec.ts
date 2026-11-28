import { expect, test } from '@playwright/test';

test('Flow command palette completes commands and reviews a typo before running',async({page})=>{
  await page.goto('/?view=flow');
  const input=page.locator('#cmd'), list=page.locator('#cmd-suggestions');
  await page.locator('#flow-command').click();
  await expect(input).toBeFocused();
  await input.fill('dj cue A s'); await expect(list.getByRole('option').first()).toContainText('set');
  await input.press('Tab'); await expect(input).toHaveValue('dj cue A set ');
  await input.fill('dj sttaus'); await page.locator('#command button').click();
  await expect(input).toHaveValue('dj sttaus'); await expect(list.getByRole('option').first()).toContainText('status');
  await expect(page.locator('#transcript')).not.toContainText('› dj sttaus');
  await list.getByRole('option').first().click(); await expect(input).toHaveValue('dj status ');
  await expect(page.locator('#transcript')).not.toContainText('› dj status');
  await input.press('Enter'); await expect(page.locator('#transcript')).toContainText('Crossfader');
  await input.fill('lv sea'); await input.press('ArrowDown'); await input.press('Enter');
  await expect(input).toHaveValue('lv search '); await expect(page.locator('#transcript')).not.toContainText('› lv search');
  await input.fill('tone sweep 220 440 --curve=l'); await expect(list.getByRole('option')).toHaveCount(2);
  await input.press('Tab'); await input.press('Shift+Tab'); await expect(input).toHaveValue('tone sweep 220 440 --curve=log ');
  await input.press('Escape'); await expect(list).toBeHidden();
  await input.press('Escape'); await expect(input).toBeHidden();
});

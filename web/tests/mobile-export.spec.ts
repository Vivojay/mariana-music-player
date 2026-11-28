import { expect, test } from '@playwright/test';

for (const canShareFiles of [true, false]) {
  test('native wall export via ' + (canShareFiles ? 'Share' : 'Copy'), async ({ page }) => {
    await page.addInitScript((supportsFiles: boolean) => {
      Object.assign(window, { MarianaNativeShell: 'ios' });
      Object.defineProperties(navigator, {
        canShare: { configurable: true, value: () => supportsFiles },
        share: { configurable: true, value: async ({ files }: ShareData) => {
          sessionStorage.setItem('transfer', await files![0].text());
        } },
        clipboard: { configurable: true, value: { writeText: async (value: string) => {
          sessionStorage.setItem('transfer', value);
        } } },
      });
    }, canShareFiles);
    await page.goto('/');
    await expect(page.locator('#wall-view')).toHaveValue('self');
    await page.locator('#wall-exchange summary').click();
    await page.locator('#wall-export').click();
    await expect(page.locator('#wall-download')).toBeHidden();
    const transfer = page.getByRole('button', { name: canShareFiles ? 'Share JSON' : 'Copy JSON' });
    await transfer.click();
    await expect(page.locator('#wall-status')).toHaveText(canShareFiles ? 'Wall shared.' : 'Wall JSON copied.');
    expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem('transfer')!).format)).toBe('mariana.wall.v1');
  });
}

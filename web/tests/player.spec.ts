import { expect, test } from '@playwright/test';

test('tone, persisted playback controls, appearance and offline local audio', async ({ page, context }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => true));
  await page.locator('#cmd').fill('tone sine 440 --seconds 50');
  await page.locator('#command button').click();
  await expect(page.locator('#queue li')).toHaveCount(1);
  await expect(page.locator('#duration')).toHaveText('0:50');
  if (await page.locator('#play').innerText() === 'Play') await page.locator('#play').click();
  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  await page.locator('#fwd').click();
  await page.locator('#bookmark').click();
  await expect(page.locator('#marks li')).toHaveCount(1);
  const mark = await page.locator('#marks li button').first().innerText();
  await page.selectOption('#theme', 'redblood');
  await page.locator('nav [data-mode=flow]').click();
  await expect(page.locator('.console')).toBeHidden();
  await page.reload();
  await expect(page.locator('#theme')).toHaveValue('redblood');
  await expect(page.locator('#duration')).toHaveText('0:50');
  await expect(page.locator('#marks li button').first()).toHaveText(mark);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await context.setOffline(true);
  await page.reload();
  await expect(page.locator('#duration')).toHaveText('0:50');
  await page.locator('#play').click();
  await expect(page.locator('#play')).toHaveText('Pause');
  await page.locator('#queue li button').last().click();
  await expect(page.locator('#empty')).toBeVisible();
  expect(errors).toEqual([]);
});

test('RSS import identifies and deduplicates enclosures', async ({ page }) => {
  await page.route('https://podcast.example/show.xml', route => route.fulfill({
    contentType: 'application/rss+xml', headers: { 'Access-Control-Allow-Origin': '*' },
    body: '<rss><channel><title>Music show</title><item><title>Live show</title><enclosure url="https://podcast.example/live.wav"/></item></channel></rss>',
  }));
  await page.route('https://podcast.example/live.wav', route => route.abort());
  await page.goto('/');
  for (const expected of [1,0]) {
    await page.locator('#cmd').fill('feed https://podcast.example/show.xml');
    await page.locator('#command button').click();
    await expect(page.locator('#transcript')).toContainText('Added ' + expected + ' episode(s).');
  }
  await expect(page.locator('#queue li')).toHaveCount(1);
});

test('music walls exchange public snapshots and persist local posts across modes', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#wall-view')).toHaveValue('self');
  await page.locator('#cmd').fill('wall');
  await page.locator('#command button').click();
  await expect(page.locator('#wall-title')).toBeFocused();
  await page.locator('#wall-profile input').fill('Mariana listener');
  await page.locator('#wall-profile button').click();
  await expect(page.locator('#wall-status')).toHaveText('Profile saved.');
  await page.locator('#wall-compose summary').click();
  const form = page.locator('#wall-post');
  await form.locator('[name=kind]').selectOption('review');
  await form.locator('[name=artist]').fill('Indie artist');
  await form.locator('[name=title]').fill('First release');
  await form.locator('[name=body]').fill('Acoustic arrangement');
  await form.getByRole('button').click();
  await expect(page.locator('#wall-posts h3')).toHaveText('First release');
  await page.locator('#wall-exchange summary').click();
  await page.locator('#wall-export').click();
  await expect(page.locator('#wall-json')).toHaveValue(/mariana.wall.v1/);
  const snapshot = JSON.parse(await page.locator('#wall-json').inputValue());
  expect(snapshot.name).toBe('Mariana listener');
  expect(snapshot.posts[0].body).toBe('Acoustic arrangement');
  const peer = { ...snapshot, id: '7bd43bc0-3129-4bc5-a698-53375bd573c3', name: 'Friend', posts: [] };
  await page.locator('#wall-json').fill(JSON.stringify(peer));
  await page.locator('#wall-import').click();
  await expect(page.locator('#wall-view')).toHaveValue(peer.id);
  await expect(page.locator('#wall-compose')).toBeHidden();
  await page.locator('#wall-view').selectOption('self');
  await page.getByRole('button', {name:'Flow',exact:true}).click();
  await page.reload();
  await page.locator('#workspace-navigation [data-area=rooms]').click();
  await expect(page.locator('#wall-posts h3')).toHaveText('First release');
  await expect(page.locator('#wall-view option')).toHaveCount(2);
  await expect(page.locator('.console')).toBeHidden();
});

test('creates a PNG share card from a single wall post', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#wall-view')).toHaveValue('self');
  await page.locator('#wall-compose summary').click();
  await page.locator('#wall-post [name=artist]').fill('Artist');
  await page.locator('#wall-post [name=title]').fill('Track');
  await page.locator('#wall-post button').click();
  await page.getByRole('button',{name:'Create PNG card for Track'}).click();
  const image = page.locator('#wall-card-preview');
  await expect(image).toBeVisible();
  await expect(image).toHaveAttribute('alt', /Track/);
  await expect.poll(() => image.evaluate(el => (el as HTMLImageElement).naturalWidth)).toBe(1080);
  await expect(page.locator('#wall-card-caption')).toHaveValue(/Artist/);
  const url = await page.locator('#wall-card-download').getAttribute('href');
  expect(await page.evaluate(async href => {
    const response = await fetch(href!);
    return Array.from(new Uint8Array(await response.arrayBuffer()).slice(0,8));
  },url)).toEqual([137,80,78,71,13,10,26,10]);
  await page.getByText('Close preview',{exact:true}).click();
  await expect(image).toBeHidden();
});

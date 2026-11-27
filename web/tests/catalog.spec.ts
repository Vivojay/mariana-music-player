import { expect, test } from '@playwright/test';

test('searching, saving and queueing a single LibriVox chapter', async ({ page }) => {
  await page.route('https://librivox.org/api/feed/audiobooks/**', route => route.fulfill({
    json: { books: [{title: 'Frankenstein', authors: [{first_name: 'Mary', last_name: 'Shelley'}],
      url_rss: 'https://librivox.org/rss/12'}] },
    headers: {'Access-Control-Allow-Origin': '*'},
  }));
  await page.route('https://librivox.org/rss/12', route => route.fulfill({
    contentType: 'application/rss+xml', headers: {'Access-Control-Allow-Origin': '*'},
    body: '<rss><channel><item><title>Chapter one</title><enclosure url="https://audio.example/chapter1.mp3"/></item></channel></rss>',
  }));
  await page.route('https://audio.example/**', route => route.abort());
  await page.goto('/');
  await page.selectOption('#catalog-source', 'book');
  await page.fill('#catalog-term', 'Franken');
  await page.locator('#catalog-search button').click();
  await expect(page.locator('#catalog-results')).toContainText('Mary Shelley');
  await page.locator('#catalog-results').getByRole('button', {name:'Save',exact:true}).click();
  await page.reload();
  await page.locator('#catalog-shelf').getByRole('button', {name:'Chapters'}).click();
  await page.getByRole('button', {name:'Queue Chapter one'}).click();
  await expect(page.locator('#queue li')).toHaveCount(1);
  await expect(page.locator('#queue')).toContainText('Chapter one');
});

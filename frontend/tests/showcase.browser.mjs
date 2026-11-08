import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve, dirname } from 'node:path';
import { chromium } from 'playwright';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const url = pathToFileURL(resolve(root, 'showcase/index.html')).href;

test('showcase explains the reading boundary and responds to keyboard input', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [390, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      await page.goto(url);
      const slider = page.getByRole('slider', { name: /I am reading/ });
      await slider.focus();
      await page.keyboard.press('ArrowRight');
      assert.equal(await slider.getAttribute('aria-valuetext'), 'Chapter 3');
      assert.match(await page.locator('#boundary-result').innerText(), /Chapters 1 and 2/);
      await page.keyboard.press('ArrowRight');
      assert.equal(await slider.getAttribute('aria-valuetext'), 'Finished book');
      assert.match(await page.locator('#boundary-result').innerText(), /All detected chapters/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.locator('img').evaluateAll((images) => images.every((image) => image.complete && image.naturalWidth > 0)), true);
      assert.equal(await page.getByRole('link', { name: /See how to run it/ }).getAttribute('href'), 'https://github.com/Giapa/Spoiless#readme');
      await page.close();
    }
  } finally {
    await browser.close();
  }
});

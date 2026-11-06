import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { chromium } from 'playwright';

const port = await new Promise((resolve, reject) => {
  const listener = createServer().once('error', reject);
  listener.listen(0, '127.0.0.1', () => {
    const address = listener.address();
    listener.close(() => resolve(address.port));
  });
});
const server = spawn('node', ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { stdio: 'ignore' });
after(() => server.kill());

async function openApp(width = 1440) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width, height: 844 } });
  page.setDefaultTimeout(5000);
  let modelReady = false;
  let modelError = false;
  await page.route(`http://127.0.0.1:${port}/api/**`, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/semantic-model') {
      if (modelError) return route.fulfill({ status: 503 });
      if (route.request().method() === 'POST') modelReady = true;
      return route.fulfill({ json: { ready: modelReady } });
    }
    const body = path === '/api/books' || path === '/api/chatgpt/accounts' ? [] : { status: 'idle', email: null, plan_usage_enabled: null };
    return route.fulfill({ json: body });
  });
  for (let tries = 0; ; tries++) {
    try { await page.goto(`http://127.0.0.1:${port}`); break; }
    catch (error) { if (tries >= 50) throw error; await new Promise((resolve) => setTimeout(resolve, 100)); }
  }
  if (width < 700) await page.getByRole('button', { name: 'Show sidebar' }).click();
  return { browser, page, setError: (value) => { modelError = value; } };
}

test('local search setup hides after download and stays hidden when already ready', async () => {
  const { browser, page } = await openApp();
  try {
    const summary = page.getByText('Local search settings');
    await summary.click();
    await page.getByRole('button', { name: 'Download model' }).click();
    await summary.waitFor({ state: 'detached' });
    await page.reload();
    assert.equal(await summary.count(), 0);
  } finally { await browser.close(); }
});

test('local search setup can retry a status failure', async () => {
  const { browser, page, setError } = await openApp();
  try {
    setError(true);
    await page.reload();
    await page.getByText('Local search settings').click();
    await page.getByText('Could not check model setup.').waitFor();
    setError(false);
    await page.getByRole('button', { name: 'Retry' }).click();
    await page.getByRole('button', { name: 'Download model' }).waitFor();
  } finally { await browser.close(); }
});

test('plan notice fits on phone and Escape dismisses it for the account', async () => {
  const { browser, page } = await openApp(390);
  try {
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/accounts`, (route) => route.fulfill({ json: [{ id: 'test-account', email: null, active: true }] }));
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in`, (route) => route.fulfill({ json: { status: 'connected', email: null, plan_usage_enabled: true } }));
    await page.reload();
    const dialog = page.getByRole('dialog', { name: 'You’re using your ChatGPT plan' });
    await dialog.waitFor();
    const box = await dialog.boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= 390);
    assert.ok(box.y >= 0 && box.y + box.height <= 844);
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'detached' });
    await page.reload();
    assert.equal(await dialog.count(), 0);
  } finally { await browser.close(); }
});

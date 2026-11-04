import { test, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { chromium } from "playwright";

const port = await new Promise((resolve, reject) => {
  const listener = createServer();
  listener.once("error", reject);
  listener.listen(0, "127.0.0.1", () => {
    const address = listener.address();
    listener.close(() => resolve(address.port));
  });
});
const server = spawn("node", ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(port), "--strictPort"], { stdio: "ignore" });
after(() => server.kill());

async function openApp() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.setDefaultTimeout(3000);
  await page.route(`http://127.0.0.1:${port}/api/**`, async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = path === "/api/books" ? [] : path === "/api/semantic-model" ? { ready: false } : path === "/api/chatgpt/accounts" ? [] : { status: "idle", email: null, plan_usage_enabled: null };
    await route.fulfill({ json: body });
  });
  for (let tries = 0; ; tries++) {
    try { await page.goto(`http://127.0.0.1:${port}`); break; }
    catch (error) { if (tries >= 50) throw error; await new Promise((resolve) => setTimeout(resolve, 100)); }
  }
  return { browser, page };
}

test("a reader can find ChatGPT sign-in in the library", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Continue with ChatGPT" }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Continue with ChatGPT" }).count(), 1);
    assert.match(await page.locator("body").innerText(), /ChatGPT plan/);
  } finally { await browser.close(); }
});

test("a reader can start and cancel a browser sign-in", async () => {
  const { browser, page } = await openApp();
  let action;
  try {
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in`, async (route) => {
      if (route.request().method() === "POST") {
        action = route.request().postDataJSON();
        await route.fulfill({ json: { status: "pending", email: null, plan_usage_enabled: null } });
      } else await route.fulfill({ json: { status: "pending", email: null, plan_usage_enabled: null } });
    });
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in/cancel`, async (route) => {
      await route.fulfill({ json: { status: "cancelled", email: null, plan_usage_enabled: null } });
    });
    await page.getByRole("button", { name: "Continue with ChatGPT" }).click();
    await page.getByText(/complete sign-in in your browser/i).waitFor();
    assert.deepEqual(action, { confirm: true });
    await page.getByRole("button", { name: "Cancel sign-in" }).click();
    await page.getByText(/sign-in was cancelled/i).waitFor();
  } finally { await browser.close(); }
});

test("successful sign-in explains plan usage once", async () => {
  const { browser, page } = await openApp();
  let started = false;
  try {
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in`, async (route) => {
      if (route.request().method() === "POST") started = true;
      await route.fulfill({ json: started && route.request().method() === "GET" ? { status: "connected", email: "reader@example.test", plan_usage_enabled: true } : { status: started ? "pending" : "idle", email: null, plan_usage_enabled: null } });
    });
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/accounts`, async (route) => {
      await route.fulfill({ json: [{ id: "account-one", email: "reader@example.test", active: true }] });
    });
    await page.getByRole("button", { name: "Continue with ChatGPT" }).click();
    const dialog = page.getByRole("dialog", { name: "You’re using your ChatGPT plan" });
    await dialog.waitFor({ timeout: 4000 });
    assert.match(await dialog.innerText(), /eligible/i);
    await dialog.getByRole("button", { name: "Got it" }).click();
    assert.equal(await dialog.count(), 0);
    assert.match(await page.locator("body").innerText(), /reader@example.test/);
    await page.reload();
    await page.getByText(/connected as reader@example.test/i).waitFor();
    assert.equal(await dialog.count(), 0);
  } finally { await browser.close(); }
});

test("saved account can be reauthorized without claiming it is connected", async () => {
  const { browser, page } = await openApp();
  let action;
  try {
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/accounts`, async (route) => {
      await route.fulfill({ json: [{ id: "saved-account", email: "reader@example.test", active: true }] });
    });
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in`, async (route) => {
      if (route.request().method() === "POST") action = route.request().postDataJSON();
      await route.fulfill({ json: { status: action ? "pending" : "saved", email: "reader@example.test", plan_usage_enabled: null } });
    });
    await page.reload();
    await page.getByText(/saved account.*sign in again/i).waitFor();
    await page.getByRole("button", { name: "Continue with ChatGPT" }).click();
    await page.getByText(/complete sign-in in your browser/i).waitFor();
    assert.deepEqual(action, { confirm: true, account_id: "saved-account" });
  } finally { await browser.close(); }
});

test("sign-out warns when remote revocation was not confirmed", async () => {
  const { browser, page } = await openApp();
  try {
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/accounts`, (route) => route.fulfill({ json: [{ id: "saved-account", email: "reader@example.test", active: true }] }));
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in`, (route) => route.fulfill({ json: { status: "saved", email: "reader@example.test", plan_usage_enabled: null } }));
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-out`, (route) => route.fulfill({ json: { revocation_confirmed: false } }));
    await page.reload();
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByText(/could not confirm.*disconnect/i).waitFor();
    assert.equal(await page.getByRole("link", { name: /ChatGPT settings/i }).count(), 1);
  } finally { await browser.close(); }
});

test("reader can sign in with another saved registration", async () => {
  const { browser, page } = await openApp();
  let selected;
  try {
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/accounts`, (route) => route.fulfill({ json: [
      { id: "account-a", email: "same@example.test", active: true },
      { id: "account-b", email: "same@example.test", active: false },
    ] }));
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in`, (route) => {
      if (route.request().method() === "POST") selected = route.request().postDataJSON();
      return route.fulfill({ json: { status: selected ? "pending" : "saved", email: "same@example.test", plan_usage_enabled: null } });
    });
    await page.reload();
    const accountChoice = page.getByRole("combobox", { name: "Saved ChatGPT account" });
    await accountChoice.selectOption("account-b");
    await page.getByRole("button", { name: "Continue with ChatGPT" }).click();
    await page.getByText(/complete sign-in in your browser/i).waitFor();
    assert.deepEqual(selected, { confirm: true, account_id: "account-b" });
  } finally { await browser.close(); }
});

test("reader can retry when checking sign-in status fails", async () => {
  const { browser, page } = await openApp();
  try {
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in`, (route) => route.fulfill({ status: 503, json: { detail: "Unavailable" } }));
    await page.reload();
    await page.getByRole("alert").getByText(/could not check/i).waitFor();
    await page.unroute(`http://127.0.0.1:${port}/api/chatgpt/sign-in`);
    await page.getByRole("button", { name: "Retry" }).click();
    await page.getByRole("alert").waitFor({ state: "hidden" });
    assert.equal(await page.getByRole("button", { name: "Continue with ChatGPT" }).isEnabled(), true);
  } finally { await browser.close(); }
});

test("a delayed status check cannot undo cancellation", async () => {
  const { browser, page } = await openApp();
  let delayed;
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  try {
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in`, async (route) => {
      if (route.request().method() === "POST") return route.fulfill({ json: { status: "pending", email: null, plan_usage_enabled: null } });
      delayed = true;
      await held;
      await route.fulfill({ json: { status: "pending", email: null, plan_usage_enabled: null } });
    });
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in/cancel`, (route) => route.fulfill({ json: { status: "cancelled", email: null, plan_usage_enabled: null } }));
    await page.getByRole("button", { name: "Continue with ChatGPT" }).click();
    await page.waitForFunction(() => document.body.textContent?.includes("Complete sign-in"));
    await page.waitForTimeout(1200);
    assert.equal(delayed, true);
    await page.getByRole("button", { name: "Cancel sign-in" }).click();
    await page.getByText(/sign-in was cancelled/i).waitFor();
    release();
    await page.waitForTimeout(300);
    assert.equal(await page.getByText(/sign-in was cancelled/i).count(), 1);
  } finally { release(); await browser.close(); }
});

test("a new sign-in after signing out does not reuse a previous account", async () => {
  const { browser, page } = await openApp();
  let action;
  try {
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/accounts`, (route) => route.fulfill({ json: [{ id: "old-account", email: "reader@example.test", active: true }] }));
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in`, (route) => {
      if (route.request().method() === "POST") action = route.request().postDataJSON();
      return route.fulfill({ json: { status: action ? "pending" : "saved", email: "reader@example.test", plan_usage_enabled: null } });
    });
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-out`, (route) => route.fulfill({ json: { revocation_confirmed: true } }));
    await page.reload();
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByRole("button", { name: "Continue with ChatGPT" }).click();
    await page.getByText(/complete sign-in in your browser/i).waitFor();
    assert.deepEqual(action, { confirm: true });
  } finally { await browser.close(); }
});

test("signed-out registrations remain available for later sign-in", async () => {
  const { browser, page } = await openApp();
  let action;
  try {
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/accounts`, (route) => route.fulfill({ json: [{ id: "old-account", email: "reader@example.test", active: false }] }));
    await page.route(`http://127.0.0.1:${port}/api/chatgpt/sign-in`, (route) => {
      if (route.request().method() === "POST") action = route.request().postDataJSON();
      return route.fulfill({ json: { status: action ? "pending" : "idle", email: null, plan_usage_enabled: null } });
    });
    await page.reload();
    await page.getByRole("combobox", { name: "Saved ChatGPT account" }).selectOption("old-account");
    await page.getByRole("button", { name: "Continue with ChatGPT" }).click();
    await page.getByText(/complete sign-in in your browser/i).waitFor();
    assert.deepEqual(action, { confirm: true, account_id: "old-account" });
  } finally { await browser.close(); }
});

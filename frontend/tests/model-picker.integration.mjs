import { test, after } from "node:test";
import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { createServer } from "node:net";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright";

const port = await new Promise((resolvePort, reject) => {
  const listener = createServer();
  listener.once("error", reject);
  listener.listen(0, "127.0.0.1", () => {
    const address = listener.address();
    listener.close(() => resolvePort(address.port));
  });
});
const dataDir = mkdtempSync(join(tmpdir(), "spoiless-picker-test-"));
const python = process.env.SPOILESS_TEST_PYTHON || execFileSync("uv", ["run", "--project", "../backend", "python", "-c", "import sys; print(sys.executable)"], { encoding: "utf8" }).trim();
const server = spawn(python, ["tests/support/model_picker_server.py"], {
  env: { ...process.env, XDG_DATA_HOME: dataDir, SPOILESS_TEST_PORT: String(port), PYTHONPATH: resolve("../backend") },
  stdio: "inherit",
});
after(async () => {
  if (server.exitCode === null) {
    server.kill();
    await new Promise((resolveExit) => server.once("exit", resolveExit));
  }
  rmSync(dataDir, { recursive: true, force: true });
});

async function openApp() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.setDefaultTimeout(3000);
  for (let tries = 0; ; tries++) {
    try { await page.goto(`http://127.0.0.1:${port}`); break; }
    catch (error) { if (tries >= 50) throw error; await new Promise((r) => setTimeout(r, 100)); }
  }
  return { browser, page };
}

test("reader loads and chooses models through the local API", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    const select = page.getByRole("combobox", { name: "ChatGPT model" });
    await select.selectOption("a2");
    assert.equal(await select.inputValue(), "a2");
    assert.deepEqual(await select.locator("option").allTextContents(), ["Choose a model", "Model A1", "Model A2"]);
  } finally { await browser.close(); }
});


test("switching the selected account clears stale models on return", async () => {
  const { browser, page } = await openApp();
  const origin = `http://127.0.0.1:${port}`;
  const headers = { Origin: origin, "X-Spoiless-Action": "1" };
  let first;
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    const select = page.getByRole("combobox", { name: "ChatGPT model" });
    await select.selectOption("a2");
    const accounts = await (await page.request.get(`${origin}/api/chatgpt/accounts`)).json();
    first = accounts.find((account) => account.email === "a@example.test").id;
    const second = accounts.find((account) => account.email === "b@example.test").id;
    const changed = await page.request.post(`${origin}/api/chatgpt/accounts/select`, { headers, data: { account_id: second, confirm: true } });
    assert.equal(changed.status(), 200);
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await select.waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "Load available models" }).click();
    await select.selectOption("b1");
    assert.deepEqual(await select.locator("option").allTextContents(), ["Choose a model", "Model B1"]);
  } finally {
    if (first) await page.request.post(`${origin}/api/chatgpt/accounts/select`, { headers, data: { account_id: first, confirm: true } });
    await browser.close();
  }
});


test("reader sees an empty state when the account has no models", async () => {
  const { browser, page } = await openApp();
  const origin = `http://127.0.0.1:${port}`;
  const headers = { Origin: origin, "X-Spoiless-Action": "1" };
  let first;
  try {
    const accounts = await (await page.request.get(`${origin}/api/chatgpt/accounts`)).json();
    first = accounts.find((account) => account.email === "a@example.test").id;
    const third = accounts.find((account) => account.email === "c@example.test").id;
    assert.equal((await page.request.post(`${origin}/api/chatgpt/accounts/select`, { headers, data: { account_id: third, confirm: true } })).status(), 200);
    await page.reload();
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByText(/no models are available/i).waitFor();
    assert.equal(await page.getByRole("combobox", { name: "ChatGPT model" }).count(), 0);
  } finally {
    if (first) await page.request.post(`${origin}/api/chatgpt/accounts/select`, { headers, data: { account_id: first, confirm: true } });
    await browser.close();
  }
});


test("reader can retry after a model lookup failure", async () => {
  const { browser, page } = await openApp();
  const origin = `http://127.0.0.1:${port}`;
  const headers = { Origin: origin, "X-Spoiless-Action": "1" };
  let first;
  try {
    const accounts = await (await page.request.get(`${origin}/api/chatgpt/accounts`)).json();
    first = accounts.find((account) => account.email === "a@example.test").id;
    const fourth = accounts.find((account) => account.email === "d@example.test").id;
    assert.equal((await page.request.post(`${origin}/api/chatgpt/accounts/select`, { headers, data: { account_id: fourth, confirm: true } })).status(), 200);
    await page.reload();
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("alert").getByText(/could not load chatgpt models/i).waitFor();
    assert.equal((await page.locator("body").innerText()).includes("secret-provider-details"), false);
    assert.equal(await page.getByRole("button", { name: "Load available models" }).isEnabled(), true);
  } finally {
    if (first) await page.request.post(`${origin}/api/chatgpt/accounts/select`, { headers, data: { account_id: first, confirm: true } });
    await browser.close();
  }
});

test("reader sees the account error and can retry model loading", async () => {
  const { browser, page } = await openApp();
  try {
    await page.route("**/api/chatgpt/models", async (route) => {
      await route.fulfill({ status: 409, json: { detail: "This account needs to sign in again." } });
      await page.unroute("**/api/chatgpt/models");
    });
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("alert").getByText("This account needs to sign in again.").waitFor();
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a2");
  } finally { await browser.close(); }
});

test("signing out clears the previous account's model selection", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    const select = page.getByRole("combobox", { name: "ChatGPT model" });
    await select.selectOption("a2");
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByText(/signed out locally/i).waitFor();
    await select.waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByText("Connect a ChatGPT account first.").waitFor();
  } finally { await browser.close(); }
});

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
const dataDir = mkdtempSync(join(tmpdir(), "spoiless-question-test-"));
const python = process.env.SPOILESS_TEST_PYTHON || execFileSync("uv", ["run", "--project", "../backend", "python", "-c", "import sys; print(sys.executable)"], { encoding: "utf8" }).trim();
const server = spawn(python, ["tests/support/question_server.py"], {
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
  page.setDefaultTimeout(6000);
  for (let tries = 0; ; tries++) {
    try { await page.goto(`http://127.0.0.1:${port}`); break; }
    catch (error) { if (tries >= 50) throw error; await new Promise((r) => setTimeout(r, 100)); }
  }
  await page.getByText("Account and model", { exact: true }).click();
  return { browser, page };
}

test("reader recaps a completed chapter and sees a citation", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a1");
    await page.getByText("Recap a completed chapter", { exact: true }).click();
    const chapter = page.getByRole("combobox", { name: "Chapter to recap" });
    assert.deepEqual((await chapter.locator("option").allTextContents()).map((text) => text.trim()), ["Choose a chapter", "Chapter 1"]);
    await chapter.selectOption("1");
    assert.match(await page.locator("body").innerText(), /selected chapter.*sent to OpenAI/i);
    assert.match(await page.locator("body").innerText(), /longer recaps use multiple AI requests/i);
    assert.match(await page.locator("body").innerText(), /may continue after you leave/i);
    assert.match(await page.locator("body").innerText(), /may count toward your usage limits/i);
    await page.getByRole("button", { name: "Create recap" }).click();
    const recap = page.getByRole("region", { name: "Recap" });
    await recap.getByText("Mira found the key.").waitFor();
    await recap.getByText("found the key", { exact: true }).waitFor();
    assert.equal((await page.locator("body").innerText()).includes("UNREAD_SECRET"), false);
  } finally { await browser.close(); }
});

test("reader can recap through a completed chapter", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a1");
    await page.getByText("Recap a completed chapter", { exact: true }).click();
    await page.getByRole("combobox", { name: "Chapter to recap" }).selectOption("1");
    await page.getByRole("radio", { name: "From the beginning through this chapter" }).check();
    await page.getByText(/confirmed front matter and all chapters through the selected chapter.*sent to OpenAI/i).waitFor();
    const sent = page.waitForRequest((request) => request.method() === "POST" && new URL(request.url()).pathname.endsWith("/recap"));
    await page.getByRole("button", { name: "Create recap" }).click();
    assert.equal((await sent).postDataJSON().mode, "through");
    const recap = page.getByRole("region", { name: "Recap" });
    await recap.getByText("Mira found the key.").waitFor();
    await recap.getByText("found the key", { exact: true }).waitFor();
    assert.equal((await page.locator("body").innerText()).includes("UNREAD_SECRET"), false);
    await page.getByRole("radio", { name: "Only this chapter" }).check();
    await recap.waitFor({ state: "hidden" });
  } finally { await browser.close(); }
});

test("moving backward withholds an in-flight recap", async () => {
  const { browser, page } = await openApp();
  try {
    const progress = page.getByRole("combobox", { name: "Current chapter" });
    await progress.selectOption({ label: "Finished book" });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByText("Reading progress saved.").waitFor();
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a3");
    await page.getByText("Recap a completed chapter", { exact: true }).click();
    await page.getByRole("radio", { name: "From the beginning through this chapter" }).check();
    await page.getByRole("combobox", { name: "Chapter to recap" }).selectOption("2");
    await page.getByRole("button", { name: "Create recap" }).click();
    await page.waitForFunction(async () => (await (await fetch("/__test__/question_started")).json()).started);
    await progress.selectOption({ label: "Chapter 2" });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByText("Reading progress saved.").waitFor();
    await page.waitForTimeout(1800);
    assert.equal((await page.locator("body").innerText()).includes("UNREAD_SECRET"), false);
    await page.getByText("Recap a completed chapter", { exact: true }).click();
    assert.deepEqual((await page.getByRole("combobox", { name: "Chapter to recap" }).locator("option").allTextContents()).map((text) => text.trim()), ["Choose a chapter", "Chapter 1"]);
  } finally { await browser.close(); }
});

test("recap requires a selected model", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByText("Recap a completed chapter", { exact: true }).click();
    await page.getByRole("combobox", { name: "Chapter to recap" }).selectOption("1");
    assert.equal(await page.getByRole("button", { name: "Create recap" }).isDisabled(), true);
    await page.getByText(/choose a ChatGPT model below to create a recap/i).waitFor();
  } finally { await browser.close(); }
});

test("recap with invalid citations is withheld and can be retried", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a4");
    await page.getByText("Recap a completed chapter", { exact: true }).click();
    await page.getByRole("combobox", { name: "Chapter to recap" }).selectOption("1");
    await page.getByRole("button", { name: "Create recap" }).click();
    await page.getByRole("alert").getByText(/could not verify the answer citations/i).waitFor();
    assert.equal((await page.locator("body").innerText()).includes("UNREAD_SECRET"), false);
    assert.equal(await page.getByRole("button", { name: "Create recap" }).isEnabled(), true);
  } finally { await browser.close(); }
});

test("recap usage limit offers the usage settings link", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a2");
    await page.getByText("Recap a completed chapter", { exact: true }).click();
    await page.getByRole("combobox", { name: "Chapter to recap" }).selectOption("1");
    await page.getByRole("button", { name: "Create recap" }).click();
    await page.getByRole("alert").getByText(/usage limit/i).waitFor();
    assert.ok(await page.getByRole("link", { name: "Manage usage" }).count() >= 1);
  } finally { await browser.close(); }
});

test("leaving the window clears a completed recap", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a1");
    await page.getByText("Recap a completed chapter", { exact: true }).click();
    await page.getByRole("combobox", { name: "Chapter to recap" }).selectOption("1");
    await page.getByRole("button", { name: "Create recap" }).click();
    const recap = page.getByRole("region", { name: "Recap" });
    await recap.getByText("Mira found the key.").waitFor();
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    await recap.waitFor({ state: "hidden" });
  } finally { await browser.close(); }
});

test("switching recap scope clears a pending result", async () => {
  const { browser, page } = await openApp();
  try {
    const progress = page.getByRole("combobox", { name: "Current chapter" });
    await progress.selectOption({ label: "Finished book" });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByText("Reading progress saved.").waitFor();
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a3");
    await page.getByText("Recap a completed chapter", { exact: true }).click();
    await page.getByRole("combobox", { name: "Chapter to recap" }).selectOption("2");
    await page.getByRole("radio", { name: "From the beginning through this chapter" }).check();
    const sent = page.waitForRequest((request) => request.method() === "POST" && new URL(request.url()).pathname.endsWith("/recap"));
    await page.getByRole("button", { name: "Create recap" }).click();
    await sent;
    await page.getByRole("radio", { name: "Only this chapter" }).check();
    await page.waitForTimeout(1800);
    assert.equal(await page.getByRole("region", { name: "Recap" }).count(), 0);
    assert.equal((await page.locator("body").innerText()).includes("UNREAD_SECRET"), false);
  } finally { await browser.close(); }
});

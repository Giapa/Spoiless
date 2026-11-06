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

test("available chapters can be selected without review", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("heading", { name: "The Sample Book" }).waitFor();
    assert.equal(await page.getByRole("button", { name: /review chapters/i }).count(), 0);
    const progress = page.getByRole("combobox", { name: "Current chapter" });
    await progress.selectOption({ label: "Chapter 1: The Lost Key" });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByText("Reading progress saved.").waitFor();
    assert.equal(await page.getByText("Ask about completed chapters").count(), 0);
    await progress.selectOption({ label: "Chapter 2" });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByText("Reading progress saved.").waitFor();
  } finally { await browser.close(); }
});

test("AI chapter analysis can be retried and makes chapters available", async () => {
  const { browser, page } = await openApp();
  let bookId;
  try {
    const response = await page.request.post(`http://127.0.0.1:${port}/__test__/unmapped-book`);
    assert.equal(response.ok(), true);
    bookId = (await response.json()).id;
    await page.reload();
    await page.getByRole("combobox", { name: "Book" }).selectOption({ label: "Unmapped Book" });
    await page.getByText("Chapters could not be detected", { exact: false }).waitFor();
    await page.getByText(/full book, including unread text/i).waitFor();
    assert.equal(await page.getByRole("button", { name: "Analyze chapters" }).isDisabled(), true);
    await page.getByText("Account and model", { exact: true }).click();
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a2");
    await page.getByRole("button", { name: "Analyze chapters" }).click();
    await page.getByRole("alert").getByText("Could not verify chapter boundaries. Please retry.").waitFor();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a1");
    await page.getByRole("button", { name: "Analyze chapters" }).click();
    await page.getByRole("combobox", { name: "Current chapter" }).waitFor();
    assert.equal(await page.getByRole("combobox", { name: "Current chapter" }).locator("option").count(), 4);
    assert.equal(await page.getByRole("button", { name: /review chapters/i }).count(), 0);
  } finally {
    if (bookId) await page.request.delete(`http://127.0.0.1:${port}/api/books/${bookId}`, { headers: { Origin: `http://127.0.0.1:${port}`, "X-Spoiless-Action": "1" } });
    await browser.close();
  }
});


test("reader asks a question and sees a verified citation", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a1");
    await page.getByRole("textbox", { name: "Your question" }).fill("Who found the key?");
    assert.match(await page.locator("body").innerText(), /passages.*sent to OpenAI/i);
    assert.match(await page.locator("body").innerText(), /recent conversation may be sent to OpenAI/i);
    await page.getByRole("button", { name: "Ask" }).click();
    await page.getByText("Mira found the key.").waitFor();
    assert.match(await page.locator("body").innerText(), /found the key/);
    assert.equal((await page.locator("body").innerText()).includes("UNREAD_SECRET"), false);
  } finally { await browser.close(); }
});

test("moving progress backward hides an in-flight answer", async () => {
  const { browser, page } = await openApp();
  try {
    const progress = page.getByRole("combobox", { name: "Current chapter" });
    await progress.selectOption({ label: "Finished book" });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByText("Reading progress saved.").waitFor();
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a3");
    await page.getByRole("textbox", { name: "Your question" }).fill("Who found the key?");
    await page.getByRole("button", { name: "Ask" }).click();
    await page.waitForFunction(async () => (await (await fetch("/__test__/question_started")).json()).started);
    await progress.selectOption({ label: "Chapter 2" });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByText("Reading progress saved.").waitFor();
    await page.waitForTimeout(1800);
    assert.equal((await page.locator("body").innerText()).includes("UNREAD_SECRET"), false);
  } finally { await browser.close(); }
});

test("usage limit directs the reader to ChatGPT usage settings", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a2");
    await page.getByRole("textbox", { name: "Your question" }).fill("Who found the key?");
    await page.getByRole("button", { name: "Ask" }).click();
    await page.getByRole("alert").getByText(/usage limit/i).waitFor();
    assert.equal(await page.getByRole("link", { name: "Manage usage" }).count(), 1);
  } finally { await browser.close(); }
});

test("unverifiable citations are withheld and reader can retry", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a4");
    await page.getByRole("textbox", { name: "Your question" }).fill("Who found the key?");
    await page.getByRole("button", { name: "Ask" }).click();
    await page.getByRole("alert").getByText(/could not verify the answer citations/i).waitFor();
    assert.equal((await page.locator("body").innerText()).includes("UNREAD_SECRET"), false);
    assert.equal(await page.getByRole("button", { name: "Ask" }).isEnabled(), true);
  } finally { await browser.close(); }
});

test("changing progress clears an already displayed answer", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a1");
    await page.getByRole("textbox", { name: "Your question" }).fill("Who found the key?");
    await page.getByRole("button", { name: "Ask" }).click();
    await page.getByText("Mira found the key.").waitFor();
    await page.getByRole("combobox", { name: "Current chapter" }).selectOption({ label: "Finished book" });
    await page.getByText("Mira found the key.").waitFor({ state: "hidden" });
  } finally { await browser.close(); }
});

test("a question cannot be sent until a model is selected", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("textbox", { name: "Your question" }).fill("Who found the key?");
    assert.equal(await page.getByRole("button", { name: "Ask" }).isDisabled(), true);
    await page.getByText("Choose a model in Account and model to ask a question.").waitFor();
  } finally { await browser.close(); }
});

test("leaving the window clears a displayed answer", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a1");
    await page.getByRole("textbox", { name: "Your question" }).fill("Who found the key?");
    await page.getByRole("button", { name: "Ask" }).click();
    await page.getByText("Mira found the key.").waitFor();
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    await page.getByText("Mira found the key.").waitFor({ state: "hidden" });
  } finally { await browser.close(); }
});

test("reader can reopen saved questions, answers and citations", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a1");
    await page.getByRole("textbox", { name: "Your question" }).fill("What did Mira find?");
    await page.getByRole("button", { name: "Ask" }).click();
    await page.getByRole("listitem").filter({ hasText: "What did Mira find?" }).getByText("Mira found the key.").waitFor();
    await page.reload();
    const history = page.getByRole("region", { name: "Conversation history" });
    const turn = history.getByRole("listitem").filter({ hasText: "What did Mira find?" });
    await turn.getByText("Mira found the key.").waitFor();
    await turn.getByText("found the key", { exact: true }).waitFor();
  } finally { await browser.close(); }
});

test("moving backward hides the old conversation even after moving forward again", async () => {
  const { browser, page } = await openApp();
  try {
    const progress = page.getByRole("combobox", { name: "Current chapter" });
    await progress.selectOption({ label: "Finished book" });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByText("Reading progress saved.").waitFor();
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a3");
    await page.getByRole("textbox", { name: "Your question" }).fill("Who found the key?");
    await page.getByRole("button", { name: "Ask" }).click();
    await page.getByText(/UNREAD_SECRET/).first().waitFor();
    const history = page.getByRole("region", { name: "Conversation history" });
    await history.getByText(/UNREAD_SECRET/).first().waitFor();
    await progress.selectOption({ label: "Chapter 2" });
    assert.equal(await history.count(), 0);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByText("Reading progress saved.").waitFor();
    await history.getByText("No questions in this conversation yet.").waitFor();
    await progress.selectOption({ label: "Finished book" });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.getByText("Reading progress saved.").waitFor();
    await history.getByText("No questions in this conversation yet.").waitFor();
  } finally { await browser.close(); }
});

test("an open history updates after asking and closes when leaving the window", async () => {
  const { browser, page } = await openApp();
  try {
    const progress = page.getByRole("combobox", { name: "Current chapter" });
    if (await progress.inputValue() !== "2") {
      await progress.selectOption({ label: "Chapter 2" });
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await page.getByText("Reading progress saved.").waitFor();
    }
    const history = page.getByRole("region", { name: "Conversation history" });
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a1");
    await page.getByRole("textbox", { name: "Your question" }).fill("Where was the key?");
    await page.getByRole("button", { name: "Ask" }).click();
    await history.getByText("Where was the key?").waitFor();
    await page.evaluate(() => window.dispatchEvent(new Event("blur")));
    await history.getByText("No questions in this conversation yet.").waitFor();
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await page.getByRole("region", { name: "Conversation history" }).getByText("Where was the key?").waitFor();
  } finally { await browser.close(); }
});

test("a newly imported book shows detected heading titles without review", async () => {
  const { browser, page } = await openApp();
  try {
    const epub = await (await page.request.get(`http://127.0.0.1:${port}/__test__/heading-epub`)).body();
    await page.locator('input[type="file"]').setInputFiles({ name: "headings.epub", mimeType: "application/epub+zip", buffer: epub });
    await page.getByRole("combobox", { name: "Book" }).selectOption({ label: "Heading Book" });
    const book = page.getByRole("region", { name: "Book conversation" });
    await book.getByRole("heading", { name: "Heading Book" }).waitFor();
    const progress = book.getByRole("combobox", { name: "Current chapter" });
    await progress.selectOption({ label: "Chapter 1: The Beginning" });
    await book.getByRole("button", { name: "Save", exact: true }).click();
    await book.getByText("Reading progress saved.").waitFor();
    assert.equal(await book.getByRole("button", { name: /review/i }).count(), 0);
    await page.getByRole("combobox", { name: "Book" }).selectOption({ label: "The Sample Book" });
    await page.getByRole("heading", { name: "The Sample Book" }).waitFor();
    assert.equal(await page.getByRole("heading", { name: "Heading Book" }).count(), 0);
  } finally { await browser.close(); }
});


test("phone layout supports keyboard access to chapter and composer", async () => {
  const { browser, page } = await openApp();
  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("combobox", { name: "Book" }).selectOption({ label: "The Sample Book" });
    await page.getByRole("heading", { name: "The Sample Book" }).waitFor();
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a1");
    const composer = page.getByRole("textbox", { name: "Your question" });
    await composer.focus();
    await page.keyboard.type("Who found the key?");
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement?.textContent?.trim()), "Manage usage");
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement?.textContent?.trim()), "Ask");
    await page.keyboard.press("Enter");
    await page.getByRole("region", { name: "Conversation history" }).getByText("Who found the key?").waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.getByRole("combobox", { name: "Current chapter" }).focus();
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("id")), await page.getByRole("combobox", { name: "Current chapter" }).getAttribute("id"));
  } finally { await browser.close(); }
});

test("first imported book is selected in an empty library", async () => {
  const { browser, page } = await openApp();
  try {
    const origin = `http://127.0.0.1:${port}`;
    const books = await (await page.request.get(`${origin}/api/books`)).json();
    for (const book of books) {
      const response = await page.request.delete(`${origin}/api/books/${book.id}`, { headers: { Origin: origin, "X-Spoiless-Action": "1" } });
      assert.equal(response.status(), 204);
    }
    await page.reload();
    await page.getByRole("heading", { name: "Start with a book" }).waitFor();
    const epub = await (await page.request.get(`${origin}/__test__/heading-epub`)).body();
    await page.locator('input[type="file"]').setInputFiles({ name: "headings.epub", mimeType: "application/epub+zip", buffer: epub });
    await page.getByRole("heading", { name: "Heading Book" }).waitFor();
    assert.notEqual(await page.getByRole("combobox", { name: "Book" }).inputValue(), "");
  } finally { await browser.close(); }
});

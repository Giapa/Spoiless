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
  env: { ...process.env, SPOILESS_TEST_LONG_RECAP: "1", XDG_DATA_HOME: dataDir, SPOILESS_TEST_PORT: String(port), PYTHONPATH: resolve("../backend") },
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

test("reader can view a cited recap of a long chapter", async () => {
  const { browser, page } = await openApp();
  try {
    await page.getByRole("button", { name: "Load available models" }).click();
    await page.getByRole("combobox", { name: "ChatGPT model" }).selectOption("a1");
    await page.getByText("Recap a completed chapter", { exact: true }).click();
    await page.getByRole("combobox", { name: "Chapter to recap" }).selectOption("1");
    await page.getByRole("button", { name: "Create recap" }).click();
    const recap = page.getByRole("region", { name: "Recap" });
    await recap.getByText("A supported recap.").waitFor();
    await recap.getByText("LAST_FACT", { exact: true }).waitFor();
    assert.equal((await page.locator("body").innerText()).includes("UNREAD_SECRET"), false);
  } finally { await browser.close(); }
});

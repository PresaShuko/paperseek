import { spawn } from "node:child_process";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const viteEntry = resolve(root, "node_modules/vite/bin/vite.js");
const playwrightEntry = resolve(root, "node_modules/@playwright/test/cli.js");
const externalBase = process.env.PAPERSEEK_BROWSER_BASE_URL;
const server = externalBase ? null : spawn(
    process.execPath,
    [viteEntry, "--host", "127.0.0.1", "--port", "4173", "--strictPort"],
    { cwd: root, stdio: ["ignore", "ignore", "inherit"] },
  );

async function waitForServer() {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (server?.exitCode !== null && server !== null) throw new Error(`Vite exited with code ${server.exitCode}.`);
    try {
      const response = await fetch(externalBase || "http://127.0.0.1:4173/");
      if (response.ok) return;
    } catch {
      // The server is still starting.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error("Vite did not become ready within 30 seconds.");
}

function stopServer() {
  if (server?.exitCode === null) server.kill();
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    stopServer();
    process.exitCode = 130;
  });
}

let exitCode = 1;
try {
  await waitForServer();
  exitCode = await new Promise((resolveExit) => {
    const tests = spawn(process.execPath, [playwrightEntry, "test", ...process.argv.slice(2)], {
      cwd: root,
      stdio: "inherit",
    });
    tests.on("exit", (code) => resolveExit(code ?? 1));
  });
} finally {
  stopServer();
}

process.exitCode = exitCode;

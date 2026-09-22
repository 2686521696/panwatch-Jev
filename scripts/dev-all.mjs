/**
 * Start the PanWatch dev stack: API :8000, then frontend :5183.
 * Ctrl+C stops both. Busy ports are cleared with dev-stop first.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import net from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  API_PORT,
  DEV_PORTS,
  WEB_PORT,
  outputHasReady,
  pythonExecutable,
  resolveDevReload,
} from "./dev-stack.mjs";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const frontendDir = resolve(projectRoot, "frontend");

const children = [];
let shuttingDown = false;

function canConnect(port) {
  return new Promise((resolvePromise) => {
    const socket = net.connect({ host: "127.0.0.1", port });
    const done = (value) => {
      socket.removeAllListeners();
      socket.destroy();
      resolvePromise(value);
    };
    socket.setTimeout(400);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
  });
}

async function busyPorts() {
  const busy = [];
  for (const entry of DEV_PORTS) {
    if (await canConnect(entry.port)) busy.push(entry);
  }
  return busy;
}

class PreflightAbort extends Error {
  constructor(label) {
    super(`preflight aborted: ports busy (${label})`);
    this.name = "PreflightAbort";
  }
}

function terminateChild(child) {
  if (!child?.pid) return;
  if (process.platform === "win32") {
    spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    });
    return;
  }
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch {
    try {
      child.kill("SIGTERM");
    } catch {
      /* already gone */
    }
  }
}

function shutdown(exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) terminateChild(child);
  const timer = setTimeout(() => process.exit(exitCode), process.platform === "win32" ? 1200 : 300);
  timer.unref?.();
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

function prefixStream(stream, label, target) {
  let buffer = "";
  stream?.on("data", (chunk) => {
    buffer += chunk.toString();
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";
    for (const line of lines) target.write(`[${label}] ${line}\n`);
  });
  return () => buffer;
}

function run(name, command, args, { cwd, env, readyText, matchStderr = false, timeoutMs = 180000, portGuard }) {
  // shell:true plus an args array trips Node's DEP0190. On Windows, .cmd
  // shims (pnpm) still need a shell, so pass one command line instead.
  const spawnOptions = {
    cwd,
    env,
    detached: process.platform !== "win32",
    windowsHide: false,
    stdio: ["ignore", "pipe", "pipe"],
  };
  const quoteCmd = (value) => (
    /[\s"]/u.test(value) ? `"${String(value).replace(/"/g, '\\"')}"` : value
  );
  const child = process.platform === "win32"
    ? spawn([command, ...args].map(quoteCmd).join(" "), { ...spawnOptions, shell: true })
    : spawn(command, args, spawnOptions);
  children.push(child);

  const stdoutTail = prefixStream(child.stdout, name, process.stdout);
  const stderrTail = prefixStream(child.stderr, name, process.stderr);
  let settled = false;

  const ready = new Promise((resolveReady, rejectReady) => {
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      fn(value);
    };
    let readyBuffer = "";
    const consider = (text) => {
      readyBuffer = (readyBuffer + text).slice(-8000);
      if (outputHasReady(readyBuffer, readyText)) finish(resolveReady);
    };
    child.stdout?.on("data", (chunk) => consider(chunk.toString()));
    if (matchStderr) child.stderr?.on("data", (chunk) => consider(chunk.toString()));
    child.once("error", (error) => finish(rejectReady, error));
    child.once("exit", (code, signal) => {
      const reason = signal ? `signal ${signal}` : `code ${code ?? 0}`;
      const tail = [stdoutTail(), stderrTail()].filter(Boolean).join("\n");
      finish(
        rejectReady,
        new Error(tail ? `[${name}] exited with ${reason}\n${tail}` : `[${name}] exited with ${reason}`)
      );
    });
    setTimeout(() => {
      if (settled || !portGuard) {
        finish(rejectReady, new Error(`[${name}] timed out waiting for "${readyText}"`));
        return;
      }
      canConnect(portGuard).then((up) => {
        if (up) finish(resolveReady);
        else finish(rejectReady, new Error(`[${name}] timed out waiting for "${readyText}"`));
      });
    }, timeoutMs);
  });

  child.on("exit", (code, signal) => {
    if (shuttingDown || !settled) return;
    const reason = signal ? `signal ${signal}` : `code ${code ?? 0}`;
    // On Windows, `shell: true` is cmd.exe. It can exit after handing off to
    // python/pnpm while the real listener stays up. Don't tear the stack down
    // if the advertised port is still open.
    if (portGuard && process.platform === "win32") {
      canConnect(portGuard).then((stillListening) => {
        if (shuttingDown) return;
        if (stillListening) {
          console.warn(`[${name}] wrapper exited with ${reason}, but :${portGuard} is still up`);
          return;
        }
        console.error(`[${name}] exited with ${reason}`);
        shutdown(code && code !== 0 ? code : 1);
      });
      return;
    }
    console.error(`[${name}] exited with ${reason}`);
    shutdown(code && code !== 0 ? code : 1);
  });

  return { child, ready };
}

async function preflight() {
  let busy = await busyPorts();
  if (!busy.length) {
    console.log("[all] ports free");
    return;
  }
  const label = busy.map((entry) => `${entry.port} (${entry.name})`).join(", ");
  console.warn(`[all] ports busy: ${label} — running stop first`);
  await new Promise((resolveDone) => {
    const child = spawn(process.execPath, [resolve(projectRoot, "scripts", "dev-stop.mjs")], {
      cwd: projectRoot,
      stdio: "inherit",
    });
    child.on("close", () => resolveDone());
    child.on("error", (error) => {
      console.warn(`[all] stop failed to run: ${error.message}`);
      resolveDone();
    });
  });
  await new Promise((r) => setTimeout(r, 600));
  busy = await busyPorts();
  if (!busy.length) {
    console.log("[all] ports cleared");
    return;
  }
  const still = busy.map((entry) => `${entry.port} (${entry.name})`).join(", ");
  if (process.env.DEV_ALL_ALLOW_BUSY_PORTS === "1") {
    console.warn(`[all] ports still busy (${still}); starting anyway because DEV_ALL_ALLOW_BUSY_PORTS=1`);
    return;
  }
  console.error(
    `[all] ports still busy after stop: ${still}. Refusing to start a second stack. ` +
      "Set DEV_ALL_ALLOW_BUSY_PORTS=1 to override."
  );
  throw new PreflightAbort(still);
}

async function ensureFrontendDeps() {
  if (existsSync(resolve(frontendDir, "node_modules"))) return;
  console.log("[all] frontend/node_modules missing, running pnpm install");
  await new Promise((resolveDone, rejectDone) => {
    const child = spawn("pnpm", ["install", "--no-frozen-lockfile"], {
      cwd: frontendDir,
      stdio: "inherit",
      shell: process.platform === "win32",
    });
    child.on("exit", (code) => {
      if (code === 0) resolveDone();
      else rejectDone(new Error(`pnpm install exited ${code ?? 1}`));
    });
    child.on("error", rejectDone);
  });
}

async function startStack() {
  const python = pythonExecutable(projectRoot);
  if (!existsSync(python)) {
    throw new Error(
      `venv not found at ${python}. Create it with: python -m venv .venv ; .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt`
    );
  }

  await preflight();
  await ensureFrontendDeps();

  const reload = resolveDevReload();
  console.log(`[all] API http://127.0.0.1:${API_PORT}  DEV_RELOAD=${reload}`);
  console.log(`[all] Web http://127.0.0.1:${WEB_PORT}  (/api -> :${API_PORT})`);
  if (reload === "0" && process.platform === "win32") {
    console.log("[all] reload is off on Windows. Set DEV_RELOAD=1 if you want uvicorn --reload.");
  }

  const api = run("api", python, [resolve(projectRoot, "server.py")], {
    cwd: projectRoot,
    env: {
      ...process.env,
      DEV_RELOAD: reload,
      PYTHONUTF8: process.env.PYTHONUTF8 || "1",
      PYTHONIOENCODING: process.env.PYTHONIOENCODING || "utf-8",
    },
    readyText: "Application startup complete",
    matchStderr: true,
    portGuard: API_PORT,
  });

  await api.ready;
  if (shuttingDown) return;
  console.log("[all] API is up");

  const web = run("web", "pnpm", ["dev"], {
    cwd: frontendDir,
    env: { ...process.env },
    readyText: "Local:",
    matchStderr: true,
    timeoutMs: 120000,
    portGuard: WEB_PORT,
  });
  await web.ready;
  if (shuttingDown) return;
  console.log(`[all] ready  http://127.0.0.1:${WEB_PORT}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  startStack().catch((error) => {
    if (!(error instanceof PreflightAbort)) {
      console.error(`[all] ${error?.stack || error}`);
    }
    shutdown(1);
  });
}

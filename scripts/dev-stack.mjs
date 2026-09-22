/** Shared process matching for PanWatch `all` / `stop`. */

export const API_PORT = Number(process.env.PANWATCH_API_PORT || 8000);
export const WEB_PORT = Number(process.env.PANWATCH_WEB_PORT || 5183);

export const DEV_PORTS = [
  { port: API_PORT, name: "api" },
  { port: WEB_PORT, name: "web" },
];

/** Names allowed to be killed when they own a PanWatch dev port. */
export const DEV_PROCESS_NAMES = new Set([
  "node",
  "npm",
  "pnpm",
  "cmd",
  "python",
  "python3",
  "uvicorn",
]);

export const WSL_RELAY_NAMES = new Set([
  "wslrelay",
  "wslhost",
  "wslservice",
  "vmmem",
  "vmmemwsl",
]);

export function normalizePath(value) {
  return String(value ?? "").replace(/\\/g, "/").toLowerCase();
}

/**
 * Windows defaults reload off. uvicorn --reload double-imports and the
 * reloader parent often stalls /api/health. Set DEV_RELOAD=1 to opt in.
 */
export function resolveDevReload(env = process.env, platform = process.platform) {
  const raw = env.DEV_RELOAD;
  if (raw == null || String(raw).trim() === "") {
    return platform === "win32" ? "0" : "1";
  }
  return ["1", "true", "yes", "on"].includes(String(raw).trim().toLowerCase())
    ? "1"
    : "0";
}

export function pythonExecutable(root, platform = process.platform) {
  return platform === "win32"
    ? `${root}\\.venv\\Scripts\\python.exe`
    : `${root}/.venv/bin/python`;
}

/**
 * True when this process is part of the PanWatch dev stack for `root`.
 * Does not match `dev-stop` itself.
 */
export function isPanwatchDevProcess({ name, commandLine, exePath, root }) {
  const cmd = normalizePath(commandLine);
  const exe = normalizePath(exePath);
  const rootNorm = normalizePath(root).replace(/\/+$/, "");
  const procName = String(name ?? "").toLowerCase().replace(/\.exe$/, "");
  const inProject = (cmd.includes(rootNorm) || exe.includes(rootNorm)) && rootNorm.length > 0;
  const isPython = procName.startsWith("python") || procName === "uvicorn";
  const runsServer = cmd.includes("server.py");
  const reloadWorker = cmd.includes("spawn_main");
  const venvPython = exe.includes("/.venv/") || exe.includes("/.venv/scripts/python");

  if (isPython) {
    if (!inProject && !(venvPython && (runsServer || reloadWorker))) return false;
    return runsServer || reloadWorker || cmd.includes("uvicorn");
  }

  if (!inProject) return false;
  if (cmd.includes("scripts/dev-stop.mjs")) return false;
  if (cmd.includes("scripts/dev-all.mjs")) return true;
  if (runsServer) return true;
  if (reloadWorker && (exe.includes("/.venv/") || cmd.includes("/.venv/"))) return true;
  if (cmd.includes("/frontend/") && (cmd.includes("vite") || cmd.includes("pnpm"))) return true;
  if (cmd.includes("vite") && cmd.includes("5183")) return true;
  return false;
}

export function collectKillSet(processes, root, selfPid) {
  const byParent = new Map();
  for (const processInfo of processes) {
    const parent = Number(processInfo.ParentProcessId ?? processInfo.parentPid ?? 0);
    const list = byParent.get(parent) ?? [];
    list.push(processInfo);
    byParent.set(parent, list);
  }

  const seen = new Set();
  const queue = [];
  for (const processInfo of processes) {
    const pid = Number(processInfo.ProcessId ?? processInfo.pid);
    if (!Number.isInteger(pid) || pid === selfPid || seen.has(pid)) continue;
    if (
      !isPanwatchDevProcess({
        name: processInfo.Name ?? processInfo.name,
        commandLine: processInfo.CommandLine ?? processInfo.commandLine,
        exePath: processInfo.ExecutablePath ?? processInfo.exePath,
        root,
      })
    ) {
      continue;
    }
    seen.add(pid);
    queue.push(processInfo);
  }

  const kill = [];
  while (queue.length) {
    const current = queue.shift();
    kill.push(current);
    const pid = Number(current.ProcessId ?? current.pid);
    for (const child of byParent.get(pid) ?? []) {
      const childPid = Number(child.ProcessId ?? child.pid);
      if (!Number.isInteger(childPid) || childPid === selfPid || seen.has(childPid)) continue;
      seen.add(childPid);
      queue.push(child);
    }
  }
  return kill;
}

/** Vite colors the word Local and the colon separately, so a raw includes("Local:") never hits. */
export function stripAnsi(text) {
  return String(text ?? "").replace(/\u001b\[[0-9;]*m/g, "");
}

export function outputHasReady(buffer, readyText) {
  if (!readyText) return false;
  return stripAnsi(buffer).includes(readyText);
}

export function taskkillAlreadyExited(error) {
  const message = String(error?.message || error || "");
  return /not found|没有找到|no running instance|not running/i.test(message);
}

export function baseProcessName(name) {
  return String(name ?? "")
    .toLowerCase()
    .replace(/\.exe$/, "");
}

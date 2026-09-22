/**
 * Stop the PanWatch dev stack: project processes, then listeners on :8000 / :5183.
 * Other programs on those ports are left alone and reported.
 */
import { execFile } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import {
  DEV_PORTS,
  DEV_PROCESS_NAMES,
  WSL_RELAY_NAMES,
  baseProcessName,
  collectKillSet,
  taskkillAlreadyExited,
} from "./dev-stack.mjs";

const execFileAsync = promisify(execFile);
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

async function listWindowsProcesses() {
  const command = [
    "Get-CimInstance Win32_Process |",
    "Select-Object ProcessId,ParentProcessId,Name,CommandLine,ExecutablePath |",
    "ConvertTo-Json -Compress -Depth 3",
  ].join(" ");
  const { stdout } = await execFileAsync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-Command", command],
    { cwd: projectRoot, maxBuffer: 32 * 1024 * 1024 }
  );
  const text = stdout.trim();
  if (!text) return [];
  const parsed = JSON.parse(text);
  return Array.isArray(parsed) ? parsed : [parsed];
}

async function listUnixProcesses() {
  const { stdout } = await execFileAsync("ps", ["-ax", "-o", "pid=,ppid=,command="], {
    cwd: projectRoot,
  });
  return stdout
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(/^(\d+)\s+(\d+)\s+(.*)$/);
      if (!match) return null;
      return {
        ProcessId: Number(match[1]),
        ParentProcessId: Number(match[2]),
        Name: "unix",
        CommandLine: match[3],
        ExecutablePath: "",
      };
    })
    .filter(Boolean);
}

async function taskkill(pid) {
  await execFileAsync("taskkill", ["/PID", String(pid), "/T", "/F"], { cwd: projectRoot });
}

async function listeningPidsWindows(port) {
  try {
    const { stdout } = await execFileAsync("netstat", ["-ano", "-p", "TCP"], { cwd: projectRoot });
    const pids = new Set();
    for (const line of stdout.split(/\r?\n/)) {
      const match = line.trim().match(/^TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)$/i);
      if (match && Number(match[1]) === port) pids.add(Number(match[2]));
    }
    return [...pids];
  } catch {
    return [];
  }
}

async function processNameWindows(pid) {
  try {
    const { stdout } = await execFileAsync(
      "tasklist",
      ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"],
      { cwd: projectRoot }
    );
    const match = stdout.match(/^"([^"]+)"/m);
    if (match) return match[1];
  } catch {
    /* CIM fallback */
  }
  try {
    const { stdout } = await execFileAsync(
      "powershell.exe",
      [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        `(Get-CimInstance Win32_Process -Filter "ProcessId=${Number(pid)}" -ErrorAction SilentlyContinue).Name`,
      ],
      { cwd: projectRoot }
    );
    return stdout.trim() || null;
  } catch {
    return null;
  }
}

async function sweepWindowsPorts() {
  for (const { port, name: role } of DEV_PORTS) {
    for (const pid of await listeningPidsWindows(port)) {
      if (pid === process.pid || pid === 0) continue;
      const name = await processNameWindows(pid);
      if (!name) {
        console.log(`[stop] port ${port} (${role}) owner PID ${pid} has no name — trying taskkill`);
        try {
          await taskkill(pid);
          console.log(`[stop] stopped PID ${pid} tree (port ${port})`);
        } catch (error) {
          console.warn(`[stop] taskkill PID ${pid} (port ${port}) failed: ${error?.message ?? error}`);
        }
        continue;
      }
      const base = baseProcessName(name);
      if (WSL_RELAY_NAMES.has(base)) {
        console.warn(
          `[stop] port ${port} is held by WSL relay ${name} (PID ${pid}). ` +
            'taskkill will not free it. Stop it inside WSL, or run "wsl --shutdown".'
        );
        continue;
      }
      if (DEV_PROCESS_NAMES.has(base)) {
        try {
          await taskkill(pid);
          console.log(`[stop] stopped PID ${pid} tree (port ${port}, ${name})`);
        } catch (error) {
          console.warn(`[stop] taskkill PID ${pid} (port ${port}) failed: ${error?.message ?? error}`);
        }
      } else {
        console.log(`[stop] port ${port} held by PID ${pid} (${name}) — not a dev process, left running`);
      }
    }
  }

  await new Promise((r) => setTimeout(r, 400));
  for (const { port } of DEV_PORTS) {
    const pids = (await listeningPidsWindows(port)).filter((pid) => pid !== process.pid && pid !== 0);
    if (pids.length) {
      console.warn(`[stop] port ${port} is still occupied (PID ${pids.join(",")})`);
    }
  }
}

async function sweepUnixPorts() {
  for (const { port } of DEV_PORTS) {
    let pids = [];
    try {
      const { stdout } = await execFileAsync("lsof", ["-ti", `tcp:${port}`, "-sTCP:LISTEN"]);
      pids = stdout
        .split("\n")
        .map((line) => Number(line.trim()))
        .filter(Boolean);
    } catch {
      continue;
    }
    for (const pid of pids) {
      if (pid === process.pid) continue;
      let commandLine = "";
      try {
        const { stdout } = await execFileAsync("ps", ["-p", String(pid), "-o", "command="]);
        commandLine = stdout.trim().toLowerCase();
      } catch {
        continue;
      }
      if ([...DEV_PROCESS_NAMES].some((name) => commandLine.includes(name))) {
        try {
          process.kill(pid, "SIGTERM");
          console.log(`[stop] stopped PID ${pid} (port ${port})`);
        } catch {
          /* already gone */
        }
      } else {
        console.log(`[stop] port ${port} held by PID ${pid} — not a dev process, left running`);
      }
    }
  }
}

async function main() {
  const processes =
    process.platform === "win32" ? await listWindowsProcesses() : await listUnixProcesses();
  const targets = collectKillSet(processes, projectRoot, process.pid);
  if (!targets.length) {
    console.log("[stop] no project dev processes found");
  }
  const ordered = [...targets].sort(
    (a, b) => Number(b.ProcessId ?? b.pid) - Number(a.ProcessId ?? a.pid)
  );
  for (const target of ordered) {
    const pid = Number(target.ProcessId ?? target.pid);
    const name = target.Name ?? target.name ?? "process";
    try {
      if (process.platform === "win32") await taskkill(pid);
      else process.kill(pid, "SIGTERM");
      console.log(`[stop] stopped PID ${pid} (${name})`);
    } catch (error) {
      if (taskkillAlreadyExited(error)) {
        console.log(`[stop] PID ${pid} already exited`);
        continue;
      }
      console.warn(`[stop] could not stop PID ${pid}: ${error?.message ?? error}`);
    }
  }

  if (process.platform === "win32") await sweepWindowsPorts();
  else await sweepUnixPorts();
  console.log("[stop] done");
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(`[stop] ${error?.stack || error}`);
    process.exitCode = 1;
  });
}

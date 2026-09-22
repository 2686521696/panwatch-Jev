import assert from "node:assert/strict";
import test from "node:test";

import {
  collectKillSet,
  isPanwatchDevProcess,
  outputHasReady,
  resolveDevReload,
  taskkillAlreadyExited,
} from "./dev-stack.mjs";

const root = "C:/Users/me/panwatch-Jev";

test("Windows defaults reload off; explicit DEV_RELOAD wins", () => {
  assert.equal(resolveDevReload({}, "win32"), "0");
  assert.equal(resolveDevReload({}, "linux"), "1");
  assert.equal(resolveDevReload({ DEV_RELOAD: "1" }, "win32"), "1");
  assert.equal(resolveDevReload({ DEV_RELOAD: "off" }, "linux"), "0");
});

test("matches the API, vite, and reload worker; ignores stop and unrelated python", () => {
  assert.equal(
    isPanwatchDevProcess({
      name: "python.exe",
      commandLine: `${root}\\.venv\\Scripts\\python.exe ${root}\\server.py`,
      exePath: `${root}\\.venv\\Scripts\\python.exe`,
      root,
    }),
    true
  );
  assert.equal(
    isPanwatchDevProcess({
      name: "python.exe",
      commandLine: "python -c from multiprocessing.spawn import spawn_main",
      exePath: `${root}\\.venv\\Scripts\\python.exe`,
      root,
    }),
    true
  );
  assert.equal(
    isPanwatchDevProcess({
      name: "node.exe",
      commandLine: `node ${root}\\frontend\\node_modules\\vite\\bin\\vite.js`,
      exePath: "C:/Program Files/nodejs/node.exe",
      root,
    }),
    true
  );
  assert.equal(
    isPanwatchDevProcess({
      name: "node.exe",
      commandLine: `node ${root}\\scripts\\dev-all.mjs`,
      exePath: "",
      root,
    }),
    true
  );
  assert.equal(
    isPanwatchDevProcess({
      name: "node.exe",
      commandLine: `node ${root}\\scripts\\dev-stop.mjs`,
      exePath: "",
      root,
    }),
    false
  );
  assert.equal(
    isPanwatchDevProcess({
      name: "python.exe",
      commandLine: "C:/other/python.exe other.py",
      exePath: "C:/other/python.exe",
      root,
    }),
    false
  );
});

test("Vite colored Local banner still counts as ready", () => {
  const banner = "  \u001b[32m➜\u001b[39m  \u001b[1mLocal\u001b[22m:   \u001b[36mhttp://localhost:\u001b[1m5183\u001b[22m/";
  assert.equal(banner.includes("Local:"), false);
  assert.equal(outputHasReady(banner, "Local:"), true);
  assert.equal(outputHasReady("Application startup complete.", "Application startup complete"), true);
});

test("taskkill not-found is treated as already exited", () => {
  assert.equal(taskkillAlreadyExited(new Error('错误: 没有找到进程 "32312"。')), true);
  assert.equal(taskkillAlreadyExited(new Error("Access is denied.")), false);
});

test("kill set includes children of a matched parent", () => {
  const processes = [
    {
      ProcessId: 10,
      ParentProcessId: 1,
      Name: "node.exe",
      CommandLine: `node ${root}/scripts/dev-all.mjs`,
      ExecutablePath: "",
    },
    {
      ProcessId: 11,
      ParentProcessId: 10,
      Name: "cmd.exe",
      CommandLine: "cmd /c pnpm dev",
      ExecutablePath: "",
    },
    {
      ProcessId: 99,
      ParentProcessId: 1,
      Name: "node.exe",
      CommandLine: "node C:/other/app.js",
      ExecutablePath: "",
    },
  ];
  const pids = collectKillSet(processes, root, 0).map((item) => item.ProcessId);
  assert.deepEqual(pids.sort((a, b) => a - b), [10, 11]);
});

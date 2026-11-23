import http from 'node:http';
import net from 'node:net';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

// Hyper-V/WSL can reserve 5310 on Windows and cause WinError 10013.
// Keep the Linux default and explicit BACKEND_PORT overrides intact.
const port = Number(process.env.BACKEND_PORT || (process.platform === 'win32' ? 15310 : 5310));

function isHealthyBackendBody(body) {
  try {
    const payload = JSON.parse(body);
    return payload?.status === 'healthy' && payload?.database === 'connected';
  } catch {
    return false;
  }
}

function getBackendReadiness() {
  return new Promise((resolve) => {
    const request = http.get(`http://127.0.0.1:${port}/api/health`, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => {
        if (body.length < 16_384) body += chunk;
      });
      response.on('end', () => {
        resolve({
          reachable: true,
          healthy: response.statusCode === 200 && isHealthyBackendBody(body),
        });
      });
    });
    request.setTimeout(1500, () => {
      request.destroy();
      resolve({ reachable: false, healthy: false });
    });
    request.on('error', () => resolve({ reachable: false, healthy: false }));
  });
}

function isPortReachable() {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: '127.0.0.1', port });
    socket.once('connect', () => {
      socket.destroy();
      resolve(true);
    });
    socket.once('error', () => resolve(false));
  });
}

const existingBackend = await getBackendReadiness();
if (existingBackend.reachable) {
  if (existingBackend.healthy) {
    console.log(`[dev:backend] Reusing existing healthy NetOps backend on port ${port}.`);
    process.exit(0);
  }
  console.error(`[dev:backend] NetOps responded on port ${port}, but /api/health is not healthy (database migration or startup failed).`);
  process.exit(1);
}

if (await isPortReachable()) {
  console.error(`[dev:backend] Port ${port} is occupied by another service, and it is not a NetOps backend.`);
  process.exit(1);
}

const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';

// On Windows, uvicorn's reloader restarts its worker with
// os.kill(pid, CTRL_C_EVENT).  A console Ctrl+C cannot be limited to one
// process, so every process attached to this terminal receives it -- this
// script, the frontend and the dev:internal supervisor all shut down and the
// whole `npm run dev` exits after the first backend file change.  On Windows
// the uvicorn reloader is therefore disabled (NEXORA_DEV_RELOAD=0) and this
// script watches backend/ itself and restarts Python with TerminateProcess,
// which signals nothing else.  Other platforms keep the uvicorn reloader.
const ownReload = process.platform === 'win32' && process.env.NEXORA_DEV_RELOAD !== '1';
const backendDir = path.resolve(process.cwd(), 'backend');
const excludedDirs = ['tests', 'artifacts', '__pycache__', '.pytest_cache'].map((name) => path.join(backendDir, name));
const reloadDebounceMs = 400;

let child = null;
let shuttingDown = false;
let restartRequested = false;
let restartTimer = null;
let pendingChange = '';

const startChild = () => {
  child = spawn(python, ['backend/main.py'], {
    cwd: process.cwd(),
    stdio: 'inherit',
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      NODE_ENV: 'development',
      // A local service startup must not replay persisted alert state into real
      // webhooks. Operators can explicitly opt in via the inherited value.
      NEXORA_AUTOMATIC_NOTIFICATIONS_ENABLED:
        process.env.NEXORA_AUTOMATIC_NOTIFICATIONS_ENABLED ?? '0',
      NEXORA_DEV_RELOAD: ownReload ? '0' : (process.env.NEXORA_DEV_RELOAD ?? '1'),
      PORT: String(port),
      PYTHONPATH: 'backend',
    },
  });

  child.on('error', (error) => {
    console.error(`[dev:backend] Failed to start Python backend: ${error.message}`);
    process.exit(1);
  });

  child.on('exit', (code, signal) => {
    if (shuttingDown) {
      process.exit(0);
    }
    if (restartRequested) {
      restartRequested = false;
      startChild();
      return;
    }
    if (signal) {
      process.kill(process.pid, signal);
    } else {
      process.exit(code ?? 1);
    }
  });
};

const stopChild = () => {
  if (child && child.exitCode === null && !child.killed) {
    child.kill();
  }
};

const requestRestart = () => {
  restartTimer = null;
  if (shuttingDown) return;
  console.log(`[dev:backend] Change detected in ${pendingChange || 'backend'}; restarting the backend.`);
  pendingChange = '';
  if (child && child.exitCode === null) {
    restartRequested = true;
    child.kill();
  } else {
    startChild();
  }
};

if (ownReload) {
  try {
    fs.watch(backendDir, { recursive: true }, (_event, filename) => {
      if (!filename || shuttingDown) return;
      const name = String(filename);
      if (!name.endsWith('.py')) return;
      const full = path.join(backendDir, name);
      if (excludedDirs.some((dir) => full === dir || full.startsWith(dir + path.sep))) return;
      pendingChange = path.join('backend', name);
      if (restartTimer) clearTimeout(restartTimer);
      restartTimer = setTimeout(requestRestart, reloadDebounceMs);
    });
    console.log('[dev:backend] Watching backend/*.py; the backend restarts on change (Windows-safe reload).');
  } catch (error) {
    console.error(`[dev:backend] File watching is unavailable (${error.message}); restart the backend manually after changes.`);
  }
}

process.once('SIGINT', () => {
  shuttingDown = true;
  stopChild();
});

process.once('SIGTERM', () => {
  shuttingDown = true;
  stopChild();
});

startChild();

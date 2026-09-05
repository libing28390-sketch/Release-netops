import http from 'node:http';
import net from 'node:net';
import { spawn } from 'node:child_process';

// 5010 is reserved by Hyper-V/WSL on some Windows hosts and fails with
// WinError 10013. Keep BACKEND_PORT as an explicit override for deployments.
const port = Number(process.env.BACKEND_PORT || 5310);

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

// Allow a worktree or CI harness to point at its own interpreter.  The
// default remains the repository-local venv used by normal development, but
// hard-coding that relative path makes an otherwise healthy checkout fail
// before the backend can report a useful configuration error.
const python = process.env.NEXORA_PYTHON
  || (process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
// A local database can contain real notification channel webhooks. Do not
// replay existing alert state merely by starting the dev server; opt in
// explicitly with NEXORA_AUTOMATIC_NOTIFICATIONS_ENABLED=1 when needed.
const automaticNotifications = process.env.NEXORA_AUTOMATIC_NOTIFICATIONS_ENABLED ?? '0';
const child = spawn(python, ['backend/main.py'], {
  cwd: process.cwd(),
  stdio: 'inherit',
  env: {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    NODE_ENV: 'development',
    PORT: String(port),
    PYTHONPATH: 'backend',
    NEXORA_AUTOMATIC_NOTIFICATIONS_ENABLED: automaticNotifications,
  },
});

let shuttingDown = false;

const stopChild = () => {
  if (child.exitCode === null && !child.killed) {
    child.kill();
  }
};

process.once('SIGINT', () => {
  shuttingDown = true;
  stopChild();
});

process.once('SIGTERM', () => {
  shuttingDown = true;
  stopChild();
});

child.on('error', (error) => {
  console.error(`[dev:backend] Failed to start Python backend: ${error.message}`);
  process.exit(1);
});

child.on('exit', (code, signal) => {
  if (shuttingDown) {
    process.exit(0);
  }
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code ?? 1);
  }
});

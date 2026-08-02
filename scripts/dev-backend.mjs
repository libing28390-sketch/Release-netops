import http from 'node:http';
import net from 'node:net';
import { spawn } from 'node:child_process';

// 5010 is reserved by Hyper-V/WSL on some Windows hosts and fails with
// WinError 10013. Keep BACKEND_PORT as an explicit override for deployments.
const port = Number(process.env.BACKEND_PORT || 5310);

function isNetOpsBackendRunning() {
  return new Promise((resolve) => {
    const request = http.get(`http://127.0.0.1:${port}/api/health`, (response) => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.setTimeout(1500, () => {
      request.destroy();
      resolve(false);
    });
    request.on('error', () => resolve(false));
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

if (await isNetOpsBackendRunning()) {
  console.log(`[dev:backend] Reusing existing NetOps backend on port ${port}.`);
  process.exit(0);
}

if (await isPortReachable()) {
  console.error(`[dev:backend] Port ${port} is occupied by another service, and it is not a NetOps backend.`);
  process.exit(1);
}

const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
const child = spawn(python, ['backend/main.py'], {
  cwd: process.cwd(),
  stdio: 'inherit',
  env: {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    NODE_ENV: 'development',
    PORT: String(port),
    PYTHONPATH: 'backend',
  },
});

child.on('error', (error) => {
  console.error(`[dev:backend] Failed to start Python backend: ${error.message}`);
  process.exit(1);
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code ?? 1);
  }
});

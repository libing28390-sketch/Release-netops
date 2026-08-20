import http from 'node:http';
import net from 'node:net';
import { spawn } from 'node:child_process';

// Keep the default aligned with vite.config.ts. VITE_PORT can still override
// it explicitly when another environment requires a different port.
const port = Number(process.env.VITE_PORT || 5400);

function readHttpRoot() {
  return new Promise((resolve) => {
    const request = http.get(`http://127.0.0.1:${port}/`, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => {
        if (body.length < 16_384) body += chunk;
      });
      response.on('end', () => {
        resolve({
          statusCode: response.statusCode || 0,
          body,
        });
      });
    });
    request.setTimeout(1500, () => {
      request.destroy();
      resolve({ statusCode: 0, body: '' });
    });
    request.on('error', () => resolve({ statusCode: 0, body: '' }));
  });
}

async function isNexoraFrontendRunning() {
  const response = await readHttpRoot();
  return response.statusCode === 200
    && /<title>\s*Nexora\s*<\/title>/i.test(response.body)
    && /id=["']root["']/i.test(response.body);
}

function isPortReachable() {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: '127.0.0.1', port });
    socket.setTimeout(1500);
    socket.once('connect', () => {
      socket.destroy();
      resolve(true);
    });
    socket.once('timeout', () => {
      socket.destroy();
      resolve(false);
    });
    socket.once('error', () => resolve(false));
  });
}

if (await isNexoraFrontendRunning()) {
  console.log(`[dev:frontend] Reusing existing Nexora frontend on port ${port}.`);
  process.exit(0);
}

if (await isPortReachable()) {
  console.error(`[dev:frontend] Port ${port} is occupied by another service, and it is not a Nexora frontend.`);
  process.exit(1);
}

const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js'], {
  cwd: process.cwd(),
  stdio: 'inherit',
  env: {
    ...process.env,
    CI: 'true',
    VITE_PORT: String(port),
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
  console.error(`[dev:frontend] Failed to start Vite: ${error.message}`);
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

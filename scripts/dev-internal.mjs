import http from 'node:http';
import { spawn } from 'node:child_process';

const backendPort = Number(process.env.BACKEND_PORT || (process.platform === 'win32' ? 15310 : 5310));
const frontendPort = Number(process.env.VITE_PORT || 5400);
const waitTimeoutMs = 120_000;

let shuttingDown = false;
let backendChild = null;
let frontendChild = null;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function requestText(url) {
  return new Promise((resolve) => {
    const request = http.get(url, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => {
        if (body.length < 16_384) body += chunk;
      });
      response.on('end', () => resolve({ statusCode: response.statusCode || 0, body }));
    });
    request.setTimeout(1500, () => {
      request.destroy();
      resolve({ statusCode: 0, body: '' });
    });
    request.on('error', () => resolve({ statusCode: 0, body: '' }));
  });
}

async function isBackendRunning() {
  const response = await requestText(`http://127.0.0.1:${backendPort}/api/health`);
  if (response.statusCode !== 200) return false;
  try {
    const payload = JSON.parse(response.body);
    return payload?.status === 'healthy' && payload?.database === 'connected';
  } catch {
    return false;
  }
}

async function isFrontendRunning() {
  const response = await requestText(`http://127.0.0.1:${frontendPort}/`);
  return response.statusCode === 200
    && /<title>\s*Nexora\s*<\/title>/i.test(response.body)
    && /id=["']root["']/i.test(response.body);
}

function startService(script, label) {
  const child = spawn(process.execPath, [script], {
    cwd: process.cwd(),
    stdio: 'inherit',
    env: { ...process.env },
  });
  child.on('error', (error) => {
    if (!shuttingDown) {
      console.error(`[dev:internal] ${label} failed to start: ${error.message}`);
      void shutdown(1);
    }
  });
  child.on('exit', (code, signal) => {
    if (!shuttingDown && code !== 0) {
      console.error(`[dev:internal] ${label} exited unexpectedly (code=${code ?? 'null'}, signal=${signal ?? 'none'})`);
      void shutdown(1);
    }
  });
  return child;
}

async function waitFor(check, child, label) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < waitTimeoutMs) {
    if (await check()) return true;
    if (child && child.exitCode !== null && child.exitCode !== 0) {
      console.error(`[dev:internal] ${label} stopped before becoming ready.`);
      return false;
    }
    await delay(500);
  }
  console.error(`[dev:internal] Timed out waiting for ${label}.`);
  return false;
}

async function shutdown(exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of [frontendChild, backendChild]) {
    if (child && child.exitCode === null && !child.killed) child.kill();
  }
  await delay(150);
  process.exit(exitCode);
}

process.once('SIGINT', () => { void shutdown(0); });
process.once('SIGTERM', () => { void shutdown(0); });
if (process.platform === 'win32') {
  process.once('SIGBREAK', () => { void shutdown(0); });
}

if (!await isBackendRunning()) {
  backendChild = startService('scripts/dev-backend.mjs', 'Backend');
  if (!await waitFor(isBackendRunning, backendChild, `backend on ${backendPort}`)) {
    await shutdown(1);
  }
} else {
  console.log(`[dev:internal] Reusing existing NetOps backend on port ${backendPort}.`);
}

if (!await isFrontendRunning()) {
  frontendChild = startService('scripts/dev-frontend.mjs', 'Frontend');
  if (!await waitFor(isFrontendRunning, frontendChild, `frontend on ${frontendPort}`)) {
    await shutdown(1);
  }
} else {
  console.log(`[dev:internal] Reusing existing Nexora frontend on port ${frontendPort}.`);
}

// Keep the supervisor alive while at least one service is owned by this run.
// If both services were reused, this process still acts as a clean Ctrl+C
// attachment point without starting duplicate listeners.
await new Promise(() => {});

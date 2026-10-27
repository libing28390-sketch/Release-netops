import http from 'node:http';
import { spawn } from 'node:child_process';

const backendPort = Number(process.env.BACKEND_PORT || (process.platform === 'win32' ? 15310 : 5310));
const frontendPort = Number(process.env.VITE_PORT || 5400);
const startupNoticeMs = 120_000;
const healthCheckIntervalMs = 5_000;
const unhealthyChecksBeforeRestart = 3;
const restartBaseDelayMs = 1_000;
const restartMaxDelayMs = 30_000;

let shuttingDown = false;
let healthMonitor = null;
const services = new Set();

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
    request.setTimeout(1_500, () => {
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

function createServiceSupervisor(script, label, healthCheck) {
  const state = {
    child: null,
    childStartedAt: 0,
    consecutiveHealthFailures: 0,
    healthCheck,
    healthCheckInProgress: false,
    label,
    restartAttempt: 0,
    restartTimer: null,
    script,
    stopped: false,
  };

  const clearRestartTimer = () => {
    if (!state.restartTimer) return;
    clearTimeout(state.restartTimer);
    state.restartTimer = null;
  };

  const recordHealthy = () => {
    state.consecutiveHealthFailures = 0;
    state.restartAttempt = 0;
    clearRestartTimer();
  };

  const startChild = () => {
    if (shuttingDown || state.stopped || (state.child && state.child.exitCode === null)) return;

    console.log(`[dev:internal] Starting ${state.label} with automatic recovery enabled.`);
    try {
      const child = spawn(process.execPath, [state.script], {
        cwd: process.cwd(),
        stdio: 'inherit',
        env: { ...process.env },
      });
      state.child = child;
      state.childStartedAt = Date.now();
      state.consecutiveHealthFailures = 0;

      child.on('error', (error) => {
        if (!shuttingDown && !state.stopped) {
          console.error(`[dev:internal] ${state.label} failed to start: ${error.message}`);
          scheduleRestart('process start failed');
        }
      });
      child.once('close', (code, signal) => {
        if (state.child === child) state.child = null;
        if (shuttingDown || state.stopped) return;
        scheduleRestart(`process exited (code=${code ?? 'null'}, signal=${signal ?? 'none'})`);
      });
    } catch (error) {
      console.error(`[dev:internal] ${state.label} failed to start: ${error?.message || error}`);
      scheduleRestart('process spawn failed');
    }
  };

  const scheduleRestart = (reason, immediate = false) => {
    if (shuttingDown || state.stopped || state.restartTimer) return;
    const attempt = state.restartAttempt + 1;
    const retryDelayMs = immediate
      ? 0
      : Math.min(restartBaseDelayMs * (2 ** state.restartAttempt), restartMaxDelayMs);
    if (!immediate) state.restartAttempt += 1;
    console.error(
      `[dev:internal] ${state.label} unavailable (${reason}); retry ${attempt} in ${retryDelayMs}ms.`,
    );
    state.restartTimer = setTimeout(async () => {
      state.restartTimer = null;
      if (shuttingDown || state.stopped) return;
      if (await state.healthCheck()) {
        recordHealthy();
        return;
      }
      startChild();
    }, retryDelayMs);
  };

  const reconcile = async () => {
    if (shuttingDown || state.stopped || state.healthCheckInProgress) return;
    state.healthCheckInProgress = true;
    try {
      if (await state.healthCheck()) {
        recordHealthy();
        return;
      }

      // Give a newly started service up to the normal startup window before
      // restarting it for an unhealthy readiness probe.
      if (state.child && state.child.exitCode === null) {
        if (Date.now() - state.childStartedAt < startupNoticeMs) return;
        state.consecutiveHealthFailures += 1;
        if (state.consecutiveHealthFailures >= unhealthyChecksBeforeRestart) {
          console.error(`[dev:internal] ${state.label} failed ${state.consecutiveHealthFailures} health checks; restarting it.`);
          state.consecutiveHealthFailures = 0;
          state.child.kill();
        }
        return;
      }

      // This also recovers a service that was already running when this
      // supervisor started, without killing an unowned process. Require the
      // same consecutive-failure threshold used for owned children so a
      // transiently slow health endpoint does not trigger repeated launches.
      state.consecutiveHealthFailures += 1;
      if (state.consecutiveHealthFailures < unhealthyChecksBeforeRestart) return;
      state.consecutiveHealthFailures = 0;
      scheduleRestart(`health check failed ${unhealthyChecksBeforeRestart} consecutive times`);
    } finally {
      state.healthCheckInProgress = false;
    }
  };

  const waitUntilHealthy = async () => {
    let lastNoticeAt = Date.now();
    while (!shuttingDown && !state.stopped) {
      if (await state.healthCheck()) {
        recordHealthy();
        return true;
      }
      await reconcile();
      if (Date.now() - lastNoticeAt >= startupNoticeMs) {
        console.error(`[dev:internal] Still waiting for ${state.label}; automatic retries continue.`);
        lastNoticeAt = Date.now();
      }
      await delay(500);
    }
    return false;
  };

  const ensureRunning = async () => {
    if (await state.healthCheck()) {
      recordHealthy();
      console.log(`[dev:internal] Reusing healthy ${state.label}.`);
      return true;
    }
    if (!state.child && !state.restartTimer) scheduleRestart('initial readiness check failed', true);
    return waitUntilHealthy();
  };

  const stop = () => {
    state.stopped = true;
    clearRestartTimer();
    if (state.child && state.child.exitCode === null && !state.child.killed) state.child.kill();
  };

  const supervisor = { ensureRunning, reconcile, stop };
  services.add(supervisor);
  return supervisor;
}

async function shutdown(exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  if (healthMonitor) clearInterval(healthMonitor);
  for (const service of services) service.stop();
  await delay(500);
  process.exit(exitCode);
}

process.once('SIGINT', () => { void shutdown(0); });
process.once('SIGTERM', () => { void shutdown(0); });
if (process.platform === 'win32') {
  process.once('SIGBREAK', () => { void shutdown(0); });
}

const backendSupervisor = createServiceSupervisor('scripts/dev-backend.mjs', 'Backend', isBackendRunning);
const frontendSupervisor = createServiceSupervisor('scripts/dev-frontend.mjs', 'Frontend', isFrontendRunning);

if (!await backendSupervisor.ensureRunning()) await shutdown(1);
if (!await frontendSupervisor.ensureRunning()) await shutdown(1);

healthMonitor = setInterval(() => {
  void backendSupervisor.reconcile();
  void frontendSupervisor.reconcile();
}, healthCheckIntervalMs);

// Keep monitoring service readiness. Owned children restart with capped
// exponential backoff; reused services are relaunched if their port goes down.
await new Promise(() => {});

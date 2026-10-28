import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const viteCli = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url));
const startedAt = Date.now();
const child = spawn(process.execPath, [viteCli, 'build'], {
  env: {
    ...process.env,
    NODE_OPTIONS: process.env.NODE_OPTIONS || '--max-old-space-size=4096',
  },
  stdio: 'inherit',
});

let settled = false;
const heartbeat = setInterval(() => {
  const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
  console.log(`[frontend-build] Vite is still running (${elapsedSeconds}s elapsed).`);
}, 10_000);

function finish(exitCode) {
  if (settled) return;
  settled = true;
  clearInterval(heartbeat);
  process.exitCode = exitCode;
}

child.once('error', (error) => {
  console.error(`[frontend-build] Could not start Vite: ${error.message}`);
  finish(1);
});

child.once('close', (exitCode, signal) => {
  if (settled) return;
  if (signal) {
    console.error(`[frontend-build] Vite stopped by ${signal}.`);
    finish(1);
    return;
  }
  const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
  console.log(`[frontend-build] Vite exited with code ${exitCode ?? 1} (${elapsedSeconds}s elapsed).`);
  finish(exitCode ?? 1);
});

process.once('SIGINT', () => child.kill('SIGINT'));
process.once('SIGTERM', () => child.kill('SIGTERM'));

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

/**
 * Startup Logger Utility with 90-day Retention and Gzip Compression
 * Automatically persists Frontend + Backend console output.
 */

const logDir = path.resolve(__dirname, '../data/logs');
if (!fs.existsSync(logDir)) fs.mkdirSync(logDir, { recursive: true });

const logFile = path.join(logDir, 'startup.log');

// ─── LOG ROTATION & CLEANUP ───
function rotateAndCleanup() {
  try {
    const files = fs.readdirSync(logDir);
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 90);

    if (fs.existsSync(logFile) && fs.statSync(logFile).size > 0) {
      const stats = fs.statSync(logFile);
      const mtime = new Date(stats.mtime);
      const dateStr = mtime.toISOString().split('T')[0];
      const archivePath = `${logFile}.${dateStr}.${Date.now()}`;
      
      fs.renameSync(logFile, archivePath);

      const gzip = zlib.createGzip();
      const source = fs.createReadStream(archivePath);
      const destination = fs.createWriteStream(`${archivePath}.gz`);
      source.pipe(gzip).pipe(destination).on('finish', () => {
        fs.unlinkSync(archivePath);
      });
    }

    files.forEach(file => {
      if ((file.startsWith('startup.log.') || file.startsWith('netops.log.')) && file.endsWith('.gz')) {
        const dateMatch = file.match(/(\d{4}-\d{2}-\d{2})/);
        if (dateMatch) {
          const fileDate = new Date(dateMatch[1]);
          if (fileDate < cutoff) {
            fs.unlinkSync(path.join(logDir, file));
          }
        }
      }
    });
  } catch (err) {}
}

rotateAndCleanup();

const logStream = fs.createWriteStream(logFile, { flags: 'a', encoding: 'utf8' });
const timestamp = () => new Date().toISOString();

logStream.write(`\n\n[SYSTEM] [${timestamp()}] >>> NEW SESSION (${process.argv.includes('--prod') ? 'PROD' : 'DEV'}) <<<\n`);

const targetScript = process.argv.includes('--prod') ? 'start:internal' : 'dev:internal';

const proc = spawn('npm', ['run', targetScript], {
  shell: true,
  env: { ...process.env, FORCE_COLOR: 'true' },
  stdio: ['inherit', 'pipe', 'pipe']
});

const stripAnsi = (str) => str.replace(/\u001b\[[0-9;]*m/g, '');

proc.stdout.on('data', (data) => {
  process.stdout.write(data);
  logStream.write(stripAnsi(data.toString()));
});

proc.stderr.on('data', (data) => {
  process.stderr.write(data);
  logStream.write(`[ERROR] ${stripAnsi(data.toString())}`);
});

proc.on('close', (code) => {
  logStream.write(`\n[SYSTEM] [${timestamp()}] >>> SESSION CLOSED WITH CODE ${code} <<<\n`);
  logStream.end();
  process.exit(code);
});

process.on('SIGINT', () => proc.kill('SIGINT'));
process.on('SIGTERM', () => proc.kill('SIGTERM'));
process.on('exit', () => proc.kill());

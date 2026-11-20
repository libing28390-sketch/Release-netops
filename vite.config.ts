import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import fs from 'fs';
import path from 'path';
import zlib from 'zlib';
import { defineConfig, loadEnv } from 'vite';

function buildProgressPlugin() {
  let transformedModules = 0;
  let startedAt = 0;

  const report = (message: string) => {
    const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
    console.log(`[frontend-build] ${message} (${elapsedSeconds}s elapsed)`);
  };

  return {
    name: 'nexora-build-progress',
    apply: 'build' as const,
    enforce: 'post' as const,
    buildStart() {
      transformedModules = 0;
      startedAt = Date.now();
      report('Vite build started');
    },
    transform() {
      transformedModules += 1;
      if (transformedModules % 250 === 0) {
        report(`${transformedModules} modules transformed`);
      }
      return null;
    },
    buildEnd() {
      report(`module transform finished; ${transformedModules} modules processed, generating output`);
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  // Windows/Hyper-V/WSL may reserve broad dynamic ranges. Keep the default
  // outside the currently reserved 5241-5340 range; VITE_PORT remains an
  // explicit override for deployments or another local environment.
  const frontendPort = Number(env.VITE_PORT || process.env.VITE_PORT || '5400');
  const backendPort = process.env.BACKEND_PORT || (process.platform === 'win32' ? '15310' : '5310');
  const apiTarget = process.env.VITE_API_TARGET || `http://127.0.0.1:${backendPort}`;
  function gzipPrecompressPlugin() {
    let outDir = 'dist';
    return {
      name: 'nexora-gzip-precompress',
      apply: 'build' as const,
      configResolved(config: { build: { outDir: string } }) {
        outDir = config.build.outDir || 'dist';
      },
      closeBundle() {
        const assetsDir = path.resolve(__dirname, outDir, 'assets');
        if (!fs.existsSync(assetsDir)) return;
        let compressedCount = 0;
        for (const entry of fs.readdirSync(assetsDir)) {
          if (!/\.(js|css|svg)$/i.test(entry)) continue;
          const filePath = path.join(assetsDir, entry);
          const stat = fs.statSync(filePath);
          if (!stat.isFile() || stat.size < 1024) continue;
          const raw = fs.readFileSync(filePath);
          const gz = zlib.gzipSync(raw, { level: 9 });
          if (gz.length < raw.length) {
            fs.writeFileSync(`${filePath}.gz`, gz);
            compressedCount += 1;
          }
        }
        console.log(`[frontend-build] Precompressed ${compressedCount} static assets (.gz)`);
      },
    };
  }

  return {
    plugins: [react(), tailwindcss(), buildProgressPlugin(), gzipPrecompressPlugin()],
    define: {
      'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY),
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    optimizeDeps: {
      // The default HTML glob also finds historical dist-* validation builds.
      // Follow imports from the application entry instead of scanning those copies.
      entries: ['index.html'],
    },
    build: {
      // The remaining three.js chunk is an intentionally lazy WebGL dependency
      // for the rack/home 3D views; keep the warning focused on initial app code.
      chunkSizeWarningLimit: 768,
      rollupOptions: {
        output: {
          manualChunks(id) {
            const moduleId = id.replaceAll('\\', '/');
            if (!moduleId.includes('/node_modules/')) return undefined;

            // Match package boundaries instead of using `id.includes('react')`.
            // The latter also pulled @react-three/* and react-markdown into the
            // core React chunk, making the initial bundle unnecessarily large.
            if (moduleId.includes('/node_modules/react-router/')
              || moduleId.includes('/node_modules/react-router-dom/')
              || moduleId.includes('/node_modules/@remix-run/router/')) {
              return 'router-vendor';
            }

            if (moduleId.includes('/node_modules/react/')
              || moduleId.includes('/node_modules/react-dom/')
              || moduleId.includes('/node_modules/scheduler/')
              || moduleId.includes('/node_modules/react-is/')
              || moduleId.includes('/node_modules/use-sync-external-store/')) {
              return 'react-vendor';
            }

            // Recharts and React Three Fiber both depend on this shared
            // module. Keep it with React so Rollup cannot create a
            // charts-vendor -> react-vendor -> charts-vendor cycle.
            if (moduleId.includes('/node_modules/recharts/')
              || moduleId.includes('/node_modules/d3-')
              || moduleId.includes('/node_modules/d3/')) {
              return 'charts-vendor';
            }

            if (moduleId.includes('/node_modules/xlsx/')
              || moduleId.includes('/node_modules/html-to-image/')
              || moduleId.includes('/node_modules/html2canvas/')) {
              return 'export-vendor';
            }

            if (moduleId.includes('/node_modules/lucide-react/')
              || moduleId.includes('/node_modules/motion/')
              || moduleId.includes('/node_modules/motion-dom/')
              || moduleId.includes('/node_modules/framer-motion/')) {
              return 'ui-vendor';
            }

            if (moduleId.includes('/node_modules/react-markdown/')
              || moduleId.includes('/node_modules/remark-gfm/')
              || moduleId.includes('/node_modules/unified/')
              || moduleId.includes('/node_modules/remark-')) {
              return 'markdown-vendor';
            }

            return undefined;
          },
        },
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modifyâfile watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      port: frontendPort,
      strictPort: true,
      host: '0.0.0.0',
      watch: {
        // Keep Vite focused on frontend sources so Linux doesn't exhaust inotify
        // watchers on `.venv`, backend code, or backup data.
        ignored: [
          '**/.git/**',
          '**/node_modules/**',
          '**/.venv/**',
          '**/backend/**',
          '**/backup/**',
          '**/data/**',
          '**/dist/**',
          '**/dist-*/**',
          '**/.codex-*/**',
        ],
      },
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          ws: true,
        },
        '/docs': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/redoc': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/openapi.json': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  };
});

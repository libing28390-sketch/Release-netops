import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  // Windows/Hyper-V/WSL may reserve broad dynamic ranges. Keep the default
  // outside the currently reserved 5241-5340 range; VITE_PORT remains an
  // explicit override for deployments or another local environment.
  const frontendPort = Number(env.VITE_PORT || process.env.VITE_PORT || '5400');
  return {
    plugins: [react(), tailwindcss()],
    define: {
      'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY),
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
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

            if (moduleId.includes('/node_modules/@react-three/')) {
              return 'react-three-vendor';
            }

            if (moduleId.includes('/node_modules/three/')) {
              return 'three-vendor';
            }

            if (moduleId.includes('/node_modules/three-')
              || moduleId.includes('/node_modules/troika-')
              || moduleId.includes('/node_modules/camera-controls/')) {
              return 'webgl-addons-vendor';
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
        // watchers on `.venv`, backend code, backup data, or SQLite artifacts.
        ignored: [
          '**/.git/**',
          '**/node_modules/**',
          '**/.venv/**',
          '**/backend/**',
          '**/backup/**',
          '**/data/**',
          '**/dist/**',
          '**/.codex-build-validation*/**',
        ],
      },
      proxy: {
        '/api': {
          target: process.env.VITE_API_TARGET || 'http://127.0.0.1:5310',
          changeOrigin: true,
          ws: true,
        },
        '/docs': {
          target: process.env.VITE_API_TARGET || 'http://127.0.0.1:5310',
          changeOrigin: true,
        },
        '/redoc': {
          target: process.env.VITE_API_TARGET || 'http://127.0.0.1:5310',
          changeOrigin: true,
        },
        '/openapi.json': {
          target: process.env.VITE_API_TARGET || 'http://127.0.0.1:5310',
          changeOrigin: true,
        },
      },
    },
  };
});

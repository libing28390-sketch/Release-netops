import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
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
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return undefined;

            if (id.includes('react') || id.includes('scheduler')) {
              return 'react-vendor';
            }

            if (id.includes('react-router')) {
              return 'router-vendor';
            }

            if (id.includes('recharts') || id.includes('/d3-')) {
              return 'charts-vendor';
            }

            if (id.includes('xlsx') || id.includes('html-to-image') || id.includes('html2canvas')) {
              return 'export-vendor';
            }

            if (id.includes('lucide-react') || id.includes('motion')) {
              return 'ui-vendor';
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
      port: 5150,
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
        ],
      },
      proxy: {
        '/api': {
          target: process.env.VITE_API_TARGET || 'http://127.0.0.1:5010',
          changeOrigin: true,
          ws: true,
        },
      },
    },
  };
});

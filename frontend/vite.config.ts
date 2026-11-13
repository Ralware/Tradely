import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backendTarget = process.env.VITE_DEV_BACKEND ?? 'http://127.0.0.1:8000';

// The frontend talks to FastAPI through the /api prefix. In development the
// Vite server proxies those calls, so no CORS configuration is needed on the
// Python side. In production, serve `dist/` from any static host and reverse
// proxy /api to the FastAPI process.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: backendTarget, changeOrigin: true },
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
    proxy: {
      '/api': { target: backendTarget, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ['lightweight-charts'],
          react: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
});

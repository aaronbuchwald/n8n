import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Where the FastAPI server lives. Overridable so `pnpm dev` / the e2e test can
// point at a non-default port without editing this file.
const API_TARGET = process.env.GE_API_TARGET ?? 'http://127.0.0.1:8000';

// Proxy `/api/*` to the engine server. Applied to BOTH the dev server and
// `vite preview`, so the built bundle is served same-origin with `/api` during
// local runs and the Playwright e2e (see web/README.md). In real deployment the
// built `dist/` and the API share an origin behind a reverse proxy.
const proxy = {
  '/api': {
    target: API_TARGET,
    changeOrigin: true,
  },
};

// Relative base so the built bundle works when served from any path / file host.
// All assets are emitted locally into dist/ — nothing is fetched from a CDN.
export default defineConfig({
  base: './',
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
  // Monaco's web worker (editor.worker) is imported via `?worker`; emit it as an
  // ES module worker so it is bundled into dist/ and loaded same-origin — never
  // fetched from a CDN.
  worker: { format: 'es' },
  // Pre-bundle Monaco's ESM entry so dev/preview resolve it locally too.
  optimizeDeps: {
    include: ['monaco-editor/esm/vs/editor/editor.api'],
  },
  build: {
    outDir: 'dist',
    // Fail loud if anything tries to resolve to an external URL at build time.
    rollupOptions: {},
  },
});

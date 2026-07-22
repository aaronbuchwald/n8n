import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Relative base so the built bundle works when served from any path / file host.
// All assets are emitted locally into dist/ — nothing is fetched from a CDN.
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: 'dist',
    // Fail loud if anything tries to resolve to an external URL at build time.
    rollupOptions: {},
  },
});

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite serves src/ in dev and outputs to dist/ on build.
// In dev, run `npm run dev` on :5173 — it proxies /api/* to server.py on :3000.
// In prod, server.py serves the built dist/ directly.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:3000',
        changeOrigin: true,
      },
      // Serve avatar GLBs and any other static assets from the existing ui/ dir.
      '/avatar-zoo': {
        target: 'http://localhost:3000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      // TalkingHead + lipsync-en + three are loaded from the browser import
      // map (see index.html). Keep them out of the bundle so the CDN modules
      // are used.
      external: [/^three($|\/)/, 'talkinghead', 'lipsync-en'],
    },
  },
});

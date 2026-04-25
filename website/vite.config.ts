import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// GitHub Pages serves project sites under /<repo>/ — the base path must match
// or all asset/script URLs 404. Override at build time with VITE_BASE=/ for
// custom domains or root deploys.
const base = process.env.VITE_BASE ?? '/HRKit/';

export default defineConfig({
  base,
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1',
  },
});

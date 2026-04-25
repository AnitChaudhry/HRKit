import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// GitHub Pages serves project sites under /<repo>/ — the base path must match
// or all asset/script URLs 404. Hard-coded to '/HRKit/' for the
// AnitChaudhry/HRKit Pages site; change here if forking under a different name
// or deploying under a custom domain.
export default defineConfig({
  base: '/HRKit/',
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1',
  },
});

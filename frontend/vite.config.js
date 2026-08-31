import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// http://127.0.0.1:5173 is already in main.py's CORS allow-list, so `npm run
// dev` talks to the API cross-origin with no extra config. `npm run build`
// emits ./dist, which main.py serves itself -- there the page and the API
// share an origin and CORS never comes into it.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  build: { outDir: "dist", sourcemap: true },
});

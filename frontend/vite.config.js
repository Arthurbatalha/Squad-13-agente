import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Em desenvolvimento, /api é encaminhado ao Uvicorn (porta 8000): sem CORS no navegador.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.js",
    restoreMocks: true,
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
});

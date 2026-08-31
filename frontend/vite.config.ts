import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  base: mode === "extension" ? "./" : "/app/",
  plugins: [react()],
  publicDir: mode === "extension" ? "extension" : false,
  build: mode === "extension" ? { outDir: "dist-extension", emptyOutDir: true } : undefined,
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000" },
  },
}));

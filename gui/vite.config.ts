import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiPort = process.env.KGS_API_PORT || "5001";
const guiPort = Number(process.env.KGS_GUI_PORT || "5173");
const apiTarget = `http://127.0.0.1:${apiPort}`;

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: guiPort,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
      "/health": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});

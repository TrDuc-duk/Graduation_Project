import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: trình duyệt chỉ gọi /api cùng origin; Vite chuyển tiếp tới backend dev (không truy cập DB trực tiếp)
const backend = process.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8001";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": "/src" } },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": { target: backend, changeOrigin: true } },
  },
});

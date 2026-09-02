import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时 `pnpm dev` 跑在 5173，把 /api 与 /report 代理到 FastAPI（默认 18000）；
// 生产由 FastAPI 直接托管 dist，无需代理。
const BACKEND = process.env.JOB_AGENT_API || "http://127.0.0.1:18000";

export default defineConfig({
  plugins: [react()],
  base: "./", // 相对路径，便于被挂在任意根路径下托管
  server: {
    proxy: {
      "/api": BACKEND,
      "/report": BACKEND,
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});

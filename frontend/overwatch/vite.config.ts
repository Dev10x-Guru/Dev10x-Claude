import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

const daemon = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [svelte()],
  base: "/",
  build: {
    outDir: "../../src/dev10x/comm/overwatch/static",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    proxy: {
      "/api": daemon,
      "/answer": daemon,
      "/keys": daemon,
      "/reply": daemon,
    },
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
});

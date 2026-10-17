import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    host: "::",
    port: 8080,
    proxy: {
      // Local dev helper to avoid CORS when hitting FastAPI directly.
      // Use `VITE_FPL_TEAM_RECOMMENDATION_URL="/recommendations?..."`
      "/recommendations": {
        target: process.env.VITE_FPL_API_BASE_URL ?? "https://fpl-assistant-api.fly.dev/",
        changeOrigin: true,
      },
      "/squad": {
        target: process.env.VITE_FPL_API_BASE_URL ?? "https://fpl-assistant-api.fly.dev/",
        changeOrigin: true,
        // The dev-only SquadPicker SPA page also lives at /squad. Let browser
        // navigations (Accept: text/html) fall through to the SPA; only proxy
        // real API calls (fetch, Accept: */*) to the backend /squad endpoint.
        bypass(req) {
          if (req.headers.accept?.includes("text/html")) return req.url;
        },
      },
      "/fixtures": {
        target: process.env.VITE_FPL_API_BASE_URL ?? "https://fpl-assistant-api.fly.dev/",
        changeOrigin: true,
      },
      "/chips": {
        target: process.env.VITE_FPL_API_BASE_URL ?? "https://fpl-assistant-api.fly.dev/",
        changeOrigin: true,
      },
    },
  },
  plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}));

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// While developing, the dashboard runs on port 5173 and passes API calls on
// to the RahSaaf server. Once built, the server serves the dashboard itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Port dédié à la console admin, distinct de l'espace client.
    port: 5174,
    // En développement, l'API passe par la passerelle (WAF) comme en production.
    proxy: { "/api": "http://localhost:8080" },
  },
});
